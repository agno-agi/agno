import asyncio
import json
from inspect import signature
from typing import Any, AsyncIterator, ClassVar, Dict, List, Optional, Tuple
from uuid import uuid4

from agno.agents._config import agent_dataclass
from agno.agents.base import BaseExternalAgent, ExternalRunMetricsEvent, ExternalRunResult
from agno.agents.google_adk.utils import abuild_media_parts
from agno.metrics import BaseMetrics, ModelMetrics
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)

_PROVIDER = "Google"
# Native session state key: how many stored Agno turns the native session covers.
_TURNS_KEY = "agno_turns"


@agent_dataclass
class GoogleADKAgent(BaseExternalAgent):
    """Adapter for Google ADK (Agent Development Kit) agents.

    Wraps an ADK agent, or a whole agent tree (LlmAgent with sub-agents, SequentialAgent,
    ParallelAgent, LoopAgent, custom BaseAgent), so it can be used with AgentOS endpoints
    or standalone via .run() / .print_response().

    The adapter drives an ADK Runner. Each Agno session is an ADK session with the same id,
    so ADK keeps the native conversation (events, state) on its session service while Agno
    stores runs, tool calls and metrics. When the ADK session is new but Agno already holds
    history for the session (a new process with the in-memory session service, for example),
    the stored history is replayed in the prompt. Images, audio, videos and files are sent
    to Gemini as native parts of the user message.

    Args:
        name: Display name for this agent.
        id: Unique identifier (auto-generated from name if not set).
        agent: The ADK agent to run (the root of the tree).
        app_name: ADK application name used to scope sessions. Defaults to "agno".
        session_service: ADK session service. Defaults to an in-memory one, which keeps the
            native conversation for the life of the process; use DatabaseSessionService or
            VertexAiSessionService to keep it across processes.
        artifact_service: Optional ADK artifact service.
        memory_service: Optional ADK memory service.
        plugins: Optional ADK plugins passed to the Runner.
        runner: A prebuilt ADK Runner (for example one built from an ADK App). When set,
            agent, app_name and the services above are taken from it.
        run_config: Optional ADK RunConfig applied to every run. Streaming runs switch it to
            SSE streaming mode when no mode is set.
        default_user_id: ADK sessions belong to a user; used when a run has no user_id.

    Example:
        from google.adk.agents import LlmAgent
        from agno.agents.google_adk import GoogleADKAgent

        def get_weather(city: str) -> dict:
            \"\"\"Look up the weather for a city.\"\"\"
            return {"city": city, "forecast": "sunny"}

        adk_agent = LlmAgent(
            name="weather_agent",
            model="gemini-3.7-flash",
            instruction="Answer questions about the weather.",
            tools=[get_weather],
        )

        agent = GoogleADKAgent(name="Weather Agent", agent=adk_agent)

        # Standalone usage
        agent.print_response("What is the weather in Paris?")

        # Or register with AgentOS
        from agno.os.app import AgentOS
        app = AgentOS(agents=[agent])
    """

    agent: Any = None
    app_name: str = "agno"
    session_service: Any = None
    artifact_service: Any = None
    memory_service: Any = None
    plugins: Optional[List[Any]] = None
    runner: Any = None
    run_config: Any = None
    default_user_id: str = "agno"

    _sdk_name: ClassVar[str] = "google-adk"

    def __post_init__(self) -> None:
        super().__post_init__()
        # Built once: the default in-memory session service lives on the runner, so a new
        # runner per run would lose the native conversation between turns.
        self._runner: Any = self.runner

    # ---------------------------------------------------------------------------
    # Runner and session
    # ---------------------------------------------------------------------------

    def _get_runner(self) -> Any:
        if self._runner is not None:
            return self._runner
        try:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
        except ImportError:
            raise ImportError("google-adk is required: pip install google-adk")
        if self.agent is None:
            raise ValueError("No agent provided to GoogleADKAgent")
        if self.session_service is None:
            self.session_service = InMemorySessionService()
        self._runner = Runner(
            app_name=self.app_name,
            agent=self.agent,
            session_service=self.session_service,
            artifact_service=self.artifact_service,
            memory_service=self.memory_service,
            plugins=self.plugins,
        )
        return self._runner

    async def _aget_or_create_session(self, runner: Any, user_id: str, session_id: str, turns: int) -> Tuple[Any, bool]:
        """The ADK session for this Agno session, and whether it carries the conversation so far.

        turns is the number of stored Agno turns before this one. Each run records in the
        native session's state how many turns that session covers, so a native session another
        worker never saw (an in-memory session service behind several AgentOS workers) is
        recognised as stale and rebuilt from the stored history instead of resumed.
        """
        service = runner.session_service
        ids = dict(app_name=runner.app_name, user_id=user_id, session_id=session_id)
        session = await service.get_session(**ids)
        if session is not None:
            covered = (session.state or {}).get(_TURNS_KEY)
            if not session.events:
                return session, False
            if covered is None or covered >= turns:
                return session, True
            await service.delete_session(**ids)
        session = await service.create_session(**ids)
        return session, False

    def _adk_user_id(self, kwargs: Dict[str, Any]) -> str:
        return str(kwargs.get("user_id") or self.default_user_id)

    def _stream_run_config(self) -> Any:
        """The run config for a streaming run: the configured one in SSE mode unless a mode is set."""
        from google.adk.agents.run_config import RunConfig, StreamingMode

        config = self.run_config
        if config is None:
            return RunConfig(streaming_mode=StreamingMode.SSE)
        if config.streaming_mode in (None, StreamingMode.NONE):
            return config.model_copy(update={"streaming_mode": StreamingMode.SSE})
        return config

    def _media_kwargs(self, **media: Any) -> Dict[str, Any]:
        """Gemini is multimodal: every kind is sent as a native part of the user message."""
        accepted = {name: list(values) for name, values in media.items() if values}
        return {"media": accepted} if accepted else {}

    def _run_model(self) -> Tuple[Optional[str], Optional[str]]:
        model = getattr(self.agent, "model", None)
        if model is None:
            return None, None
        model_id = model if isinstance(model, str) else getattr(model, "model", None)
        return (str(model_id), _PROVIDER) if model_id else (None, None)

    async def _ainterrupt_run(self, handle: Any) -> None:
        handle.set()

    # ---------------------------------------------------------------------------
    # Adapter hooks
    # ---------------------------------------------------------------------------

    async def _arun_adapter(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> ExternalRunResult:
        """Non-streaming: run the ADK agent and collect its answer, tool calls and usage."""
        content: List[str] = []
        # Recorded as tools complete, in the run state the base keeps when an attempt fails or
        # is cancelled, so a tool that ran before a later model call failed stays on the run.
        tools: Dict[str, ToolExecution] = kwargs["run_state"].setdefault("tools", {})
        metrics = None
        async for event in self._aevents(input, history, self.run_config, **kwargs):
            if isinstance(event, ExternalRunMetricsEvent):
                metrics = event.metrics
            elif isinstance(event, RunContentEvent):
                content.append(event.content or "")
            elif isinstance(event, (ToolCallStartedEvent, ToolCallCompletedEvent)) and event.tool:
                key = event.tool.tool_call_id or str(uuid4())
                if key not in tools:
                    tools[key] = event.tool
                else:
                    tools[key].result = event.tool.result
                    tools[key].tool_call_error = event.tool.tool_call_error
        return ExternalRunResult(content="".join(content), tools=list(tools.values()) or None, metrics=metrics)

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming: partial text as it arrives, tool calls as ADK executes them."""
        async for event in self._aevents(input, history, self._stream_run_config(), **kwargs):
            yield event

    # ---------------------------------------------------------------------------
    # ADK event translation
    # ---------------------------------------------------------------------------

    async def _aevents(
        self, input: Any, history: Optional[List[Dict[str, Any]]], run_config: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        """Run one turn on the ADK Runner and translate its events.

        Yields RunContentEvent, ToolCallStartedEvent and ToolCallCompletedEvent, then one
        ExternalRunMetricsEvent when the model reported usage.
        """
        try:
            from google.genai import types
        except ImportError:
            raise ImportError("google-adk is required: pip install google-adk")

        runner = self._get_runner()
        run_id = kwargs.get("run_id") or str(uuid4())
        session_id = kwargs["session_id"]
        user_id = self._adk_user_id(kwargs)
        turns = sum(1 for message in history or [] if message.get("role") == "user")
        _, resumed = await self._aget_or_create_session(runner, user_id, session_id, turns)

        prompt = self._build_prompt(input, history, resumed)
        parts: List[Any] = [types.Part.from_text(text=prompt)]
        parts.extend(await abuild_media_parts(kwargs.get("media")))
        new_message = types.Content(role="user", parts=parts)

        run_kwargs: Dict[str, Any] = dict(
            user_id=user_id, session_id=session_id, new_message=new_message, state_delta={_TURNS_KEY: turns + 1}
        )
        if run_config is not None:
            run_kwargs["run_config"] = run_config
        abort = asyncio.Event()
        if "abort_signal" in signature(runner.run_async).parameters:
            run_kwargs["abort_signal"] = abort
        self._set_run_handle(run_id, abort)

        translator = _EventTranslator(run_id=run_id, agent_id=self.get_id(), agent_name=self.name or "")
        try:
            async for event in runner.run_async(**run_kwargs):
                for translated in translator.translate(event):
                    yield translated
        finally:
            self._clear_run_handle(run_id)
        for translated in translator.flush():
            yield translated

        metrics = translator.metrics()
        if metrics is not None:
            yield ExternalRunMetricsEvent(run_id=run_id, agent_id=self.get_id(), metrics=metrics)


class _EventTranslator:
    """Turn ADK events into Agno run events, one invocation at a time.

    In SSE streaming mode ADK yields partial text chunks and then one complete event that
    repeats the whole text; only what the chunks did not already carry is emitted for it.
    A ParallelAgent's sub-agents interleave their chunks, so one source streams live at a
    time: text from any other source is held and emitted whole, as its own block, once the
    live source is done. Blocks are separated by a blank line, so the run's content reads
    the same whether or not it was streamed.
    """

    def __init__(self, *, run_id: str, agent_id: str, agent_name: str) -> None:
        self.run_id = run_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.live: Optional[Tuple[Any, Any]] = None
        self.streamed = ""
        # Text of sources that started while another was live, by (branch, author).
        self.held: Dict[Tuple[Any, Any], str] = {}
        # Sources that completed while held, in completion order, with their full text.
        self.done: List[str] = []
        self.emitted_any = False
        # Tool call ids by name, for providers that return responses without ids.
        self.pending: Dict[str, List[str]] = {}
        self.totals = BaseMetrics()
        self.models: Dict[str, ModelMetrics] = {}
        self.usage_seen = False

    def translate(self, event: Any) -> List[RunOutputEvent]:
        out: List[RunOutputEvent] = []
        if getattr(event, "author", None) == "user":
            return out
        partial = bool(getattr(event, "partial", False))
        content = getattr(event, "content", None)
        parts = list(getattr(content, "parts", None) or []) if content is not None else []

        text = "".join(
            part.text for part in parts if getattr(part, "text", None) and not getattr(part, "thought", False)
        )
        if text:
            source = (getattr(event, "branch", None), getattr(event, "author", None))
            out.extend(self._text(source, text, partial))

        if not partial:
            for call in (part.function_call for part in parts if getattr(part, "function_call", None)):
                call_id = call.id or str(uuid4())
                self.pending.setdefault(call.name or "", []).append(call_id)
                out.append(
                    ToolCallStartedEvent(
                        run_id=self.run_id,
                        agent_id=self.agent_id,
                        agent_name=self.agent_name,
                        tool=ToolExecution(
                            tool_call_id=call_id, tool_name=call.name or "tool", tool_args=dict(call.args or {})
                        ),
                    )
                )
            for response in (part.function_response for part in parts if getattr(part, "function_response", None)):
                queued = self.pending.get(response.name or "", [])
                call_id = response.id or (queued.pop(0) if queued else str(uuid4()))
                if response.id and response.id in queued:
                    queued.remove(response.id)
                result, failed = _tool_result(response.response)
                out.append(
                    ToolCallCompletedEvent(
                        run_id=self.run_id,
                        agent_id=self.agent_id,
                        agent_name=self.agent_name,
                        tool=ToolExecution(
                            tool_call_id=call_id,
                            tool_name=response.name or "tool",
                            result=result,
                            tool_call_error=failed,
                        ),
                    )
                )
            self._count_usage(event)

        error_code = getattr(event, "error_code", None)
        if error_code and not partial and not parts:
            raise RuntimeError(f"Google ADK run failed: {error_code}: {getattr(event, 'error_message', None) or ''}")
        return out

    def _text(self, source: Tuple[Any, Any], text: str, partial: bool) -> List[RunOutputEvent]:
        out: List[RunOutputEvent] = []
        if partial:
            if self.live is None:
                self.live = source
            if self.live == source:
                out.extend(self._content(text, new_turn=not self.streamed))
                self.streamed += text
            else:
                self.held[source] = self.held.get(source, "") + text
            return out
        if self.live == source:
            if text.startswith(self.streamed):
                remainder = text[len(self.streamed) :]
                if remainder:
                    out.extend(self._content(remainder, new_turn=False))
            else:
                out.extend(self._content(text, new_turn=True))
            out.extend(self._finish_live())
        elif self.live is None:
            out.extend(self._content(text, new_turn=True))
        else:
            self.held.pop(source, None)
            self.done.append(text)
        return out

    def _finish_live(self) -> List[RunOutputEvent]:
        """The live source is done: emit the sources that completed meanwhile, then let the
        next held source stream live from what it has so far."""
        out: List[RunOutputEvent] = []
        self.live, self.streamed = None, ""
        for text in self.done:
            out.extend(self._content(text, new_turn=True))
        self.done = []
        if self.held:
            source, text = next(iter(self.held.items()))
            del self.held[source]
            self.live, self.streamed = source, text
            out.extend(self._content(text, new_turn=True))
        return out

    def flush(self) -> List[RunOutputEvent]:
        """Emit whatever is still held when the invocation ends without completing it."""
        out: List[RunOutputEvent] = []
        for text in self.done:
            out.extend(self._content(text, new_turn=True))
        for text in self.held.values():
            out.extend(self._content(text, new_turn=True))
        self.done, self.held, self.live, self.streamed = [], {}, None, ""
        return out

    def _content(self, text: str, *, new_turn: bool) -> List[RunOutputEvent]:
        if new_turn and self.emitted_any:
            text = "\n\n" + text
        self.emitted_any = True
        return [RunContentEvent(run_id=self.run_id, agent_id=self.agent_id, agent_name=self.agent_name, content=text)]

    def _count_usage(self, event: Any) -> None:
        usage = getattr(event, "usage_metadata", None)
        if usage is None:
            return
        self.usage_seen = True
        model_id = str(getattr(event, "model_version", None) or "")
        entry = self.models.setdefault(model_id, ModelMetrics(id=model_id, provider=_PROVIDER))
        for target in (self.totals, entry):
            target.input_tokens += usage.prompt_token_count or 0
            target.output_tokens += usage.candidates_token_count or 0
            target.total_tokens += usage.total_token_count or 0
            target.cache_read_tokens += usage.cached_content_token_count or 0
            target.reasoning_tokens += usage.thoughts_token_count or 0

    def metrics(self) -> Any:
        if not self.usage_seen:
            return None
        return BaseExternalAgent._build_metrics(self.totals, list(self.models.values()))


def _tool_result(response: Any) -> Tuple[str, bool]:
    """ADK wraps a tool's plain return value as {"result": value} and failures as {"error": ...}."""
    if isinstance(response, dict):
        if set(response) == {"result"}:
            value = response["result"]
            return (value if isinstance(value, str) else json.dumps(value, default=str)), False
        if "error" in response and "result" not in response:
            return json.dumps(response, default=str), True
        return json.dumps(response, default=str), False
    return str(response), False
