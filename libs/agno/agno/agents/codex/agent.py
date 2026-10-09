import json
import warnings
from copy import deepcopy
from dataclasses import dataclass, field, replace
from importlib import import_module
from typing import TYPE_CHECKING, Any, AsyncIterator, ClassVar, Dict, Iterator, List, Optional, Set, Tuple
from uuid import uuid4

from agno.agents._config import agent_dataclass
from agno.agents.base import BaseExternalAgent, ExternalRunResult
from agno.agents.codex.options import ThreadOptions, TurnOptions
from agno.exceptions import RunCancelledException
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from openai_codex import CodexConfig


def _sdk() -> Any:
    """Lazy-import the openai_codex module."""
    try:
        import openai_codex  # type: ignore

        return openai_codex
    except ImportError as e:
        raise ImportError("openai-codex is required: pip install openai-codex") from e


# Accept the CLI spellings as well as the SDK enum names for the sandbox setting.
_SANDBOX_ALIASES: Dict[str, str] = {
    "read_only": "read-only",
    "readonly": "read-only",
    "workspace_write": "workspace-write",
    "full_access": "full-access",
    "danger-full-access": "full-access",
    "danger_full_access": "full-access",
}

# thread_start-only options that thread_resume does not accept.
_START_ONLY_KEYS = {"ephemeral", "service_name", "session_start_source", "thread_source"}


def _item_root(item: Any) -> Any:
    """Unwrap a pydantic RootModel (ThreadItem) to the concrete item."""
    return getattr(item, "root", item)


def _coerce_args(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"input": parsed}
        except json.JSONDecodeError:
            return {"input": raw}
    return {"input": raw}


def _text_from_content(content: Any) -> Optional[str]:
    """Join the text parts of an MCP-style content list."""
    if not isinstance(content, list):
        return None
    texts: List[str] = []
    for part in content:
        text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
        if text:
            texts.append(str(text))
    return "\n".join(texts) if texts else None


@dataclass
class _StreamState:
    """Bookkeeping for one streamed turn."""

    text_item_ids: Set[str] = field(default_factory=set)
    current_text_item: Optional[str] = None
    emitted_text: bool = False
    tool_info: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    error: Optional[str] = None


