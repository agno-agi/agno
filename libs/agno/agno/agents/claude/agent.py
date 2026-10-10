import warnings
from dataclasses import field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, ClassVar, Dict, List, Literal, Optional, Union
from uuid import uuid4

from agno.agents._config import agent_dataclass
from agno.agents._media import accept_media, cleanup_media, media_prompt_block, stage_media, stage_prior_media
from agno.agents.base import BaseExternalAgent, ExternalRunResult, ExternalRunWarningEvent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.cancel import araise_if_cancelled
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions
    from claude_agent_sdk.types import (
        McpServerConfig,
        PermissionMode,
        SdkPluginConfig,
        SettingSource,
        SystemPromptCustom,
        SystemPromptFile,
        SystemPromptPreset,
        ToolsPreset,
    )


def _copy_config(value: Any) -> Any:
    """Copy configuration containers while preserving SDK callbacks and service objects."""
    if isinstance(value, dict):
        return {key: _copy_config(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_config(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_config(item) for item in value)
    return value


def _sdk() -> Any:
    """Lazy-import the claude_agent_sdk module."""
    try:
        import claude_agent_sdk  # type: ignore

        return claude_agent_sdk
    except ImportError as e:
        raise ImportError("claude-agent-sdk is required: pip install claude-agent-sdk") from e


@agent_dataclass
class ClaudeAgent(BaseExternalAgent):
    """Adapter for the Claude Agent SDK (claude-agent-sdk).

    Wraps a per-run Claude Agent SDK client so it can be used with AgentOS
    endpoints or standalone via .run() / .print_response().

    The Claude Agent SDK runs Claude Code as a subprocess. Tool execution is handled
    internally by the SDK. tools selects built-in tools; allowed_tools pre-approves calls.

    Args:
        name: Display name for this agent.
        id: Unique identifier (auto-generated from name if not set).
        system_prompt: Optional system prompt for the agent.
        model: Model to use. Defaults to the SDK default unless set in options.
        tools: Built-in tool names or the Claude Code tool preset. An empty list disables built-in tools.
        allowed_tools: Tool calls to auto-approve; this does not limit the available tool set.
        disallowed_tools: List of tools to block.
        permission_mode: SDK permission mode, such as "default", "acceptEdits" or "dontAsk".
        max_turns: Maximum number of turns.
        max_budget_usd: Maximum cost budget in USD.
        cwd: Working directory for the agent.
        keep_uploads: Keep files attached to a run under cwd/.agno/uploads/<run_id>/ after the run.
        mcp_servers: MCP server configurations for custom tools.
        setting_sources: Filesystem settings to load; [] disables user/project/local settings.
        strict_mcp_config: Use only explicitly configured MCP servers when True.
        skills: Available skill names, or "all". Include "Skill" when explicitly selecting tools.
        plugins: Native SDK plugin configurations.
        options: Native ClaudeAgentOptions for advanced configuration. Non-None constructor
            fields override these options, including empty collections and False. Agno owns
            native session selection and token streaming; configure them through run/arun.
            Configuration containers are copied per run; callbacks and services retain identity.
        options_kwargs: Deprecated dictionary alternative to options. Cannot be combined with
            options. Retains legacy precedence over constructor fields; migrate to options
            for explicit constructor precedence. Conflicting runtime settings are rejected.

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

    # Model and instructions
    model: Optional[str] = None
    system_prompt: Optional[Union[str, "SystemPromptPreset", "SystemPromptCustom", "SystemPromptFile"]] = None
    # Workspace and settings
    cwd: Optional[Union[str, Path]] = None
    # Keep attachments staged under cwd/.agno/uploads/<run_id>/ after the run instead of deleting them.
    keep_uploads: bool = False
    project_key: Optional[str] = None
    setting_sources: Optional[List["SettingSource"]] = None
    # Tools and permissions
    tools: Optional[Union[List[str], "ToolsPreset"]] = None
    allowed_tools: Optional[List[str]] = None
    disallowed_tools: Optional[List[str]] = None
    permission_mode: Optional["PermissionMode"] = None
    mcp_servers: Optional[Union[Dict[str, "McpServerConfig"], str, Path]] = None
    strict_mcp_config: Optional[bool] = None
    # Extensions
    skills: Optional[Union[List[str], Literal["all"]]] = None
    plugins: Optional[List["SdkPluginConfig"]] = None
    # Execution limits
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    # Advanced native configuration
    options: Optional["ClaudeAgentOptions"] = None
    options_kwargs: Dict[str, Any] = field(default_factory=dict)

    _sdk_name: ClassVar[str] = "claude-agent-sdk"
    # Key under which the SDK session id is stored in the Agno session.
    _SESSION_KEY = "claude_sdk_session_id"
    _store_warning_logged: bool = field(default=False, init=False, repr=False)
    _warn_unstable_project_key: bool = field(default=False, init=False, repr=False)
    _store_skipped_logged: bool = field(default=False, init=False, repr=False)

    # Fallback Agno session_id -> SDK session id map, used when no db is configured.
    _sdk_session_ids: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.options is not None and self.options_kwargs:
            raise ValueError("Use options or options_kwargs, not both.")
        if self.options is not None and not isinstance(self.options, _sdk().ClaudeAgentOptions):
            raise TypeError("options must be a claude_agent_sdk.ClaudeAgentOptions instance.")
        if self.options_kwargs:
            warnings.warn(
                "options_kwargs is deprecated; use options=ClaudeAgentOptions(...) or named parameters. "
                "Named parameters override options; options_kwargs retains legacy precedence.",
                DeprecationWarning,
                stacklevel=2,
            )
        self._validate_runtime_options(self._option_values())
        # Without id or name, get_id() is random per process, so the default key cannot be shared across replicas.
        self._warn_unstable_project_key = self.project_key is None and self.id is None and self.name is None
        super().__post_init__()
        if self.project_key is None:
            self.project_key = self.get_id()

    def _option_values(self) -> Dict[str, Any]:
        if self.options is not None:
            return {item.name: getattr(self.options, item.name) for item in fields(self.options) if item.init}
        return dict(self.options_kwargs)

    @staticmethod
    def _validate_runtime_options(opts: Dict[str, Any]) -> None:
        for name in ("resume", "session_id", "continue_conversation", "fork_session"):
            if opts.get(name):
                raise ValueError(
                    f"ClaudeAgent manages {name}; use run/arun(session_id=...) for conversation continuity."
                )
        # Raw CLI arguments must not bypass the same session/streaming contract.
        reserved_flags = {"resume", "session-id", "continue", "fork-session", "include-partial-messages"}
        for flag in opts.get("extra_args", {}):
            if flag.lstrip("-") in reserved_flags:
                raise ValueError(f"ClaudeAgent manages extra_args[{flag!r}]; use run/arun configuration instead.")

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
        opts = self._option_values()
        if opts.get("session_store") is not None or "session_store" in self.options_kwargs:
            if not self._store_skipped_logged:
                log_debug("ClaudeAgent uses the configured session_store; Agno transcript storage is off.")
                self._store_skipped_logged = True
            return None
        if opts.get("enable_file_checkpointing"):
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

        opts = self._option_values()
        self._validate_runtime_options(opts)
        for name in (
            "system_prompt",
            "model",
            "tools",
            "allowed_tools",
            "disallowed_tools",
            "permission_mode",
            "max_turns",
            "max_budget_usd",
            "cwd",
            "mcp_servers",
            "setting_sources",
            "strict_mcp_config",
            "skills",
            "plugins",
        ):
            value = getattr(self, name)
            if value is not None:
                opts[name] = value

        # Keep the old dictionary's precedence during migration, without allowing it to
        # override the native session selected by Agno or disable requested streaming.
        opts.update(self.options_kwargs)
        partial = opts.get("include_partial_messages", False)
        if (partial and not streaming) or ("include_partial_messages" in self.options_kwargs and partial != streaming):
            raise ValueError("ClaudeAgent manages include_partial_messages; use run/arun(stream=...).")
        opts["include_partial_messages"] = streaming
        opts["resume"] = resume
        opts = _copy_config(opts)
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

    def _media_kwargs(self, **media: Any) -> Dict[str, Any]:
        """Images and files are written under cwd/.agno/uploads/<run_id>/ and named in the prompt,
        so Claude Code opens them with its Read tool. Audio and video are rejected."""
        return accept_media(media)

    async def _aquery(
        self, input: Any, history: Optional[List[Dict[str, Any]]], *, streaming: bool, **kwargs: Any
    ) -> AsyncIterator[Any]:
        """Stage attachments for the run, query, then remove them unless keep_uploads is set."""
        media = kwargs.pop("media", None)
        run_id = kwargs.get("run_id") or str(uuid4())
        kwargs["run_id"] = run_id
        staged = stage_media(self.cwd, run_id, media) if media else []
        if staged and input is not None:
            input = f"{input}{media_prompt_block(staged)}"
        # Earlier turns' attachments come back under their original paths, so Claude can
        # open again a file it was given before, on whichever replica runs this turn.
        restaged, moved_note = stage_prior_media(self.cwd, kwargs.get("session"), exclude_run_id=run_id)
        if moved_note and input is not None:
            input = f"{input}{moved_note}"
        try:
            async for message in self._aquery_sdk(input, history, streaming=streaming, **kwargs):
                yield message
        finally:
            if not self.keep_uploads:
                for staged_run_id in ([run_id] if staged else []) + restaged:
                    cleanup_media(self.cwd, staged_run_id)

    async def _aquery_sdk(
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
            run_id = kwargs.get("run_id") or str(uuid4())
            client = sdk.ClaudeSDKClient(options=options)
            try:
                await client.connect()
                await araise_if_cancelled(run_id)
                await client.query(prompt)
                self._set_run_handle(run_id, client)
                async for message in client.receive_response():
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
