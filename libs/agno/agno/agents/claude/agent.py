from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agno.agents.base import BaseExternalAgent, ExternalRunResult, ExternalRunWarningEvent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.exceptions import ModelProviderError
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.cancel import araise_if_cancelled
from agno.utils.log import log_debug, log_warning


def _sdk() -> Any:
    """Lazy-import the claude_agent_sdk module."""
    try:
        import claude_agent_sdk  # type: ignore

        return claude_agent_sdk
    except ImportError as e:
        raise ImportError("claude-agent-sdk is required: pip install claude-agent-sdk") from e


# Result subtypes for limits the user configured; a retry would grant a fresh allowance.
_LIMIT_SUBTYPES = {"error_max_turns", "error_max_budget_usd", "error_max_structured_output_retries"}
# AssistantMessage.error values that fail the same way on every attempt.
_PERMANENT_ASSISTANT_ERRORS = {"authentication_failed", "billing_error", "invalid_request"}


class ClaudeResultError(RuntimeError):
    """An error result from Claude Code, with the fields the SDK's own ResultError carries."""

    def __init__(
        self,
        message: str,
        *,
        subtype: Optional[str] = None,
        errors: Optional[List[str]] = None,
        api_error_status: Optional[int] = None,
        assistant_error: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.subtype = subtype
        self.errors = errors
        self.api_error_status = api_error_status
        self.assistant_error = assistant_error


@dataclass
class ClaudeAgent(BaseExternalAgent):
    """Adapter for the Claude Agent SDK (claude-agent-sdk).

    Wraps a per-run Claude Agent SDK client so it can be used with AgentOS
    endpoints or standalone via .run() / .print_response().

    The Claude Agent SDK runs Claude Code as a subprocess. Tool execution is handled
    internally by the SDK — you configure tools via allowed_tools and MCP servers.

    Args:
        name: Display name for this agent.
        id: Unique identifier (auto-generated from name if not set).
        system_prompt: Optional system prompt for the agent.
        model: Model to use (e.g. "claude-sonnet-4-20250514"). Defaults to SDK default.
        allowed_tools: List of tools the agent can use (e.g. ["Read", "Bash", "WebSearch"]).
        disallowed_tools: List of tools to block.
        permission_mode: Permission mode ("default", "acceptEdits", "plan", "bypassPermissions").
        max_turns: Maximum number of turns.
        max_budget_usd: Maximum cost budget in USD.
        cwd: Working directory for the agent.
        mcp_servers: MCP server configurations for custom tools.
        options_kwargs: Additional kwargs passed to ClaudeAgentOptions.
        retries: Number of times to retry a failed run. Cancelled runs, max_turns / max_budget_usd limits
            and errors that would fail again (authentication, billing, invalid requests) are not retried.
        delay_between_retries: Seconds to wait before each retry.
        exponential_backoff: Double the delay after each failed attempt.

    Example:
        from agno.agents.claude import ClaudeAgent

        agent = ClaudeAgent(
            name="Claude Coder",
            allowed_tools=["Read", "Edit", "Bash"],
            permission_mode="acceptEdits",
            max_turns=10,
        )

        # Standalone usage
        agent.print_response("Read main.py and summarize it", stream=True)

        # Or deploy with AgentOS
        from agno.os import AgentOS
        AgentOS(agents=[agent])
    """

    system_prompt: Optional[str] = None
    model: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    disallowed_tools: Optional[List[str]] = None
    permission_mode: Optional[str] = None
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    cwd: Optional[str] = None
    project_key: Optional[str] = None
    _store_warning_logged: bool = field(default=False, init=False, repr=False)
    _warn_unstable_project_key: bool = field(default=False, init=False, repr=False)
    _store_skipped_logged: bool = field(default=False, init=False, repr=False)
    mcp_servers: Optional[Dict[str, Any]] = None
    options_kwargs: Dict[str, Any] = field(default_factory=dict)
    framework: str = "claude-agent-sdk"

    # Key under which the SDK session id is stored in the Agno session's session_data.
    _SESSION_KEY = "claude_sdk_session_id"

    # Fallback Agno session_id -> SDK session id map, used when no db is configured.
    _sdk_session_ids: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        # Without id or name, get_id() is random per process, so the default key cannot be shared across replicas.
        self._warn_unstable_project_key = self.project_key is None and self.id is None and self.name is None
        super().__post_init__()
        if self.project_key is None:
            self.project_key = self.get_id()

    def _transcript_store(self, agno_session_id: Optional[str]) -> Optional[Any]:
        """The transcript store for this run, or None when transcripts stay on local disk.

        No store is attached when the database lacks transcript storage, when the caller
        supplies a session_store of their own, or when file checkpointing is enabled, since
        the SDK refuses to combine the two.
        """
        if self.db is None or agno_session_id is None:
            return None
        base = AsyncBaseDb if isinstance(self.db, AsyncBaseDb) else BaseDb
        if type(self.db).append_transcript_entries is base.append_transcript_entries:
            if not self._store_warning_logged:
                log_warning(
                    f"{type(self.db).__name__} does not support Claude transcript storage, so transcripts stay on "
                    "this machine's disk and another replica cannot resume them. Use PostgresDb or SqliteDb "
                    "(sync or async) to store transcripts in the database."
                )
                self._store_warning_logged = True
            return None
        if "session_store" in self.options_kwargs:
            if not self._store_skipped_logged:
                log_debug("ClaudeAgent uses the session_store from options_kwargs; Agno transcript storage is off.")
                self._store_skipped_logged = True
            return None
        if self.options_kwargs.get("enable_file_checkpointing"):
            if not self._store_skipped_logged:
                log_warning(
                    "ClaudeAgent cannot store transcripts in the database while enable_file_checkpointing is set; "
                    "transcripts stay on local disk and other replicas resume from Agno history only."
                )
                self._store_skipped_logged = True
            return None
        from agno.agents.claude.session_store import AgnoSessionStore

        store = AgnoSessionStore(self.db, self.project_key or self.get_id(), agno_session_id)
        if self._warn_unstable_project_key:
            log_warning(
                f"ClaudeAgent has no id, name or project_key; transcripts are stored under the generated key "
                f"'{self.project_key}' and other processes will not resume them. Set id or project_key."
            )
            self._warn_unstable_project_key = False
        return store

    def _build_options(
        self,
        *,
        streaming: bool = False,
        resume: Optional[str] = None,
        agno_session_id: Optional[str] = None,
        session_store: Optional[Any] = None,
    ) -> Any:
        """Build ClaudeAgentOptions from agent config.

        The transcript store is taken from session_store when given, otherwise created for
        agno_session_id.
        """
        sdk = _sdk()

        opts: Dict[str, Any] = {}

        if self.system_prompt:
            opts["system_prompt"] = self.system_prompt
        if self.model:
            opts["model"] = self.model
        if self.allowed_tools:
            opts["allowed_tools"] = self.allowed_tools
        if self.disallowed_tools:
            opts["disallowed_tools"] = self.disallowed_tools
        if self.permission_mode:
            opts["permission_mode"] = self.permission_mode
        if self.max_turns is not None:
            opts["max_turns"] = self.max_turns
        if self.max_budget_usd is not None:
            opts["max_budget_usd"] = self.max_budget_usd
        if self.cwd:
            opts["cwd"] = self.cwd
        if self.mcp_servers:
            opts["mcp_servers"] = self.mcp_servers

        # Enable token-level streaming when streaming is requested
        if streaming:
            opts["include_partial_messages"] = True

        if resume:
            opts["resume"] = resume

        opts.update(self.options_kwargs)
        store = session_store if session_store is not None else self._transcript_store(agno_session_id)
        if store is not None:
            opts["session_store"] = store
        return sdk.ClaudeAgentOptions(**opts)

    # ---------------------------------------------------------------------------
    # Agno session <-> SDK session mapping
    # ---------------------------------------------------------------------------

    def _get_sdk_session_id(self, session: Any, session_id: Optional[str]) -> Optional[str]:
        if session is not None and session.session_data:
            sdk_session_id = session.session_data.get(self._SESSION_KEY)
            if sdk_session_id:
                return str(sdk_session_id)
        if session_id:
            return self._sdk_session_ids.get(session_id)
        return None

    def _remember_sdk_session(self, session: Any, session_id: Optional[str], sdk_session_id: Optional[str]) -> None:
        """Stash the SDK session id on the session (persisted by the base class) and in memory."""
        if not sdk_session_id:
            return
        if session is not None:
            if session.session_data is None:
                session.session_data = {}
            session.session_data[self._SESSION_KEY] = sdk_session_id
        if session_id:
            self._sdk_session_ids[session_id] = sdk_session_id

    def _forget_sdk_session(self, session: Any, session_id: Optional[str]) -> None:
        if session is not None and session.session_data:
            session.session_data.pop(self._SESSION_KEY, None)
        if session_id:
            self._sdk_session_ids.pop(session_id, None)

    async def _aquery(
        self, input: Any, history: Optional[List[Dict[str, Any]]], *, streaming: bool, **kwargs: Any
    ) -> AsyncIterator[Any]:
        """Run a client against the SDK session tied to this Agno session, recording its id.

        Without transcript storage on the db, the SDK transcript lives on local disk under the
        agent's cwd, so a stored id may not be resumable (another host, changed cwd, deleted
        transcript). If the SDK reports the session as missing before any message arrives, start
        a fresh SDK session seeded with the Agno history; other failures keep the stored id.
        """
        sdk = _sdk()
        session = kwargs.get("session")
        session_id = kwargs.get("session_id")
        resume = self._get_sdk_session_id(session, session_id)
        store = self._transcript_store(session.session_id) if session is not None else None

        while True:
            options = self._build_options(streaming=streaming, resume=resume, session_store=store)
            prompt = self._build_prompt(input, history, resumed=resume is not None)
            received = False
            assistant_error: Optional[str] = None
            run_id = kwargs.get("run_id") or str(uuid4())
            client = sdk.ClaudeSDKClient(options=options)
            try:
                await client.connect()
                await araise_if_cancelled(run_id)
                await client.query(prompt)
                self._set_run_handle(run_id, client)
                async for message in client.receive_response():
                    if isinstance(message, sdk.AssistantMessage) and getattr(message, "error", None):
                        assistant_error = message.error
                    if isinstance(message, sdk.ResultMessage):
                        self._check_result_message(sdk, message, assistant_error)
                    if not isinstance(message, sdk.SystemMessage):
                        received = True
                    if isinstance(message, sdk.SystemMessage) and getattr(message, "subtype", None) == "init":
                        data = getattr(message, "data", {}) or {}
                        self._remember_sdk_session(session, session_id, data.get("session_id"))
                    elif isinstance(message, sdk.ResultMessage):
                        self._remember_sdk_session(session, session_id, getattr(message, "session_id", None))
                    yield message
                return
            except Exception as e:
                await araise_if_cancelled(run_id)
                if resume is None or received or not self._is_missing_session(sdk, e):
                    raise
                log_warning(
                    f"Claude SDK: could not resume session {resume} for session {session_id}: {e}. Starting a new one."
                )
                self._forget_sdk_session(session, session_id)
                resume = None
            finally:
                self._clear_run_handle(run_id)
                await client.disconnect()

    async def _ainterrupt_run(self, handle: Any) -> None:
        await handle.interrupt()

    @staticmethod
    def _is_missing_session(sdk: Any, error: Exception) -> bool:
        """True when the resume target has no transcript, as opposed to a failed run such as an API error."""
        reported = [error, getattr(error, "result", None), *(getattr(error, "errors", None) or [])]
        if any("No conversation found" in str(part) for part in reported if part):
            return True
        # SDKs without ResultError report a missing transcript only as a bare exit-code ProcessError.
        result_error = getattr(sdk, "ResultError", None)
        return isinstance(error, sdk.ProcessError) and not (
            result_error is not None and isinstance(error, result_error)
        )

    @staticmethod
    def _mirror_warning(message: Any) -> Optional[Dict[str, Any]]:
        if getattr(message, "subtype", None) != "mirror_error":
            return None
        warning = {
            "type": "transcript_persistence_failed",
            "message": "The response completed, but part of its transcript could not be persisted. "
            "Resuming on another replica may lose context.",
            "error": str(getattr(message, "error", "") or (getattr(message, "data", {}) or {}).get("error", "")),
        }
        log_warning(warning["message"])
        return warning

    def _is_retryable_error(self, error: Exception) -> bool:
        if not super()._is_retryable_error(error):
            return False
        # Read by attribute so the SDK's own ResultError classifies the same way.
        if getattr(error, "subtype", None) in _LIMIT_SUBTYPES:
            return False
        if getattr(error, "api_error_status", None) in ModelProviderError.NON_RETRYABLE_STATUS_CODES:
            return False
        if getattr(error, "assistant_error", None) in _PERMANENT_ASSISTANT_ERRORS:
            return False
        cli_not_found = getattr(_sdk(), "CLINotFoundError", None)
        return cli_not_found is None or not isinstance(error, cli_not_found)

    @staticmethod
    def _check_result_message(sdk: Any, message: Any, assistant_error: Optional[str] = None) -> None:
        """Raise if the SDK reported an error result so the base class can surface it."""
        if not isinstance(message, sdk.ResultMessage):
            return
        is_error = bool(getattr(message, "is_error", False))
        subtype = getattr(message, "subtype", None)
        if is_error or (subtype and subtype != "success"):
            # `message.result` carries the human-readable error text in the
            # invalid-model case where subtype="success" but is_error=True.
            detail = (
                getattr(message, "errors", None)
                or getattr(message, "result", None)
                or getattr(message, "stop_reason", None)
            )
            raise ClaudeResultError(
                f"Claude SDK error (is_error={is_error}, subtype={subtype}): {detail}",
                subtype=subtype,
                errors=getattr(message, "errors", None),
                api_error_status=getattr(message, "api_error_status", None),
                assistant_error=assistant_error,
            )

    async def _arun_adapter(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> ExternalRunResult:
        """Non-streaming: collect all messages and return final content."""
        sdk = _sdk()

        warnings: List[Dict[str, Any]] = []
        assistant_text = ""
        final_result = ""
        tools: Dict[str, ToolExecution] = {}

        async for message in self._aquery(input, history, streaming=False, **kwargs):
            warning = self._mirror_warning(message)
            if warning is not None:
                warnings.append(warning)
            if isinstance(message, sdk.AssistantMessage):
                # Accumulate every text block; multiple blocks per message are valid
                for block in message.content:
                    if isinstance(block, sdk.TextBlock):
                        assistant_text += block.text
                    elif isinstance(block, sdk.ToolUseBlock):
                        tools[block.id] = ToolExecution(
                            tool_call_id=block.id, tool_name=block.name, tool_args=block.input
                        )

            elif isinstance(message, sdk.UserMessage) and isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, sdk.ToolResultBlock):
                        tool = tools.setdefault(block.tool_use_id, ToolExecution(tool_call_id=block.tool_use_id))
                        result = block.content
                        tool.result = (
                            " ".join(getattr(item, "text", str(item)) for item in result)
                            if isinstance(result, list)
                            else str(result or "")
                        )
                        tool.tool_call_error = bool(getattr(block, "is_error", False))

            elif isinstance(message, sdk.ResultMessage):
                if hasattr(message, "result") and message.result:
                    final_result = str(message.result)

        # Prefer ResultMessage.result, fall back to accumulated assistant text
        return ExternalRunResult(final_result or assistant_text, list(tools.values()) or None, warnings or None)

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming: yield token-level events using include_partial_messages.

        With include_partial_messages=True, the SDK yields StreamEvent objects
        containing raw Anthropic API events (content_block_delta, etc.) alongside
        the normal complete messages. We use StreamEvent for token-level text
        streaming and tool call tracking, while still handling complete messages
        for tool results and session management.
        """
        sdk = _sdk()

        run_id = kwargs.get("run_id", str(uuid4()))

        # Track whether we got any StreamEvents (token-level streaming)
        got_stream_events = False
        # Track tool call IDs already emitted via AssistantMessage to avoid duplicates
        emitted_tool_ids: set = set()
        # Map tool_use_id -> (tool_name, tool_args) for carrying forward to ToolCallCompleted
        tool_info_map: Dict[str, Dict[str, Any]] = {}

        async for message in self._aquery(input, history, streaming=True, **kwargs):
            warning = self._mirror_warning(message)
            if warning is not None:
                yield ExternalRunWarningEvent(run_id=run_id, agent_id=self.get_id(), warning=warning)
            if isinstance(message, sdk.StreamEvent):
                got_stream_events = True
                event = message.event
                event_type = event.get("type", "")

                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    delta_type = delta.get("type", "")

                    if delta_type == "text_delta":
                        # Token-level text streaming
                        text = delta.get("text", "")
                        if text:
                            yield RunContentEvent(
                                run_id=run_id,
                                agent_id=self.get_id(),
                                agent_name=self.name or "",
                                content=text,
                            )

            elif isinstance(message, sdk.AssistantMessage):
                # Always extract tool calls from complete AssistantMessage
                # (has full name + args). For text, only use if no StreamEvents.
                for block in message.content:
                    if isinstance(block, sdk.TextBlock):
                        if not got_stream_events and block.text:
                            yield RunContentEvent(
                                run_id=run_id,
                                agent_id=self.get_id(),
                                agent_name=self.name or "",
                                content=block.text,
                            )
                    elif isinstance(block, sdk.ToolUseBlock):
                        tool_name = getattr(block, "name", "unknown")
                        tool_input = getattr(block, "input", {})
                        tool_id = getattr(block, "id", str(uuid4()))
                        if tool_id not in emitted_tool_ids:
                            emitted_tool_ids.add(tool_id)
                            tool_args = tool_input if isinstance(tool_input, dict) else {"input": tool_input}
                            tool_info_map[tool_id] = {"name": tool_name, "args": tool_args}
                            yield ToolCallStartedEvent(
                                run_id=run_id,
                                agent_id=self.get_id(),
                                agent_name=self.name or "",
                                tool=ToolExecution(
                                    tool_call_id=tool_id,
                                    tool_name=tool_name,
                                    tool_args=tool_args,
                                ),
                            )

            elif isinstance(message, sdk.UserMessage):
                # Tool results arrive as ToolResultBlock inside UserMessage
                content = message.content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, sdk.ToolResultBlock):
                            tool_use_id = getattr(block, "tool_use_id", str(uuid4()))
                            result_content = getattr(block, "content", "")
                            if isinstance(result_content, list):
                                result_str = " ".join(getattr(item, "text", str(item)) for item in result_content)
                            else:
                                result_str = str(result_content) if result_content else ""
                            # Look up tool name from the corresponding ToolCallStarted
                            info = tool_info_map.get(tool_use_id, {})
                            yield ToolCallCompletedEvent(
                                run_id=run_id,
                                agent_id=self.get_id(),
                                agent_name=self.name or "",
                                tool=ToolExecution(
                                    tool_call_id=tool_use_id,
                                    tool_name=info.get("name", ""),
                                    tool_args=info.get("args"),
                                    result=result_str,
                                ),
                            )