@agent_dataclass
class CodexAgent(BaseExternalAgent):
    """Adapter for OpenAI Codex via the official Codex Python SDK (openai-codex).

    Wraps the Codex SDK so a Codex agent can be used with AgentOS endpoints or
    standalone via .run() / .print_response().

    The SDK bundles the Codex CLI and runs it locally as an app-server
    subprocess. Codex runs the full agent loop itself (shell commands, file
    edits, web search, MCP tools); this adapter translates its notifications
    into Agno run events and maps each Agno session to one Codex thread.

    Args:
        name: Display name for this agent.
        id: Unique identifier (auto-generated from name if not set).
        model: Codex model id (e.g. "gpt-5.6-luna"). Defaults to the Codex default.
        instructions: Developer instructions appended to the Codex system prompt.
        base_instructions: Replaces the Codex built-in system prompt entirely.
        sandbox: "read-only", "workspace-write" or "full-access". Defaults to the Codex default.
        approval_mode: "auto_review" or "deny_all" for escalated permission requests.
        reasoning_effort: "minimal", "low", "medium", "high" or "xhigh".
        cwd: Working directory for the agent.
        ephemeral: Do not persist Codex thread files. Ephemeral threads cannot be resumed.
        output_schema: JSON Schema constraining the final answer. Content is the JSON string.
        model_provider: Native Codex model provider name.
        service_tier: Service tier used for threads and turns.
        mcp_servers: Native MCP server configuration, replacing config["mcp_servers"].
        config: Native thread config overrides; unrelated to client process configuration.
        client_options: Native CodexConfig for the app-server process.
        thread_options: Typed native thread settings. Named non-None settings take precedence.
        turn_options: Typed native turn settings. Named non-None settings take precedence.
        codex_bin: Path to a specific Codex executable. Defaults to the bundled one.
        env: Environment variables for the Codex process.
        thread_kwargs: Deprecated alias for thread_options.
        turn_kwargs: Deprecated alias for turn_options.

    Input must be a string. Native SDK input objects (including images, skills and
    external tool messages) are not supported by Agno's text history adapter.

    Example:
        from agno.agents.codex import CodexAgent

        agent = CodexAgent(
            name="Codex Coder",
            sandbox="workspace-write",
            cwd=".",
        )

        # Standalone usage
        agent.print_response("Summarize this repository", stream=True)

        # Or deploy with AgentOS
        from agno.os import AgentOS
        AgentOS(agents=[agent])
    """

    # Model and instructions
    model: Optional[str] = None
    instructions: Optional[str] = None
    base_instructions: Optional[str] = None
    model_provider: Optional[str] = None
    reasoning_effort: Optional[str] = None
    service_tier: Optional[str] = None
    output_schema: Optional[Dict[str, Any]] = None
    # Native tools
    mcp_servers: Optional[Dict[str, Any]] = None
    # Workspace and settings
    cwd: Optional[str] = None
    sandbox: Optional[str] = None
    approval_mode: Optional[str] = None
    ephemeral: Optional[bool] = None
    # Native runtime configuration
    client_options: Optional["CodexConfig"] = None
    thread_options: Optional[ThreadOptions] = None
    turn_options: Optional[TurnOptions] = None
    config: Optional[Dict[str, Any]] = None
    codex_bin: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    thread_kwargs: Dict[str, Any] = field(default_factory=dict)
    turn_kwargs: Dict[str, Any] = field(default_factory=dict)

    _sdk_name: ClassVar[str] = "codex"
    # Key under which the Codex thread id is stored in the Agno session.
    _THREAD_KEY = "codex_thread_id"

    # Fallback Agno session_id -> Codex thread id map, used when no db is configured.
    _thread_ids: Dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self._validate_options()
        for name in ("thread", "turn"):
            if getattr(self, f"{name}_kwargs"):
                warnings.warn(
                    f"{name}_kwargs is deprecated; use {name}_options. Named settings take precedence.",
                    DeprecationWarning,
                    stacklevel=3,
                )

    def _validate_options(self) -> None:
        for name, schema in (("thread", ThreadOptions), ("turn", TurnOptions)):
            options = getattr(self, f"{name}_options")
            legacy = getattr(self, f"{name}_kwargs")
            if options is not None and legacy:
                raise ValueError(f"Use {name}_options or {name}_kwargs, not both")
            values = options if options is not None else legacy
            unknown = set(values) - set(schema.__annotations__)
            if unknown:
                raise ValueError(f"Unknown {name} options: {', '.join(sorted(unknown))}")

    @staticmethod
    def _validate_input(input: Any) -> None:
        if not isinstance(input, str):
            raise TypeError(
                "CodexAgent input must be a string. Native Codex input objects are not supported; "
                "use the native SDK for images, skills or external tool messages."
            )

    def login_api_key(self, api_key: str) -> None:
        """Store an API key in the Codex CLI auth so future runs are authenticated."""
        sdk = _sdk()
        with sdk.Codex(self._codex_config(sdk)) as codex:
            codex.login_api_key(api_key)

    async def alogin_api_key(self, api_key: str) -> None:
        """Async version of login_api_key."""
        sdk = _sdk()
        async with sdk.AsyncCodex(self._codex_config(sdk)) as codex:
            await codex.login_api_key(api_key)

    # ---------------------------------------------------------------------------
    # SDK option builders
    # ---------------------------------------------------------------------------

    def _codex_config(self, sdk: Any) -> Any:
        if self.client_options is not None and not isinstance(self.client_options, sdk.CodexConfig):
            raise TypeError("client_options must be an openai_codex.CodexConfig")
        config = replace(self.client_options) if self.client_options is not None else sdk.CodexConfig()
        if self.codex_bin is not None:
            config.codex_bin = self.codex_bin
        if self.env is not None:
            config.env = dict(self.env)
        elif config.env is not None:
            config.env = dict(config.env)
        return config

    def _new_client(self) -> Any:
        """Create an AsyncCodex client. One app-server process per run keeps the
        client bound to the current event loop."""
        sdk = _sdk()
        return sdk.AsyncCodex(self._codex_config(sdk))

    @staticmethod
    def _to_sandbox(sdk: Any, value: str) -> Any:
        normalized = _SANDBOX_ALIASES.get(value.lower(), value.lower())
        try:
            return sdk.Sandbox(normalized)
        except ValueError as e:
            raise ValueError(
                f"Unknown sandbox {value!r}. Expected one of: read-only, workspace-write, full-access"
            ) from e

    @staticmethod
    def _to_approval_mode(sdk: Any, value: str) -> Any:
        normalized = value.lower().replace("-", "_")
        try:
            return sdk.ApprovalMode(normalized)
        except ValueError as e:
            raise ValueError(f"Unknown approval_mode {value!r}. Expected one of: auto_review, deny_all") from e

    @staticmethod
    def _to_reasoning_effort(sdk: Any, value: str) -> Any:
        types_module = getattr(sdk, "types", None)
        if types_module is None:
            types_module = import_module(f"{sdk.__name__}.types")
        return types_module.ReasoningEffort(value.lower())

    def _resolved_thread_options(self) -> Dict[str, Any]:
        self._validate_options()
        options = dict(self.thread_options if self.thread_options is not None else self.thread_kwargs)
        for key, value in {
            "model": self.model,
            "model_provider": self.model_provider,
            "developer_instructions": self.instructions,
            "base_instructions": self.base_instructions,
            "sandbox": self.sandbox,
            "approval_mode": self.approval_mode,
            "cwd": self.cwd,
            "config": self.config,
            "ephemeral": self.ephemeral,
            "service_tier": self.service_tier,
        }.items():
            if value is not None:
                options[key] = value
        if options.get("config") is not None:
            options["config"] = deepcopy(options["config"])
        if self.mcp_servers is not None:
            config = options.setdefault("config", {})
            if config is None:
                config = options["config"] = {}
            config["mcp_servers"] = deepcopy(self.mcp_servers)
        return options

    def _thread_kwargs(self, sdk: Any, *, resume: bool) -> Dict[str, Any]:
        """Build native options from the settings used for Agno session bookkeeping."""
        excluded = _START_ONLY_KEYS if resume else {"include_turns"}
        options = {k: v for k, v in self._resolved_thread_options().items() if v is not None and k not in excluded}
        self._normalize_permissions(sdk, options)
        return options

    def _normalize_permissions(self, sdk: Any, options: Dict[str, Any]) -> None:
        if "sandbox" in options:
            options["sandbox"] = self._to_sandbox(sdk, options["sandbox"])
        if "approval_mode" in options:
            options["approval_mode"] = self._to_approval_mode(sdk, options["approval_mode"])

    def _turn_kwargs(self, sdk: Any) -> Dict[str, Any]:
        self._validate_options()
        options = dict(self.turn_options if self.turn_options is not None else self.turn_kwargs)
        for key, value in {
            "model": self.model,
            "cwd": self.cwd,
            "sandbox": self.sandbox,
            "approval_mode": self.approval_mode,
            "service_tier": self.service_tier,
            "effort": self.reasoning_effort,
            "output_schema": self.output_schema,
        }.items():
            if value is not None:
                options[key] = value
        options = {k: v for k, v in options.items() if v is not None}
        self._normalize_permissions(sdk, options)
        if "effort" in options:
            options["effort"] = self._to_reasoning_effort(sdk, options["effort"])
        if "output_schema" in options:
            options["output_schema"] = deepcopy(options["output_schema"])
        return options

    # ---------------------------------------------------------------------------
    # Session <-> Codex thread mapping
    # ---------------------------------------------------------------------------

    def _get_thread_id(self, session: Any, session_id: Optional[str]) -> Optional[str]:
        if session is not None and session.session_data:
            thread_id = session.session_data.get(self._THREAD_KEY)
            if thread_id:
                return str(thread_id)
        if session_id:
            return self._thread_ids.get(session_id)
        return None

    def _remember_thread(self, session: Any, session_id: Optional[str], thread_id: Optional[str]) -> None:
        """Stash the Codex thread id on the session (persisted by the base class)
        and in memory. Ephemeral threads are never resumable, so skip them."""
        if not thread_id or self._resolved_thread_options().get("ephemeral"):
            return
        if session is not None:
            if session.session_data is None:
                session.session_data = {}
            session.session_data[self._THREAD_KEY] = thread_id
        if session_id:
            self._thread_ids[session_id] = thread_id

    def _forget_thread(self, session: Any, session_id: Optional[str]) -> None:
        if session is not None and session.session_data:
            session.session_data.pop(self._THREAD_KEY, None)
        if session_id:
            self._thread_ids.pop(session_id, None)

    @staticmethod
    def _is_missing_thread(error: Exception) -> bool:
        """True when the app-server reports the resume target as gone, not a failed call.

        The app-server answers a resume of an unknown thread with a JSON-RPC invalid
        request error whose message reads "no rollout found for thread id ..."; a
        malformed id reads "invalid session id ...".
        """
        text = str(getattr(error, "message", None) or error)
        return "no rollout found" in text or "invalid session id" in text

    async def _open_thread(self, codex: Any, sdk: Any, session: Any, session_id: Optional[str]) -> Tuple[Any, bool]:
        """Resume the thread tied to this session, or start a new one.

        Returns (thread, resumed). Only a resume the app-server rejects because the
        thread no longer exists (rollout files removed, ephemeral thread, bad id)
        falls back to a fresh thread. Any other failure (busy server, closed
        transport, bad cwd) is raised as-is and keeps the stored thread id, so a
        transient problem cannot unlink the session from its conversation.
        """
        if self._resolved_thread_options().get("ephemeral"):
            self._forget_thread(session, session_id)
        thread_id = self._get_thread_id(session, session_id)
        if thread_id:
            try:
                thread = await codex.thread_resume(thread_id, **self._thread_kwargs(sdk, resume=True))
                log_debug(f"Codex: resumed thread {thread_id} for session {session_id}")
                return thread, True
            except Exception as e:
                if not self._is_missing_thread(e):
                    raise
                log_warning(
                    f"Codex: could not resume thread {thread_id} for session {session_id}: {e}. Starting a new one."
                )
                self._forget_thread(session, session_id)

        thread = await codex.thread_start(**self._thread_kwargs(sdk, resume=False))
        log_debug(f"Codex: started thread {thread.id} for session {session_id}")
        self._remember_thread(session, session_id, getattr(thread, "id", None))
        return thread, False

    # ---------------------------------------------------------------------------
    # Adapter hooks
    # ---------------------------------------------------------------------------

    async def _arun_adapter(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> ExternalRunResult:
        """Non-streaming: run one turn and return the final answer."""
        self._validate_input(input)
        sdk = _sdk()
        self._thread_kwargs(sdk, resume=False)
        turn_options = self._turn_kwargs(sdk)
        session = kwargs.get("session")
        session_id = kwargs.get("session_id")

        async with self._new_client() as codex:
            thread, resumed = await self._open_thread(codex, sdk, session, session_id)
            prompt = self._build_prompt(input, history, resumed)
            run_id = kwargs.get("run_id") or str(uuid4())
            handle = await thread.turn(prompt, **turn_options)
            self._set_run_handle(run_id, handle)
            try:
                result = await handle.run()
            finally:
                self._clear_run_handle(run_id)
            status = getattr(result, "status", None)
            if getattr(status, "value", status) == "interrupted":
                raise RunCancelledException(run_id)
            if getattr(status, "value", status) == "failed":
                raise RuntimeError(f"Codex turn failed: {getattr(result, 'error', None)}")

        tools = []
        for item in getattr(result, "items", None) or []:
            item = _item_root(item)
            tool = self._tool_from_item(item)
            if tool is not None:
                tool.result = self._tool_result_from_item(item)
                tools.append(tool)
        return ExternalRunResult(self._final_text(result), tools or None)

    @staticmethod
    def _final_text(result: Any) -> str:
        final_response = getattr(result, "final_response", None)
        if final_response:
            return str(final_response)
        parts: List[str] = []
        for item in getattr(result, "items", None) or []:
            root = _item_root(item)
            if getattr(root, "type", None) == "agentMessage" and getattr(root, "text", None):
                parts.append(str(root.text))
        return "\n\n".join(parts)

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming: translate Codex app-server notifications into Agno events.

        Text arrives as item/agentMessage/delta notifications. Tool activity
        (shell commands, file changes, MCP calls, web search) arrives as
        item/started and item/completed notifications. turn/completed closes
        the stream and carries the failure status, if any.
        """
        self._validate_input(input)
        sdk = _sdk()
        self._thread_kwargs(sdk, resume=False)
        turn_options = self._turn_kwargs(sdk)
        run_id = kwargs.get("run_id", str(uuid4()))
        session = kwargs.get("session")
        session_id = kwargs.get("session_id")
        state = _StreamState()

        async with self._new_client() as codex:
            thread, resumed = await self._open_thread(codex, sdk, session, session_id)
            prompt = self._build_prompt(input, history, resumed)
            handle = await thread.turn(prompt, **turn_options)
            self._set_run_handle(run_id, handle)
            try:
                async for notification in handle.stream():
                    for event in self._translate_notification(notification, run_id=run_id, state=state):
                        yield event
            finally:
                self._clear_run_handle(run_id)

        if state.error:
            raise RuntimeError(f"Codex turn failed: {state.error}")

    # ---------------------------------------------------------------------------
    # Notification translation
    # ---------------------------------------------------------------------------

    async def _ainterrupt_run(self, handle: Any) -> None:
        await handle.interrupt()

    def _content_event(self, run_id: str, content: str, reasoning: Optional[str] = None) -> RunContentEvent:
        return RunContentEvent(
            run_id=run_id,
            agent_id=self.get_id(),
            agent_name=self.name or "",
            content=content,
            reasoning_content=reasoning,
        )

    def _translate_notification(
        self, notification: Any, *, run_id: str, state: _StreamState
    ) -> Iterator[RunOutputEvent]:
        method = getattr(notification, "method", "") or ""
        payload = getattr(notification, "payload", None)
        if payload is None:
            return

        if method == "item/agentMessage/delta":
            delta = getattr(payload, "delta", "") or ""
            if not delta:
                return
            item_id = getattr(payload, "item_id", None) or ""
            if item_id != state.current_text_item:
                # Separate consecutive assistant messages (commentary, then final answer)
                if state.emitted_text:
                    yield self._content_event(run_id, "\n\n")
                state.current_text_item = item_id
            state.text_item_ids.add(item_id)
            state.emitted_text = True
            yield self._content_event(run_id, str(delta))

        elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
            delta = getattr(payload, "delta", "") or ""
            if delta:
                yield self._content_event(run_id, "", reasoning=str(delta))

        elif method == "item/started":
            item = _item_root(getattr(payload, "item", None))
            if getattr(item, "type", None) == "agentMessage":
                return  # text follows as deltas
            tool = self._tool_from_item(item)
            if tool is not None:
                state.tool_info[tool.tool_call_id or ""] = {"name": tool.tool_name, "args": tool.tool_args}
                yield ToolCallStartedEvent(run_id=run_id, agent_id=self.get_id(), agent_name=self.name or "", tool=tool)

        elif method == "item/completed":
            item = _item_root(getattr(payload, "item", None))
            if getattr(item, "type", None) == "agentMessage":
                item_id = getattr(item, "id", "") or ""
                text = getattr(item, "text", "") or ""
                # Only emit the full text when no deltas were streamed for this item
                if text and item_id not in state.text_item_ids:
                    if state.emitted_text:
                        yield self._content_event(run_id, "\n\n")
                    state.emitted_text = True
                    state.current_text_item = item_id
                    yield self._content_event(run_id, str(text))
                return
            tool = self._tool_from_item(item)
            if tool is None:
                return
            if (tool.tool_call_id or "") not in state.tool_info:
                # No item/started arrived for this tool; emit it so args are visible
                state.tool_info[tool.tool_call_id or ""] = {"name": tool.tool_name, "args": tool.tool_args}
                yield ToolCallStartedEvent(
                    run_id=run_id,
                    agent_id=self.get_id(),
                    agent_name=self.name or "",
                    tool=ToolExecution(
                        tool_call_id=tool.tool_call_id, tool_name=tool.tool_name, tool_args=tool.tool_args
                    ),
                )
            tool.result = self._tool_result_from_item(item)
            yield ToolCallCompletedEvent(run_id=run_id, agent_id=self.get_id(), agent_name=self.name or "", tool=tool)

        elif method == "turn/completed":
            turn = getattr(payload, "turn", None)
            status = getattr(turn, "status", None)
            status_value = getattr(status, "value", status)
            if status_value == "failed":
                error = getattr(turn, "error", None)
                state.error = getattr(error, "message", None) or "turn failed"
            elif status_value == "interrupted":
                raise RunCancelledException(run_id)

        elif method == "error":
            error = getattr(payload, "error", None)
            message = getattr(error, "message", None) or str(error)
            if getattr(payload, "will_retry", False):
                log_debug(f"Codex: transient error, retrying: {message}")
            else:
                state.error = message

    @staticmethod
    def _tool_from_item(item: Any) -> Optional[ToolExecution]:
        """Map a Codex thread item to an Agno ToolExecution (without result)."""
        item_type = getattr(item, "type", None)
        item_id = getattr(item, "id", None) or str(uuid4())

        if item_type == "commandExecution":
            args: Dict[str, Any] = {"command": str(getattr(item, "command", "") or "")}
            cwd = getattr(item, "cwd", None)
            if cwd:
                args["cwd"] = str(cwd)
            return ToolExecution(tool_call_id=item_id, tool_name="shell", tool_args=args)

        if item_type == "mcpToolCall":
            server = getattr(item, "server", "") or ""
            tool = getattr(item, "tool", "") or ""
            return ToolExecution(
                tool_call_id=item_id,
                tool_name=f"mcp__{server}__{tool}",
                tool_args=_coerce_args(getattr(item, "arguments", None)),
            )

        if item_type == "dynamicToolCall":
            return ToolExecution(
                tool_call_id=item_id,
                tool_name=str(getattr(item, "tool", None) or "tool"),
                tool_args=_coerce_args(getattr(item, "arguments", None)),
            )

        if item_type == "fileChange":
            changes: List[Dict[str, Any]] = []
            for change in getattr(item, "changes", None) or []:
                kind = _item_root(getattr(change, "kind", None))
                kind_name = getattr(kind, "type", None) or (str(kind) if kind is not None else None)
                changes.append({"path": str(getattr(change, "path", "") or ""), "kind": kind_name})
            return ToolExecution(tool_call_id=item_id, tool_name="apply_patch", tool_args={"changes": changes})

        if item_type == "webSearch":
            return ToolExecution(
                tool_call_id=item_id,
                tool_name="web_search",
                tool_args={"query": str(getattr(item, "query", "") or "")},
            )

        return None

    @staticmethod
    def _tool_result_from_item(item: Any) -> str:
        """Render a completed Codex thread item's outcome as the tool result string."""
        item_type = getattr(item, "type", None)
        status = getattr(item, "status", None)
        status_value = getattr(status, "value", status)

        if item_type == "commandExecution":
            output = str(getattr(item, "aggregated_output", None) or "")
            exit_code = getattr(item, "exit_code", None)
            if exit_code not in (None, 0):
                output = f"{output}\n[exit code {exit_code}]".strip()
            if not output and status_value in ("failed", "declined"):
                output = f"command {status_value}"
            return output

        if item_type in ("mcpToolCall", "dynamicToolCall"):
            error = getattr(item, "error", None)
            if error is not None:
                return f"error: {getattr(error, 'message', error)}"
            result = getattr(item, "result", None)
            if result is not None:
                text = _text_from_content(getattr(result, "content", None))
                if text:
                    return text
                structured = getattr(result, "structured_content", None)
                if structured is not None:
                    return json.dumps(structured, default=str)
                return str(result)
            text = _text_from_content(getattr(item, "content_items", None))
            if text:
                return text
            return str(status_value or "completed")

        if item_type == "fileChange":
            lines: List[str] = []
            if status_value:
                lines.append(f"status: {status_value}")
            for change in getattr(item, "changes", None) or []:
                kind = _item_root(getattr(change, "kind", None))
                kind_name = getattr(kind, "type", None) or (str(kind) if kind is not None else "update")
                lines.append(f"{kind_name} {getattr(change, 'path', '')}")
                diff = getattr(change, "diff", None)
                if diff:
                    lines.append(str(diff))
            return "\n".join(lines)

        if item_type == "webSearch":
            results = getattr(item, "results", None)
            return json.dumps(results, default=str) if results else "completed"

        return str(status_value or "completed")
