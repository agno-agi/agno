import copy
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Dict, Iterator, List, Literal, Optional, Tuple, Union, cast
from uuid import uuid4

from agno.agents.base import (
    BaseExternalAgent,
    ExternalContinuation,
    ExternalRunMetricsEvent,
    ExternalRunResult,
    ExternalRunWarningEvent,
)
from agno.db.base import AsyncBaseDb, BaseDb
from agno.exceptions import ModelProviderError, RunNotContinuableError
from agno.metrics import BaseMetrics, ModelMetrics, RunMetrics
from agno.models.message import Message
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
            assistant_error: Optional[str] = None
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
                    if isinstance(message, sdk.AssistantMessage) and getattr(message, "error", None):
                        assistant_error = message.error
                    if isinstance(message, sdk.ResultMessage):
                        self._check_result_message(sdk, message, assistant_error)
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
        # Transcript order: parallel tool results can arrive in a different order than their calls.
        order = run_state.setdefault("order", {})
        if uuid not in order:
            order[uuid] = len(order)
        if isinstance(message, sdk.AssistantMessage):
            run_state["final"] = uuid
            run_state["last"] = uuid
            run_state["final_text"] = (
                "".join(block.text for block in message.content if isinstance(block, sdk.TextBlock))
                if not any(isinstance(block, sdk.ToolUseBlock) for block in message.content)
                else None
            )
            for block in message.content:
                if isinstance(block, sdk.ToolUseBlock):
                    run_state[f"call:{block.id}"] = uuid
        elif isinstance(message, sdk.UserMessage):
            run_state["last"] = uuid
            result_ids = self._tool_result_ids(sdk, message)
            for tool_use_id in result_ids:
                run_state[f"result:{tool_use_id}"] = uuid
            if not result_ids:
                run_state.setdefault("prompt", uuid)

    def _annotate_run_output(self, run: RunOutput, run_state: Dict[str, Any]) -> None:
        """Store each message's transcript position and mark the end of each tool batch as a checkpoint.

        A fork keeps every transcript entry up to a position. Tool results from one batch of
        parallel calls can sit in the transcript in a different order than Agno lists them, so a
        checkpoint is only exposed where the kept messages and the kept transcript agree: at a
        tool result that is later in the transcript than every tool result before it and earlier
        than every tool result after it.
        """
        sdk_session_id = run_state.get("session_id")
        if not sdk_session_id or not run.messages:
            return
        if run.status in (RunStatus.error, RunStatus.cancelled):
            # The base class puts the error text in a synthetic assistant
            # message. It is not a transcript entry; retain the error in
            # run.content and end the messages at the work actually received.
            run.messages.pop()
            if run_state.get("final_text") and run_state.get("last") == run_state.get("final"):
                run.messages.append(Message(role="assistant", content=run_state["final_text"]))
        order: Dict[str, int] = run_state.get("order") or {}
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
            ref: Dict[str, Any] = {"session_id": sdk_session_id, "uuid": uuid}
            if uuid in order:
                ref["position"] = order[uuid]
            message.provider_data = {**(message.provider_data or {}), self._MESSAGE_REF_KEY: ref}
        for message in run.messages:
            if message.role == "tool":
                message.checkpoint_status = None
                message.checkpoint_created_at = None
        for index in self._checkpoint_indexes(run.messages):
            message = run.messages[index]
            message.checkpoint_status = RunStatus.running.value
            message.checkpoint_created_at = message.created_at

    def _ref(self, message: Message) -> Optional[Dict[str, Any]]:
        return (message.provider_data or {}).get(self._MESSAGE_REF_KEY)

    @staticmethod
    def _tool_batches(messages: List[Message]) -> List[List[int]]:
        """Zero-based indexes of tool results, grouped into batches issued before the next reply.

        Parallel calls produce one batch; a fork can only keep a batch whole, because its results
        may sit in the transcript in a different order than Agno lists them.
        """
        batches: List[List[int]] = []
        current: List[int] = []
        last_result_position: Optional[int] = None
        for index, message in enumerate(messages):
            if message.role == "tool":
                current.append(index)
                position = ((message.provider_data or {}).get("claude_sdk") or {}).get("position")
                if position is not None:
                    last_result_position = max(last_result_position or -1, position)
            elif message.role == "assistant" and message.tool_calls:
                # A call issued before the previous result arrived belongs to the same parallel batch;
                # a call issued after it starts a new, sequential step.
                position = ((message.provider_data or {}).get("claude_sdk") or {}).get("position")
                parallel = (
                    current
                    and position is not None
                    and last_result_position is not None
                    and position < last_result_position
                )
                if current and not parallel:
                    batches.append(current)
                    current = []
                    last_result_position = None
            else:
                if current:
                    batches.append(current)
                current = []
                last_result_position = None
        if current:
            batches.append(current)
        return batches

    def _checkpoint_indexes(self, messages: List[Message]) -> List[int]:
        """Zero-based indexes of the last tool result of each batch: the only places a fork is exact."""
        return [
            batch[-1] for batch in self._tool_batches(messages) if all(self._ref(messages[index]) for index in batch)
        ]

    def _batch_end(self, messages: List[Message], index: int) -> int:
        """Move a boundary inside a batch of tool results to the end of that batch."""
        if index <= 0 or index > len(messages) or messages[index - 1].role != "tool":
            return index
        for batch in self._tool_batches(messages):
            if index - 1 in batch:
                return batch[-1] + 1
        return index

    def _batch_anchor(self, messages: List[Message], index: int) -> Optional[Dict[str, Any]]:
        """The transcript entry a fork must keep up to so the whole batch ending at index is kept."""
        for batch in self._tool_batches(messages):
            if index - 1 in batch:
                refs = [self._ref(messages[i]) or {} for i in batch]
                if not all(refs):
                    return None
                return max(refs, key=lambda r: r.get("position", -1)) or None
        return self._ref(messages[index - 1])

    async def _afork_sdk_session(self, anchor: Dict[str, Any], store: Any) -> Optional[str]:
        """Fork the stored SDK transcript at the anchor; None starts a fresh SDK session."""
        if store is None:
            raise RunNotContinuableError("Continuing a ClaudeAgent run requires a database with transcript storage")
        up_to: Optional[str] = anchor["uuid"]
        if anchor.get("before"):
            key = {"project_key": store.project_key, "session_id": anchor["session_id"]}
            entries = await store.load(key) or []
            entry = next((entry for entry in entries if entry.get("uuid") == up_to), None)
            if entry is None:
                raise RunNotContinuableError(f"Claude SDK transcript entry {up_to} was not found")
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

        status = getattr(source.status, "value", source.status)
        if status == RunStatus.cancelled.value:
            raise RunNotContinuableError(f"Cannot continue run {source.run_id}: run is cancelled")
        if not fork and status == RunStatus.completed.value:
            # Like native agents: a finished run is never rewritten in place. Its continuation is a
            # new sibling run with fork lineage, which also keeps the background path's PENDING row new.
            fork = True
        messages = source.messages or []
        if not messages:
            raise ValueError("The run has no messages to continue from")
        requested = _resolve_continue_from(source, continue_from=continue_from)
        index = 0 if requested == 0 else safe_truncation_index(messages, requested)
        if not 0 <= index <= len(messages):
            raise ValueError(f"continue_from must resolve to a message boundary between 0 and {len(messages)}")
        index = self._batch_end(messages, index)
        # The boundary message decides the mode: a user message without new input is replayed from
        # just before it; index 0 drops everything and needs new input; anything else continues after.
        boundary = messages[index - 1] if index > 0 else messages[0]
        ref = self._batch_anchor(messages, index) if boundary.role == "tool" else self._ref(boundary)
        if not ref:
            raise ValueError(
                "This run has no Claude SDK transcript position at that boundary; "
                "only runs recorded with transcript storage can be continued"
            )
        replay = index > 0 and input is None and boundary.role == "user"
        if index == 0:
            if input is None:
                raise ValueError("continue_from=0 drops the whole transcript; provide input to start the branch")
            prompt: Any = input
            kept: List[Any] = []
            tools = None
            record_input: Any = input
            before = True
        elif replay:
            prompt = boundary.content if boundary.content else None
            if prompt is None and index == 1 and source.input is not None:
                prompt = source.input.input_content
            if prompt is None:
                raise ValueError("The selected user message has no content to replay")
            kept = copy.deepcopy(messages[: index - 1])
            call_ids = {message.tool_call_id for message in kept if message.tool_call_id}
            tools = [copy.deepcopy(tool) for tool in source.tools or [] if tool.tool_call_id in call_ids] or None
            record_input = prompt
            before = True
        else:
            prompt = input or self._CONTINUE_PROMPT
            kept = copy.deepcopy(messages[:index])
            call_ids = {message.tool_call_id for message in kept if message.tool_call_id}
            tools = [copy.deepcopy(tool) for tool in source.tools or [] if tool.tool_call_id in call_ids] or None
            record_input = input
            before = False
        continuation = ExternalContinuation(
            messages=kept,
            tools=tools,
            source_input=copy.deepcopy(source.input),
            record_input=record_input,
            anchor={"session_id": ref["session_id"], "uuid": ref["uuid"], "before": before},
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
        sibling run. A finished run is always continued as a new sibling run with fork lineage, as native
        agents do, whatever fork is set to. Files the agent changed are not rewound.
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

    def _is_retryable_error(self, error: Exception) -> bool:
        if not super()._is_retryable_error(error):
            return False
        # Read by attribute so the SDK's own ResultError classifies the same way.
        if isinstance(error, RunNotContinuableError):
            return False
        if getattr(error, "subtype", None) in _LIMIT_SUBTYPES:
            return False
        if getattr(error, "api_error_status", None) in ModelProviderError.NON_RETRYABLE_STATUS_CODES:
            return False
        if getattr(error, "assistant_error", None) in _PERMANENT_ASSISTANT_ERRORS:
            return False
        cli_not_found = getattr(_sdk(), "CLINotFoundError", None)
        return cli_not_found is None or not isinstance(error, cli_not_found)

    def _metrics_from_result(self, message: Any) -> Optional[RunMetrics]:
        """Map the ResultMessage's usage and cost to RunMetrics.

        Like the native Anthropic model, input_tokens excludes the cached prefix, which is
        reported in cache_read_tokens and cache_write_tokens. Per-model entries come from the
        CLI's modelUsage map so subagents on other models are listed separately.
        """
        usage = getattr(message, "usage", None) or {}
        cost = getattr(message, "total_cost_usd", None)
        model_usage = getattr(message, "model_usage", None) or {}
        if not usage and not model_usage and cost is None:
            return None

        def _int(source: Dict[str, Any], *keys: str) -> int:
            for key in keys:
                if source.get(key) is not None:
                    return int(source[key])
            return 0

        details: List[ModelMetrics] = []
        for model_id, entry in model_usage.items():
            if not isinstance(entry, dict):
                continue
            entry_cost = entry.get("costUSD", entry.get("cost_usd"))
            input_tokens = _int(entry, "inputTokens", "input_tokens")
            output_tokens = _int(entry, "outputTokens", "output_tokens")
            details.append(
                ModelMetrics(
                    id=str(model_id),
                    provider="anthropic",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cache_read_tokens=_int(entry, "cacheReadInputTokens", "cache_read_input_tokens"),
                    cache_write_tokens=_int(entry, "cacheCreationInputTokens", "cache_creation_input_tokens"),
                    cost=float(entry_cost) if entry_cost is not None else None,
                )
            )
        input_tokens = _int(usage, "input_tokens")
        output_tokens = _int(usage, "output_tokens")
        totals = BaseMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_read_tokens=_int(usage, "cache_read_input_tokens"),
            cache_write_tokens=_int(usage, "cache_creation_input_tokens"),
            cost=float(cost) if cost is not None else None,
        )
        if not details:
            details.append(ModelMetrics(id=self.model or "claude", provider="anthropic", **totals.__dict__))
        additional: Dict[str, Any] = {}
        if getattr(message, "num_turns", None) is not None:
            additional["num_turns"] = int(message.num_turns)
        if getattr(message, "duration_api_ms", None) is not None:
            additional["api_duration"] = int(message.duration_api_ms) / 1000
        return self._build_metrics(totals, details, additional)

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
        metrics: Optional[RunMetrics] = None

        async for message in self._aquery(input, history, streaming=False, **kwargs):
            # Share the live accumulator so the base class can persist work
            # already completed if the SDK raises before returning a result.
            if kwargs.get("run_state") is not None:
                kwargs["run_state"]["tools"] = tools
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
                            tool_call_id=block.id,
                            tool_name=block.name,
                            tool_args=block.input,
                            parent_tool_call_id=getattr(message, "parent_tool_use_id", None),
                        )

            elif isinstance(message, sdk.UserMessage) and isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, sdk.ToolResultBlock):
                        tool = tools.setdefault(
                            block.tool_use_id,
                            ToolExecution(
                                tool_call_id=block.tool_use_id,
                                parent_tool_call_id=getattr(message, "parent_tool_use_id", None),
                            ),
                        )
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
                metrics = self._metrics_from_result(message)

        # Prefer ResultMessage.result, fall back to accumulated assistant text
        return ExternalRunResult(
            final_result or assistant_text, list(tools.values()) or None, warnings or None, metrics=metrics
        )

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
        # Carry tool identity and delegation lineage forward to ToolCallCompleted.
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

            elif isinstance(message, sdk.ResultMessage):
                metrics = self._metrics_from_result(message)
                if metrics is not None:
                    yield ExternalRunMetricsEvent(run_id=run_id, agent_id=self.get_id(), metrics=metrics)

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
                            parent_tool_call_id = getattr(message, "parent_tool_use_id", None)
                            tool_info_map[tool_id] = {
                                "name": tool_name,
                                "args": tool_args,
                                "parent_tool_call_id": parent_tool_call_id,
                            }
                            yield ToolCallStartedEvent(
                                run_id=run_id,
                                agent_id=self.get_id(),
                                agent_name=self.name or "",
                                tool=ToolExecution(
                                    tool_call_id=tool_id,
                                    tool_name=tool_name,
                                    tool_args=tool_args,
                                    parent_tool_call_id=parent_tool_call_id,
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
                                    tool_call_error=bool(getattr(block, "is_error", False)),
                                    parent_tool_call_id=info.get(
                                        "parent_tool_call_id", getattr(message, "parent_tool_use_id", None)
                                    ),
                                ),
                            )
