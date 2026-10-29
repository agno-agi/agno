import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from copy import deepcopy
from dataclasses import field
from importlib import import_module
from threading import Event
from typing import Any, AsyncGenerator, ClassVar, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from agno.agents._config import agent_dataclass
from agno.agents.base import BaseExternalAgent, ExternalRunMetricsEvent, ExternalRunResult, session_branch
from agno.exceptions import RunCancelledException
from agno.metrics import ModelMetrics, RunMetrics
from agno.models.response import ToolExecution
from agno.run.agent import RunContentEvent, RunOutput, RunOutputEvent, ToolCallCompletedEvent, ToolCallStartedEvent
from agno.session.agent import AgentSession


def _sdk() -> Any:
    try:
        return import_module("run_agent")
    except ImportError as error:
        raise ImportError(
            "HermesAgent requires NousResearch/hermes-agent's source environment. "
            "Activate the Hermes checkout and install Agno in that environment; "
            "see https://hermes-agent.nousresearch.com/docs/guides/python-library"
        ) from error


class HermesRunError(RuntimeError):
    """A native Hermes failure with its reported retry policy."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(block.get("text", "") for block in value if isinstance(block, dict) and "text" in block)
    if isinstance(value, dict):
        if "content" in value:
            return _text(value["content"])
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def _args(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        with suppress(json.JSONDecodeError):
            value = json.loads(value)
    return deepcopy(value) if isinstance(value, dict) else {"input": value}


def _tool_failed(value: Any) -> bool:
    if isinstance(value, str):
        with suppress(json.JSONDecodeError):
            value = json.loads(value)
    return isinstance(value, dict) and bool(value.get("error") or value.get("isError"))


@agent_dataclass
class HermesAgent(BaseExternalAgent):
    """Embed Nous Research's Hermes agent in Agno and AgentOS.

    Run from an activated Hermes source environment with Agno installed. Hermes
    owns the model/tool loop; Agno supplies sync/async calls, streaming, retries,
    cancellation and database storage. Each turn gets its own native instance
    because AIAgent is not safe to share between concurrent calls. The reusable
    Agno adapter retains Hermes's returned messages per (user_id, session_id).

    ``instructions`` supplements Hermes's system prompt. ``cwd`` is passed to
    Hermes without changing the server's working directory. Memory and background
    review are disabled by default; opt in explicitly for a personal agent.
    ``native_options`` forwards additional AIAgent constructor settings; adapter
    settings, identity and callbacks cannot be overridden through that dictionary.

    Cancellation is cooperative: cleanup waits for Hermes's worker to stop before
    releasing the session. Provider/tool timeouts remain Hermes configuration.
    Uploads and provider-enforced output_schema are not supported. Hermes's home,
    plugins and credentials are shared by the process; cwd is not a sandbox.

    Example:
        from agno.agents.hermes import HermesAgent

        agent = HermesAgent(name="Hermes", enabled_toolsets=["web"])
        agent.print_response("Explain this project", stream=True)
    """

    model: Optional[str] = None
    provider: Optional[str] = None
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: Optional[str] = None
    cwd: Optional[str] = None
    instructions: Optional[str] = None
    enabled_toolsets: Optional[List[str]] = None
    disabled_toolsets: Optional[List[str]] = None
    max_iterations: int = 60
    skip_context_files: bool = False
    skip_memory: bool = True
    skip_background_review: bool = True
    save_trajectories: bool = False
    native_options: Dict[str, Any] = field(default_factory=dict, repr=False)

    _sdk_name: ClassVar[str] = "hermes"
    _STATE_KEY: ClassVar[str] = "hermes_conversation"
    _states: Dict[Tuple[Optional[str], str], Dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            not isinstance(self.max_iterations, int)
            or isinstance(self.max_iterations, bool)
            or self.max_iterations <= 0
        ):
            raise ValueError("HermesAgent max_iterations must be positive")
        self._constructor_options()

    def _constructor_options(self) -> Dict[str, Any]:
        options = {
            "model": self.model or "",
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "cwd": self.cwd,
            "ephemeral_system_prompt": self.instructions,
            "enabled_toolsets": self.enabled_toolsets,
            "disabled_toolsets": self.disabled_toolsets,
            "max_iterations": self.max_iterations,
            "skip_context_files": self.skip_context_files,
            "skip_memory": self.skip_memory,
            "skip_background_review": self.skip_background_review,
            "save_trajectories": self.save_trajectories,
            "quiet_mode": True,
        }
        reserved = set(options) | {
            "session_id",
            "user_id",
            "user_id_alt",
            "user_name",
            "chat_id",
            "chat_name",
            "chat_type",
            "thread_id",
            "session_db",
            "parent_session_id",
            "gateway_session_key",
        }
        conflicts = [key for key in self.native_options if key in reserved or key.endswith("_callback")]
        if conflicts:
            raise ValueError("HermesAgent native_options cannot override: " + ", ".join(sorted(conflicts)))
        return deepcopy({**self.native_options, **options})

    def _run_model(self) -> Tuple[Optional[str], Optional[str]]:
        return self.model, self.provider

    def _annotate_run_output(self, run: RunOutput, run_state: Dict[str, Any]) -> None:
        run.model = run_state.get("model") or run.model
        run.model_provider = run_state.get("provider") or run.model_provider

    def _is_retryable_error(self, error: Exception) -> bool:
        if isinstance(error, HermesRunError):
            return error.retryable
        return not isinstance(error, (TypeError, ValueError)) and super()._is_retryable_error(error)

    def _conversation_state(
        self, session: Optional[AgentSession], session_id: str, user_id: Optional[str], run_id: str
    ) -> Dict[str, Any]:
        if session is None:
            return deepcopy(self._states.get((user_id, session_id)) or {})
        if session.user_id != user_id:
            raise ValueError("This Hermes session belongs to a different user")
        state = (session.session_data or {}).get(self._STATE_KEY)
        if not isinstance(state, dict):
            return {}
        # A deleted run or a changed conversation branch must not resume stale native history.
        branch = session_branch(session.runs, exclude_run_id=run_id)
        if not branch or branch[-1].run_id != state.get("run_id"):
            return {}
        return deepcopy(state)

    async def _ainterrupt_run(self, handle: Any) -> None:
        interrupt = getattr(handle, "hard_interrupt", None) or handle.interrupt
        await asyncio.get_running_loop().run_in_executor(None, interrupt)

    async def _arun_adapter(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> ExternalRunResult:
        chunks: List[str] = []
        tools: Dict[str, ToolExecution] = {}
        metrics: Optional[RunMetrics] = None
        events = self._arun_adapter_stream(input, history=history, **kwargs)
        try:
            async for event in events:
                if isinstance(event, RunContentEvent) and event.content:
                    chunks.append(event.content)
                elif isinstance(event, (ToolCallStartedEvent, ToolCallCompletedEvent)) and event.tool:
                    tools[event.tool.tool_call_id or ""] = event.tool
                elif isinstance(event, ExternalRunMetricsEvent):
                    metrics = event.metrics
        finally:
            await events.aclose()
        return ExternalRunResult(
            content=kwargs.get("run_state", {}).get("final_response", "".join(chunks)),
            tools=list(tools.values()) or None,
            metrics=metrics,
        )

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncGenerator[RunOutputEvent, None]:
        if not isinstance(input, str):
            raise TypeError("HermesAgent input must be a string")
        if kwargs.get("continuation") is not None:
            raise ValueError("HermesAgent does not support checkpoint continuation")
        run_id = kwargs.get("run_id") or str(uuid4())
        session_id = kwargs.get("session_id") or str(uuid4())
        user_id = kwargs.get("user_id")
        session = kwargs.get("session")
        run_state = kwargs.get("run_state", {})
        state = self._conversation_state(session, session_id, user_id, run_id)
        native_history = deepcopy(state.get("messages", history) or [])
        options = self._constructor_options()
        options.update(session_id=state.get("session_id") or str(uuid4()), user_id=user_id)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Tuple[str, Tuple[Any, ...]]] = asyncio.Queue()
        stopping = Event()
        handles: List[Any] = []
        native = None
        tools: Dict[str, ToolExecution] = {}
        completed_tools: Set[str] = set()
        run_state["tools"] = tools
        event_kwargs: Dict[str, Any] = dict(
            run_id=run_id, agent_id=self.get_id(), agent_name=self.name or "", session_id=session_id
        )

        def send(kind: str, *values: Any) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, values))

        def worker() -> None:
            agent = None
            try:
                agent = _sdk().AIAgent(
                    **options,
                    stream_delta_callback=lambda text: send("text", text),
                    interim_assistant_callback=lambda text, **info: send("interim", text, info),
                    tool_start_callback=lambda call_id, name, args: send("start", call_id, name, args),
                    tool_complete_callback=lambda call_id, name, args, result: send(
                        "complete", call_id, name, args, result
                    ),
                )
                handles.append(agent)
                send("ready", agent)
                if stopping.is_set():
                    return
                result = agent.run_conversation(
                    user_message=input, conversation_history=native_history or None, task_id=run_id
                )
                send("result", result)
            except Exception as error:
                send("error", error)
            finally:
                try:
                    if agent is not None:
                        agent.close()
                finally:
                    send("done")

        # Keep blocking conversations off the shared executor so cancellation can
        # still run when many Hermes turns are waiting on a provider or tool.
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agno-hermes")
        future = loop.run_in_executor(executor, worker)
        last_text = ""
        result: Optional[Dict[str, Any]] = None
        try:
            while True:
                kind, values = await queue.get()
                if kind == "ready":
                    native = values[0]
                    self._set_run_handle(run_id, native)
                elif kind == "error":
                    raise values[0]
                elif kind == "done":
                    break
                elif kind == "result":
                    result = values[0]
                elif kind == "text":
                    text = _text(values[0])
                    if text:
                        last_text += text
                        yield RunContentEvent(content=text, **event_kwargs)
                elif kind == "interim":
                    if not values[1].get("already_streamed") and values[0]:
                        yield RunContentEvent(content=_text(values[0]) + "\n\n", **event_kwargs)
                    last_text = ""
                elif kind in ("start", "complete"):
                    call_id, name, args = values[:3]
                    tool = ToolExecution(tool_call_id=str(call_id), tool_name=name, tool_args=_args(args))
                    if kind == "complete":
                        tool.result = _text(values[3])
                        tool.tool_call_error = _tool_failed(values[3])
                        completed_tools.add(tool.tool_call_id or "")
                    tools[tool.tool_call_id or ""] = tool
                    if kind == "start":
                        last_text = ""
                        yield ToolCallStartedEvent(tool=tool, **event_kwargs)
                    else:
                        yield ToolCallCompletedEvent(tool=tool, **event_kwargs)
            await asyncio.shield(future)
            if not isinstance(result, dict):
                raise HermesRunError("Hermes ended without a conversation result")
            run_state.update(model=result.get("model"), provider=result.get("provider"))
            # Some blocked/skipped native tools do not invoke the completion callback.
            # Reconcile only this turn's transcript so old calls are not reported again.
            for tool in self._result_tools(result, input, tools):
                tools[tool.tool_call_id or ""] = tool
                if (tool.tool_call_id or "") not in completed_tools:
                    completed_tools.add(tool.tool_call_id or "")
                    yield ToolCallCompletedEvent(tool=tool, **event_kwargs)
            if result.get("interrupted"):
                raise RunCancelledException("Hermes run was interrupted")
            if result.get("error") or result.get("failed") or result.get("completed") is False:
                raise HermesRunError(
                    str(result.get("error") or result.get("turn_exit_reason") or "Hermes did not complete the turn"),
                    retryable=result.get("failure_retryable") is True,
                )
            final = _text(result.get("final_response"))
            run_state["final_response"] = final
            # Callbacks can be absent on a non-streaming provider or omit a final footer.
            if final and final != last_text.strip():
                remaining = final[len(last_text) :] if last_text and final.startswith(last_text) else final
                if remaining:
                    yield RunContentEvent(content=remaining, **event_kwargs)
            messages = result.get("messages")
            if not isinstance(messages, list):
                raise HermesRunError("Hermes result is missing conversation messages")
            from agno.run.cancel import araise_if_cancelled

            await araise_if_cancelled(run_id)
            metrics = self._result_metrics(result)
            self._remember_conversation(session, session_id, user_id, run_id, options["session_id"], messages)
            if metrics is not None:
                yield ExternalRunMetricsEvent(metrics=metrics, **event_kwargs)
        finally:
            stopping.set()
            try:
                # The consumer may close before it reads the queued ready event.
                handle = native or (handles[0] if handles else None)
                try:
                    if not future.done() and handle is not None:
                        await self._ainterrupt_run(handle)
                finally:
                    # Never release the Agno session while its worker can still execute tools.
                    await asyncio.shield(future)
            finally:
                self._clear_run_handle(run_id)
                executor.shutdown(wait=True)

    @staticmethod
    def _result_tools(
        result: Dict[str, Any], prompt: str, known_tools: Dict[str, ToolExecution]
    ) -> List[ToolExecution]:
        messages = result.get("messages")
        if not isinstance(messages, list):
            return []
        boundary = result.get("current_turn_user_idx")
        if not isinstance(boundary, int) or not 0 <= boundary < len(messages):
            boundary = next(
                (
                    index
                    for index in range(len(messages) - 1, -1, -1)
                    if messages[index].get("role") == "user" and messages[index].get("content") == prompt
                ),
                len(messages),
            )
        current: Dict[str, ToolExecution] = {}
        completed: List[ToolExecution] = []
        for message in messages[boundary:]:
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                call_id = call.get("id")
                if call_id:
                    current[call_id] = deepcopy(known_tools.get(call_id)) or ToolExecution(
                        tool_call_id=call_id,
                        tool_name=function.get("name"),
                        tool_args=_args(function.get("arguments", {})),
                    )
            if message.get("role") == "tool" and message.get("tool_call_id") in current:
                tool = current[message["tool_call_id"]]
                tool.result = _text(message.get("content"))
                tool.tool_call_error = _tool_failed(message.get("content"))
                completed.append(tool)
        return completed

    def _remember_conversation(
        self,
        session: Optional[AgentSession],
        session_id: str,
        user_id: Optional[str],
        run_id: str,
        native_id: str,
        messages: List[Dict[str, Any]],
    ) -> None:
        state = dict(session_id=native_id, run_id=run_id, messages=deepcopy(messages))
        if session is not None:
            if session.session_data is None:
                session.session_data = {}
            session.session_data[self._STATE_KEY] = state
        else:
            self._states[(user_id, session_id)] = state

    def _result_metrics(self, result: Dict[str, Any]) -> Optional[RunMetrics]:
        # Each worker has a fresh AIAgent, so its session counters cover only this turn.
        if not any(key in result for key in ("input_tokens", "prompt_tokens", "total_tokens")):
            return None
        counts = {
            "input_tokens": int(result.get("input_tokens", result.get("prompt_tokens")) or 0),
            "output_tokens": int(result.get("output_tokens", result.get("completion_tokens")) or 0),
            "cache_read_tokens": int(result.get("cache_read_tokens") or 0),
            "cache_write_tokens": int(result.get("cache_write_tokens") or 0),
            "reasoning_tokens": int(result.get("reasoning_tokens") or 0),
        }
        cost = result.get("estimated_cost_usd") if result.get("cost_status") != "unknown" else None
        model = ModelMetrics(
            id=result.get("model") or self.model or "",
            provider=result.get("provider") or self.provider or "",
            total_tokens=int(result.get("total_tokens") or (counts["input_tokens"] + counts["output_tokens"])),
            cost=float(cost) if cost is not None else None,
            input_tokens=counts["input_tokens"],
            output_tokens=counts["output_tokens"],
            cache_read_tokens=counts["cache_read_tokens"],
            cache_write_tokens=counts["cache_write_tokens"],
            reasoning_tokens=counts["reasoning_tokens"],
        )
        return self._build_metrics(model, [model])
