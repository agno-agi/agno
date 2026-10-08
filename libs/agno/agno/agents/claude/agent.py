from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agno.agents.base import BaseExternalAgent, ExternalRunResult, ExternalRunWarningEvent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.utils.log import log_debug, log_warning


def _sdk() -> Any:
    """Lazy-import the claude_agent_sdk module."""
    try:
        import claude_agent_sdk  # type: ignore

        return claude_agent_sdk
    except ImportError as e:
        raise ImportError("claude-agent-sdk is required: pip install claude-agent-sdk") from e


@dataclass
class ClaudeAgent(BaseExternalAgent):
    """Adapter for the Claude Agent SDK (claude-agent-sdk).

    Wraps the Claude Agent SDK's query() function so it can be used with AgentOS
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
    mcp_servers: Optional[Dict[str, Any]] = None
    options_kwargs: Dict[str, Any] = field(default_factory=dict)
    framework: str = "claude-agent-sdk"

    # Key under which the SDK session id is stored in the Agno session's session_data.
    _SESSION_KEY = "claude_sdk_session_id"

    # Fallback Agno session_id -> SDK session id map, used when no db is configured.
    _sdk_session_ids: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.project_key is None:
            self.project_key = self.get_id()

    def _build_options(self, *, streaming: bool = False, resume: Optional[str] = None) -> Any:
        """Build ClaudeAgentOptions from agent config."""
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
        if self.db is not None:
            base = AsyncBaseDb if isinstance(self.db, AsyncBaseDb) else BaseDb
            if type(self.db).append_transcript_entries is not base.append_transcript_entries:
                from agno.agents.claude.session_store import AgnoSessionStore

                opts["session_store"] = AgnoSessionStore(self.db, self.project_key or self.get_id())
            elif not self._store_warning_logged:
                log_debug("Claude SDK transcript storage is unavailable on this database; resume uses local files.")
                self._store_warning_logged = True
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
        """Run sdk.query() against the SDK session tied to this Agno session, recording its id.

        The SDK transcript lives on local disk under the agent's cwd, so a stored id may not
        be resumable (another host, changed cwd, deleted transcript). If the resume fails
        before any message arrives, start a fresh SDK session seeded with the Agno history.
        """
        sdk = _sdk()
        session = kwargs.get("session")
        session_id = kwargs.get("session_id")
        resume = self._get_sdk_session_id(session, session_id)

        while True:
            options = self._build_options(streaming=streaming, resume=resume)
            prompt = self._build_prompt(input, history, resumed=resume is not None)
            received = False
            try:
                async for message in sdk.query(prompt=prompt, options=options):
                    if isinstance(message, sdk.ResultMessage):
                        self._check_result_message(sdk, message)
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
                if resume is None or received:
                    raise
                log_warning(
                    f"Claude SDK: could not resume session {resume} for session {session_id}: {e}. Starting a new one."
                )
                self._forget_sdk_session(session, session_id)
                resume = None

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

    @staticmethod
    def _check_result_message(sdk: Any, message: Any) -> None:
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
            raise RuntimeError(f"Claude SDK error (is_error={is_error}, subtype={subtype}): {detail}")

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
                self._check_result_message(sdk, message)
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

            elif isinstance(message, sdk.ResultMessage):
                self._check_result_message(sdk, message)
