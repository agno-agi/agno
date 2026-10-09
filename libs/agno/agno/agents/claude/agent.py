import copy
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Dict, Iterator, List, Literal, Optional, Tuple, Union, cast
from uuid import uuid4

from agno.agents.base import BaseExternalAgent, ExternalContinuation, ExternalRunResult, ExternalRunWarningEvent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutput,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus
from agno.run.cancel import araise_if_cancelled
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
    # Message.provider_data key holding the SDK session id and transcript uuid behind a message.
    _MESSAGE_REF_KEY = "claude_sdk"
    _CONTINUE_PROMPT = "Continue from where you left off."

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
        # Echo the prompt with its transcript uuid so a run can later be continued from it.
        opts["extra_args"] = {"replay-user-messages": None, **(self.options_kwargs.get("extra_args") or {})}
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
        run_state = kwargs.get("run_state")
        continuation: Optional[ExternalContinuation] = kwargs.get("continuation")
        store = self._transcript_store(session.session_id) if session is not None else None
        if continuation is not None:
            resume = await self._afork_sdk_session(continuation.anchor, store)
        else:
            resume = self._get_sdk_session_id(session, session_id)

        while True:
            if run_state is not None:
                run_state.clear()
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
                    self._record_message_ref(sdk, message, run_state)
                    if isinstance(message, sdk.UserMessage) and not self._tool_result_ids(sdk, message):
                        # The echoed prompt is bookkeeping only; adapters never see it.
                        continue
                    if isinstance(message, sdk.ResultMessage):
                        self._check_result_message(sdk, message)
                    if not isinstance(message, sdk.SystemMessage):
                        received = True
                    sdk_session_id = None
                    if isinstance(message, sdk.SystemMessage) and getattr(message, "subtype", None) == "init":
                        sdk_session_id = (getattr(message, "data", {}) or {}).get("session_id")
                    elif isinstance(message, sdk.ResultMessage):
                        sdk_session_id = getattr(message, "session_id", None)
                    if sdk_session_id:
                        self._remember_sdk_session(session, session_id, sdk_session_id)
                        if run_state is not None:
                            run_state["session_id"] = sdk_session_id
                    yield message
                return
            except Exception as e:
                await araise_if_cancelled(run_id)
                if resume is None or received or continuation is not None or not self._is_missing_session(sdk, e):
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

    # ---------------------------------------------------------------------------
    # Continue from a message boundary
    # ---------------------------------------------------------------------------

    @staticmethod
    def _tool_result_ids(sdk: Any, message: Any) -> List[str]:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            return []
        return [block.tool_use_id for block in content if isinstance(block, sdk.ToolResultBlock)]

    def _record_message_ref(self, sdk: Any, message: Any, run_state: Optional[Dict[str, Any]]) -> None:
        """Remember which transcript uuid produced each top-level prompt, tool call, tool result and reply."""
        uuid = getattr(message, "uuid", None)
        if run_state is None or not uuid or getattr(message, "parent_tool_use_id", None):
            return
        if isinstance(message, sdk.AssistantMessage):
            run_state["final"] = uuid
            for block in message.content:
                if isinstance(block, sdk.ToolUseBlock):
                    run_state[f"call:{block.id}"] = uuid
        elif isinstance(message, sdk.UserMessage):
            result_ids = self._tool_result_ids(sdk, message)
            for tool_use_id in result_ids:
                run_state[f"result:{tool_use_id}"] = uuid
            if not result_ids:
                run_state.setdefault("prompt", uuid)

    def _annotate_run_output(self, run: RunOutput, run_state: Dict[str, Any]) -> None:
        """Store each message's transcript position and mark tool results as checkpoints."""
        sdk_session_id = run_state.get("session_id")
        if not sdk_session_id or not run.messages:
            return
        last = len(run.messages) - 1
        for index, message in enumerate(run.messages):
            if (message.provider_data or {}).get(self._MESSAGE_REF_KEY):
                continue
            if message.role == "user":
                key = "prompt"
            elif message.role == "tool":
                key = f"result:{message.tool_call_id}"
            elif message.tool_calls:
                key = f"call:{message.tool_calls[0].get('id')}"
            elif index == last:
                key = "final"
            else:
                continue
            uuid = run_state.get(key)
            if uuid is None:
                continue
            ref = {"session_id": sdk_session_id, "uuid": uuid}
            message.provider_data = {**(message.provider_data or {}), self._MESSAGE_REF_KEY: ref}
            if message.role == "tool":
                message.checkpoint_status = RunStatus.running.value
                message.checkpoint_created_at = message.created_at

    async def _afork_sdk_session(self, anchor: Dict[str, Any], store: Any) -> Optional[str]:
        """Fork the stored SDK transcript at the anchor; None starts a fresh SDK session."""
        if store is None:
            raise ValueError("Continuing a ClaudeAgent run requires a database with transcript storage")
        up_to: Optional[str] = anchor["uuid"]
        if anchor.get("before"):
            key = {"project_key": store.project_key, "session_id": anchor["session_id"]}
            entries = await store.load(key) or []
            entry = next((entry for entry in entries if entry.get("uuid") == up_to), None)
            if entry is None:
                raise ValueError(f"Claude SDK transcript entry {up_to} was not found")
            up_to = entry.get("parentUuid")
            if up_to is None:
                return None
        forked = await _sdk().fork_session_via_store(
            store, anchor["session_id"], directory=self.cwd, up_to_message_id=up_to
        )
        return forked.session_id

    def _build_continuation(
        self,
        source: RunOutput,
        *,
        continue_from: Union[int, Literal["end", "last_user"]],
        fork: bool,
        input: Optional[str],
    ) -> Tuple[Any, str, ExternalContinuation]:
        """Resolve a boundary in a stored run into the prompt, run id and kept transcript for the replay."""
        from agno.agent._run import _resolve_continue_from
        from agno.utils.message import safe_truncation_index

        messages = source.messages or []
        index = safe_truncation_index(messages, _resolve_continue_from(source, continue_from=continue_from))
        if not 1 <= index <= len(messages):
            raise ValueError(f"continue_from must resolve to a message boundary between 1 and {len(messages)}")
        ref = (messages[index - 1].provider_data or {}).get(self._MESSAGE_REF_KEY)
        if not ref:
            raise ValueError(
                "This run has no Claude SDK transcript position at that boundary; "
                "only runs recorded with transcript storage can be continued"
            )
        # Replaying the whole turn re-sends the original prompt from just before it.
        restart = index == 1 and input is None and messages[0].role == "user"
        if restart:
            prompt = source.input.input_content if source.input is not None else None
            if prompt is None:
                raise ValueError("The run has no stored input to replay")
            kept: List[Any] = []
            tools = None
            record_input: Any = prompt
        else:
            prompt = input or self._CONTINUE_PROMPT
            kept = copy.deepcopy(messages[:index])
            call_ids = {message.tool_call_id for message in kept if message.tool_call_id}
            tools = [copy.deepcopy(tool) for tool in source.tools or [] if tool.tool_call_id in call_ids] or None
            record_input = input
        continuation = ExternalContinuation(
            messages=kept,
            tools=tools,
            source_input=copy.deepcopy(source.input),
            record_input=record_input,
            anchor={"session_id": ref["session_id"], "uuid": ref["uuid"], "before": restart},
            forked_from_run_id=source.run_id if fork else source.forked_from_run_id,
            forked_from_message_index=index if fork else source.forked_from_message_index,
        )
        return prompt, str(uuid4()) if fork else str(source.run_id), continuation

    @staticmethod
    def _check_continue_args(
        requirements: Any,
        updated_tools: Any,
        regenerate: bool,
        replace_original: Optional[bool],
        additional_instructions: Optional[str],
    ) -> None:
        if requirements or updated_tools:
            raise ValueError("ClaudeAgent runs have no human-in-the-loop requirements to resolve")
        if regenerate or replace_original is not None or additional_instructions is not None:
            raise ValueError("ClaudeAgent does not support regenerate; use continue_from='last_user' with fork=True")

    def continue_run(
        self,
        run_response: Optional[RunOutput] = None,
        *,
        run_id: Optional[str] = None,
        requirements: Optional[List[Any]] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        input: Optional[str] = None,
        continue_from: Union[int, Literal["end", "last_user"]] = "end",
        fork: bool = False,
        regenerate: bool = False,
        replace_original: Optional[bool] = None,
        additional_instructions: Optional[str] = None,
        stream: bool = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Union[RunOutput, Iterator[RunOutputEvent]]:
        """Continue a stored run from a message boundary by forking its SDK transcript there.

        continue_from accepts "end", "last_user" or a message index. With fork=True the replay is a new
        sibling run; otherwise it replaces the source run. Files the agent changed are not rewound.
        """
        self._check_continue_args(requirements, updated_tools, regenerate, replace_original, additional_instructions)
        source = run_response or self.get_run_output(run_id or "", session_id, user_id)
        if source is None:
            raise ValueError(f"Run {run_id} not found in session {session_id}")
        prompt, new_run_id, continuation = self._build_continuation(
            source, continue_from=continue_from, fork=fork, input=input
        )
        return self.run(
            prompt,
            stream=stream,
            session_id=source.session_id,
            user_id=user_id or source.user_id,
            run_id=new_run_id,
            continuation=continuation,
            **kwargs,
        )

    def acontinue_run(
        self,
        run_response: Optional[RunOutput] = None,
        *,
        run_id: Optional[str] = None,
        requirements: Optional[List[Any]] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        input: Optional[str] = None,
        continue_from: Union[int, Literal["end", "last_user"]] = "end",
        fork: bool = False,
        regenerate: bool = False,
        replace_original: Optional[bool] = None,
        additional_instructions: Optional[str] = None,
        stream: bool = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """Async continue_run: returns a coroutine, or an async iterator when stream=True."""
        self._check_continue_args(requirements, updated_tools, regenerate, replace_original, additional_instructions)
        kwargs.pop("background_tasks", None)
        call = dict(
            run_response=run_response,
            run_id=run_id,
            input=input,
            continue_from=continue_from,
            fork=fork,
            session_id=session_id,
            user_id=user_id,
            **kwargs,
        )
        if stream:
            return self._acontinue_stream(**call)
        return self._acontinue(**call)

    async def _aresolve_continuation(
        self,
        run_response: Optional[RunOutput],
        run_id: Optional[str],
        session_id: Optional[str],
        user_id: Optional[str],
        continue_from: Union[int, Literal["end", "last_user"]],
        fork: bool,
        input: Optional[str],
    ) -> Tuple[RunOutput, Any, str, ExternalContinuation]:
        source = run_response or await self.aget_run_output(run_id or "", session_id, user_id)
        if source is None:
            raise ValueError(f"Run {run_id} not found in session {session_id}")
        prompt, new_run_id, continuation = self._build_continuation(
            source, continue_from=continue_from, fork=fork, input=input
        )
        return source, prompt, new_run_id, continuation

    async def _acontinue(
        self, *, run_response, run_id, input, continue_from, fork, session_id, user_id, **kwargs: Any
    ) -> RunOutput:
        source, prompt, new_run_id, continuation = await self._aresolve_continuation(
            run_response, run_id, session_id, user_id, continue_from, fork, input
        )
        run = self.arun(
            prompt,
            stream=False,
            session_id=source.session_id,
            user_id=user_id or source.user_id,
            run_id=new_run_id,
            continuation=continuation,
            **kwargs,
        )
        return await cast(Awaitable[RunOutput], run)

    async def _acontinue_stream(
        self, *, run_response, run_id, input, continue_from, fork, session_id, user_id, **kwargs: Any
    ) -> AsyncIterator[Any]:
        source, prompt, new_run_id, continuation = await self._aresolve_continuation(
            run_response, run_id, session_id, user_id, continue_from, fork, input
        )
        stream = self.arun(
            prompt,
            stream=True,
            session_id=source.session_id,
            user_id=user_id or source.user_id,
            run_id=new_run_id,
            continuation=continuation,
            **kwargs,
        )
        async for item in cast(AsyncIterator[Any], stream):
            yield item

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
