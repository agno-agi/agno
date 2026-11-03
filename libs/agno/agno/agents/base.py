import asyncio
import json
from contextlib import asynccontextmanager, contextmanager, suppress
from contextvars import ContextVar
from copy import copy
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from time import time
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    ClassVar,
    Coroutine,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    overload,
)
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from agno.agents._config import agent_dataclass
from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.exceptions import InputCheckError, RunCancelledException, SessionBusyError, UnsupportedMediaError
from agno.media import Audio, File, Image, Video
from agno.metrics import BaseMetrics, ModelMetrics, RunMetrics, SessionMetrics
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import (
    CustomEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunContinuedEvent,
    RunErrorEvent,
    RunEvent,
    RunInput,
    RunOutput,
    RunOutputEvent,
    RunPausedEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from agno.utils.events import error_type_of
from agno.utils.log import log_exception, log_warning
from agno.utils.serialize import json_serializer
from agno.utils.string import parse_response_dict_str, parse_response_model_str

if TYPE_CHECKING:
    from agno.sandbox import Sandbox
    from agno.sandbox.checkpoint import CheckpointRef, CheckpointStore
    from agno.sandbox.repository import Repository
    from agno.tools.component import ComponentTool

# Limits for the history replayed into a fresh harness session when the framework's own
# session cannot be resumed. Each tool result keeps its start and its end, where shell
# output carries the exit status, and the whole replay is bounded by dropping the oldest
# entries first.
_HISTORY_TOOL_RESULT_MAX_CHARS = 2000
_HISTORY_TOOL_RESULT_TAIL_CHARS = 400
_HISTORY_MAX_CHARS = 24000


@dataclass
class _LiveHandle:
    agent: "BaseExternalAgent"
    handle: Any
    loop: asyncio.AbstractEventLoop
    # The attempt that registered the handle, so a retry's cleanup never removes the
    # handle a newer attempt registered under the same run id.
    owner: Optional[object] = None
    interrupted: bool = False


_live_handles: Dict[str, _LiveHandle] = {}
# Identifies the attempt currently inside _run_cancellation on this task, so handle cleanup can
# tell its own registration from one a retry of the same run id made in the meantime.
_handle_owner: ContextVar[Optional[object]] = ContextVar("agno_external_handle_owner", default=None)


def _sandbox_harness() -> Any:
    from agno.sandbox import _harness

    return _harness


def run_coroutine_sync(coro: Awaitable[Any]) -> Any:
    """Run a coroutine from sync code.

    On a thread with a running event loop (a notebook, a sync call made inside an async
    server) the coroutine runs on a worker thread with its own loop; otherwise asyncio.run
    is used directly. Shared by the sync wrappers of every external agent.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()  # type: ignore[arg-type]
    return asyncio.run(coro)  # type: ignore[arg-type]


@dataclass
class ExternalRunWarningEvent(CustomEvent):
    """Nonfatal adapter warning emitted to streaming consumers."""

    warning: Optional[Dict[str, Any]] = None


@dataclass
class ExternalRunMetricsEvent(CustomEvent):
    """Token usage and cost reported by a streaming adapter; consumed by the base, not forwarded."""

    metrics: Optional[RunMetrics] = None


@dataclass
class ExternalRunStructuredOutputEvent(CustomEvent):
    """The answer to parse into output_schema when it is not the streamed text; consumed by the base, not forwarded."""

    structured_output: Any = None


@dataclass
class ExternalRunResult:
    """Adapter output with tool executions retained for session history.

    structured_output is the answer to parse into output_schema when content holds something
    else (prose around a tool-delivered object, commentary before the final answer): a decoded
    object or the answer's JSON text.
    """

    content: str
    tools: Optional[List[ToolExecution]] = None
    warnings: Optional[List[Dict[str, Any]]] = None
    metrics: Optional[RunMetrics] = None
    structured_output: Any = None


@dataclass
class ExternalContinuation:
    """Replay of a stored run from one of its message boundaries."""

    messages: List[Message]
    tools: Optional[List[ToolExecution]]
    source_input: Optional[RunInput]
    record_input: Any
    anchor: Dict[str, Any]
    forked_from_run_id: Optional[str] = None
    forked_from_message_index: Optional[int] = None
    # The stored run being continued; the resumed transcript ends there.
    source_run_id: Optional[str] = None


def session_branch(
    session_runs: Optional[Sequence[Any]], exclude_run_id: Optional[str] = None, until_run_id: Optional[str] = None
) -> List[RunOutput]:
    """The runs on the conversation branch that ends at the latest run, or at until_run_id, oldest first."""
    # A fork already contains the retained prefix of its source run. Its
    # predecessor is the source's predecessor, not the most recent sibling.
    # Keep predecessor links so forks of older branches also discard any
    # intervening turns, without copying the entire history for every run.
    runs: List[RunOutput] = []
    predecessors: List[Optional[int]] = []
    indexes: Dict[str, int] = {}
    head: Optional[int] = None
    for run in session_runs or []:
        if not isinstance(run, RunOutput) or not run.messages:
            continue
        if run.run_id == exclude_run_id and run.run_id != until_run_id:
            continue
        predecessor = head
        if run.forked_from_run_id:
            source_index = indexes.get(run.forked_from_run_id)
            # If the source was deleted, its earlier ancestry is unknown;
            # only the prefix retained in the fork is safe to replay.
            predecessor = predecessors[source_index] if source_index is not None else None
        head = len(runs)
        runs.append(run)
        predecessors.append(predecessor)
        if run.run_id:
            indexes[run.run_id] = head
        if until_run_id is not None and run.run_id == until_run_id:
            break

    branch: List[RunOutput] = []
    while head is not None:
        branch.append(runs[head])
        head = predecessors[head]
    return list(reversed(branch))


@agent_dataclass
class BaseExternalAgent:
    """Base class for external SDK and framework adapters.

    Built-in adapters accept keyword-only configuration. sdk identifies the
    integration and is read-only; framework remains a compatibility alias.
    Separate media arguments are rejected unless an adapter explicitly supports
    them. Printing returns the final RunOutput and raises on failure by default.

    Structurally satisfies the AgentProtocol (agno.agent.protocol) — any subclass
    that implements the two hooks below will automatically be compatible with
    AgentOS routing, SSE streaming, and session storage.

    Provides shared infrastructure for:
    - ID and name management
    - Run lifecycle event emission (RunStarted, RunCompleted, RunError)
    - Tool call event wrapping
    - Sync/async run and print_response methods
    - Session persistence via Agno's DB (when db is configured)
    - Retrying failed runs (retries, delay_between_retries, exponential_backoff)

    Subclasses must implement:
    - _arun_adapter(input, **kwargs) -> str | ExternalRunResult  (non-streaming)
    - _arun_adapter_stream(input, **kwargs) -> AsyncIterator[RunOutputEvent]  (streaming)
    """

    name: Optional[str] = None
    id: Optional[str] = None
    description: Optional[str] = None
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    markdown: bool = True
    # Seconds a native permission request or question waits for the person's decision, and a continuation client waits.
    # Queue/sandbox execution also uses this as its cumulative human-wait budget.
    hitl_timeout: float = 900
    # Fail closed when native context is missing; sandbox restoration requires exact continuity.
    require_native_resume: bool = False
    # Propagate local persistence failures before acknowledging a runtime result.
    strict_persistence: bool = False
    # Run the whole harness process in a computer from this sandbox each turn, e.g. DockerSandbox(image).
    sandbox: Optional["Sandbox"] = field(default=None, repr=False)
    repository: Optional["Repository"] = None

    _sdk_name: ClassVar[str] = "external"
    # Runtime name the sandbox uses to rebuild this adapter; None means it cannot be sandboxed.
    _sandbox_runtime: ClassVar[Optional[str]] = None

    # Keep the streamed events on the persisted run (RunOutput.events), as Agent does, so a
    # finished run can be shown and replayed from the database. AgentOS turns this on.
    store_events: bool = False
    # Events not kept when store_events is on. Defaults to RunContent: the deltas add up to
    # the run's content, which is stored anyway.
    events_to_skip: Optional[List[RunEvent]] = None
    # Number of times to retry a failed run
    retries: int = 0
    # Delay between retries (in seconds)
    delay_between_retries: int = 1
    # Exponential backoff: if True, the delay between retries is doubled each time
    exponential_backoff: bool = False
    # Pydantic model or plain JSON Schema the final answer must match. As with Agent, the run's
    # content is the parsed model (or dict), and stays the answer text if it cannot be parsed.
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None

    # Shown to a team leader next to the name and description when this agent is a team member.
    role: Optional[str] = None

    # Adapters that pass output_schema to their framework set this; others reject the option.
    _supports_output_schema: ClassVar[bool] = False
    # A second concurrent turn on a session is refused, so the durable queue always serializes these.
    one_turn_per_session: ClassVar[bool] = True

    def __post_init__(self) -> None:
        from agno.utils.string import generate_id_from_name

        if self.id is None:
            self.id = generate_id_from_name(self.name)
        # session_id -> run_id of the turn this process is running on it. A session accepts
        # one turn at a time: the harness keeps one conversation per session on its side.
        self._sessions_in_flight: Dict[str, str] = {}
        if self.events_to_skip is None:
            self.events_to_skip = [RunEvent.run_content]
        self._check_output_schema(self.output_schema)
        if self._uses_native_hitl:
            from agno.agents._hitl import validate_native_hitl

            validate_native_hitl(self)
            self.store_events = True
        if self.repository is not None:
            from agno.sandbox.repository import Repository

            if not isinstance(self.repository, Repository):
                raise TypeError("agent.repository must be a Repository")
            if self.sandbox is None:
                raise ValueError("agent.repository requires sandbox=")
        if self.sandbox is not None:
            _sandbox_harness().validate(self)

    @property
    def _uses_native_hitl(self) -> bool:
        """Whether native policy can ask for permission and a database can hold the paused run."""
        return False

    @property
    def sdk(self) -> str:
        """Integration identifier selected by the adapter, not a constructor option."""
        # Older custom subclasses may still declare a framework field.
        if self._sdk_name == "external":
            legacy = vars(self).get("framework")
            if isinstance(legacy, str):
                return legacy
        return self._sdk_name

    @property
    def framework(self) -> str:
        """Compatibility alias for sdk; existing wire and storage keys are retained."""
        return self.sdk

    def get_id(self) -> str:
        """Return the agent ID, guaranteed non-None after construction."""
        return self.id or ""

    def as_tool(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        title: Optional[str] = None,
        annotations: Optional[Dict[str, Any]] = None,
    ) -> "ComponentTool":
        """Publish this external-framework agent as a tool with its own model-facing
        name, description, title, and behaviour annotations, for surfaces that turn
        components into tools -- today the AgentOS MCP server: ``MCPConfig(tools=[adapter.as_tool(name=...,
        description=...)])``. Every override is optional; the adapter ``id`` remains
        the run/scope handle.

        ``title`` is the human-facing display name; ``annotations`` are MCP behaviour
        hints (``readOnlyHint``, ``destructiveHint``, ``idempotentHint``,
        ``openWorldHint``) merged over the publishing surface's defaults -- see
        :mod:`agno.tools.annotations`.
        """
        from agno.tools.component import ComponentTool

        return ComponentTool(component=self, name=name, description=description, title=title, annotations=annotations)

    # ---------------------------------------------------------------------------
    # Public async API (satisfies AgentProtocol protocol)
    # ---------------------------------------------------------------------------

    @overload
    def arun(
        self,
        input: Any,
        *,
        stream: Optional[Literal[False]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: bool = False,
        yield_run_output: bool = False,
        **kwargs: Any,
    ) -> Coroutine[Any, Any, RunOutput]: ...

    @overload
    def arun(
        self,
        input: Any,
        *,
        stream: Literal[True],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: Literal[False] = False,
        yield_run_output: Literal[False] = False,
        **kwargs: Any,
    ) -> AsyncIterator[RunOutputEvent]: ...

    @overload
    def arun(
        self,
        input: Any,
        *,
        stream: Literal[True],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: Literal[False] = False,
        yield_run_output: Literal[True],
        **kwargs: Any,
    ) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]: ...

    @overload
    def arun(
        self,
        input: Any,
        *,
        stream: Literal[True],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: Literal[True],
        yield_run_output: Literal[False] = False,
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...

    @overload
    def arun(
        self,
        input: Any,
        *,
        stream: Literal[True],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: Literal[True],
        yield_run_output: Literal[True],
        **kwargs: Any,
    ) -> AsyncIterator[Union[str, RunOutput]]: ...

    @overload
    def arun(
        self,
        input: Any,
        *,
        stream: Literal[True],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: bool = False,
        yield_run_output: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[Union[RunOutputEvent, RunOutput, str]]: ...

    @overload
    def arun(
        self,
        input: Any,
        *,
        stream: Optional[bool] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: bool = False,
        yield_run_output: bool = False,
        **kwargs: Any,
    ) -> Union[Coroutine[Any, Any, RunOutput], AsyncIterator[Union[RunOutputEvent, RunOutput, str]]]: ...

    def arun(
        self,
        input: Any,
        *,
        stream: Optional[bool] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: bool = False,
        yield_run_output: bool = False,
        **kwargs: Any,
    ) -> Union[Coroutine[Any, Any, RunOutput], AsyncIterator[Union[RunOutputEvent, RunOutput, str]]]:
        """Await a result, or iterate events when stream=True.

        yield_run_output appends the terminal RunOutput to a stream. Background
        streams yield SSE strings rather than event objects. Separate media
        arguments require adapter support; unsupported media fails before work starts.
        """
        if "repository" in kwargs:
            raise ValueError("repository is agent configuration; set agent.repository=Repository(...)")
        kwargs.update(self._media_kwargs(images=images, audio=audio, videos=videos, files=files))
        run_id = run_id or str(uuid4())
        session_id = session_id or str(uuid4())
        kwargs.update(run_id=run_id, session_id=session_id, user_id=user_id)
        if background:
            if self.db is None:
                raise ValueError("Background execution requires a database")
            if stream:
                return self._arun_background_stream(input, yield_run_output=yield_run_output, **kwargs)
            return self._astart_background(input, stream=False, yield_run_output=yield_run_output, **kwargs)
        if stream:
            return self._arun_stream(input, yield_run_output=yield_run_output, **kwargs)
        return self._arun_non_stream(input, **kwargs)

    @overload
    def run(
        self,
        input: Any,
        *,
        stream: Literal[False] = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: bool = False,
        yield_run_output: bool = False,
        **kwargs: Any,
    ) -> RunOutput: ...

    @overload
    def run(
        self,
        input: Any,
        *,
        stream: Literal[True],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: Literal[False] = False,
        yield_run_output: Literal[False] = False,
        **kwargs: Any,
    ) -> Iterator[RunOutputEvent]: ...

    @overload
    def run(
        self,
        input: Any,
        *,
        stream: Literal[True],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: Literal[False] = False,
        yield_run_output: Literal[True],
        **kwargs: Any,
    ) -> Iterator[Union[RunOutputEvent, RunOutput]]: ...

    @overload
    def run(
        self,
        input: Any,
        *,
        stream: Literal[True],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: bool = False,
        yield_run_output: bool = False,
        **kwargs: Any,
    ) -> Iterator[Union[RunOutputEvent, RunOutput]]: ...

    @overload
    def run(
        self,
        input: Any,
        *,
        stream: bool = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: bool = False,
        yield_run_output: bool = False,
        **kwargs: Any,
    ) -> Union[RunOutput, Iterator[Union[RunOutputEvent, RunOutput]]]: ...

    def run(
        self,
        input: Any,
        *,
        stream: bool = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        background: bool = False,
        yield_run_output: bool = False,
        **kwargs: Any,
    ) -> Union[RunOutput, Iterator[Union[RunOutputEvent, RunOutput]]]:
        """Run synchronously, or iterate events when stream=True.

        Background work requires arun on a persistent event loop. With
        yield_run_output=True, a stream ends with the terminal RunOutput.
        """
        if background:
            raise ValueError("Use arun(background=True) on a persistent event loop")
        if "repository" in kwargs:
            raise ValueError("repository is agent configuration; set agent.repository=Repository(...)")
        kwargs.update(self._media_kwargs(images=images, audio=audio, videos=videos, files=files))
        if run_id is not None:
            kwargs["run_id"] = run_id
        if stream:
            return self._run_stream(
                input, session_id=session_id, user_id=user_id, yield_run_output=yield_run_output, **kwargs
            )
        return run_coroutine_sync(self._arun_non_stream(input, session_id=session_id, user_id=user_id, **kwargs))

    def _media_kwargs(self, **media: Any) -> Dict[str, Any]:
        """Adapters supporting media must override this and forward it to their SDK."""
        provided = [name for name, values in media.items() if values]
        if provided:
            raise UnsupportedMediaError(
                f"{type(self).__name__} does not support separate {', '.join(provided)} inputs. "
                "Use text input or the adapter's documented native input format.",
                media=provided,
            )
        return {}

    def print_response(
        self,
        input: Any,
        *,
        stream: bool = True,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        markdown: Optional[bool] = None,
        show_message: bool = True,
        raise_on_error: bool = True,
        **kwargs: Any,
    ) -> RunOutput:
        """Render progress and return the terminal result.

        Errors and cancellations raise after rendering by default. Set
        raise_on_error=False to inspect unsuccessful results directly.
        Background execution is not supported by this interactive helper.
        """
        from rich.console import Console
        from rich.live import Live

        from agno.agents._response import ResponseDisplay

        if kwargs.pop("background", False):
            raise ValueError("Use arun(background=True) directly for background execution")
        kwargs.pop("yield_run_output", None)
        display = ResponseDisplay(
            label=self.name or self.sdk,
            input=input,
            markdown=self.markdown if markdown is None else markdown,
            show_message=show_message,
        )
        console = Console()
        if stream:
            with Live(display.render(), console=console) as live:
                for event in self.run(
                    input, stream=True, session_id=session_id, user_id=user_id, yield_run_output=True, **kwargs
                ):
                    display.update(event)
                    live.update(display.render())
                live.update(display.render(finished=True))
        else:
            display.update(self.run(input, stream=False, session_id=session_id, user_id=user_id, **kwargs))
            console.print(display.render(finished=True))
        return display.finish(raise_on_error=raise_on_error)

    async def aprint_response(
        self,
        input: Any,
        *,
        stream: bool = True,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        markdown: Optional[bool] = None,
        show_message: bool = True,
        raise_on_error: bool = True,
        **kwargs: Any,
    ) -> RunOutput:
        """Render progress and return the terminal result.

        Errors and cancellations raise after rendering by default. Set
        raise_on_error=False to inspect unsuccessful results directly.
        Background execution is not supported by this interactive helper.
        """
        from rich.console import Console
        from rich.live import Live

        from agno.agents._response import ResponseDisplay

        if kwargs.pop("background", False):
            raise ValueError("Use arun(background=True) directly for background execution")
        kwargs.pop("yield_run_output", None)
        display = ResponseDisplay(
            label=self.name or self.sdk,
            input=input,
            markdown=self.markdown if markdown is None else markdown,
            show_message=show_message,
        )
        console = Console()
        if stream:
            with Live(display.render(), console=console) as live:
                async for event in self.arun(
                    input, stream=True, session_id=session_id, user_id=user_id, yield_run_output=True, **kwargs
                ):
                    display.update(event)
                    live.update(display.render())
                live.update(display.render(finished=True))
        else:
            display.update(await self.arun(input, stream=False, session_id=session_id, user_id=user_id, **kwargs))
            console.print(display.render(finished=True))
        return display.finish(raise_on_error=raise_on_error)

    # ---------------------------------------------------------------------------
    # Session persistence helpers
    # ---------------------------------------------------------------------------

    def _create_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> AgentSession:
        """Create a new AgentSession. ``team_id`` or ``workflow_id`` is set when this agent runs as
        that team's member or that workflow's step."""
        return AgentSession(
            session_id=session_id,
            agent_id=self.get_id(),
            team_id=team_id,
            workflow_id=workflow_id,
            user_id=user_id,
            session_data={},
            agent_data={"agent_id": self.id, "agent_name": self.name, "sdk": self.sdk},
            # A member's or step's own session says which team or workflow it belongs to; agent
            # session rows do not store those ids, so the link is kept in the metadata.
            metadata=self._parent_metadata(team_id, workflow_id),
            runs=[],
            created_at=int(time()),
        )

    @staticmethod
    def _pop_run_parent(kwargs: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """The (team id, workflow id) a team or workflow passed for this call, removed from ``kwargs``.

        A team passes ``_team_id`` for a member call and a workflow ``_workflow_id`` for a step; neither is
        forwarded to the adapter."""
        return kwargs.pop("_team_id", None), kwargs.pop("_workflow_id", None)

    @staticmethod
    def _parent_id(team_id: Optional[str], workflow_id: Optional[str]) -> Optional[str]:
        """The id of the team or workflow this call runs for, or None for a standalone run."""
        return team_id if team_id is not None else workflow_id

    @staticmethod
    def _parent_metadata(team_id: Optional[str], workflow_id: Optional[str]) -> Dict[str, str]:
        """Session metadata that links this agent's own session back to its team or workflow."""
        return {key: value for key, value in (("team_id", team_id), ("workflow_id", workflow_id)) if value is not None}

    def _state_session_id(self, session_id: str, parent_id: Optional[str] = None) -> str:
        """The session this agent keeps its own state in for a run on ``session_id``.

        A team runs every member, and a workflow every step, under its own session id, and that
        row is the team's or the workflow's. Run for one of them, this agent keeps its native
        conversation (the Claude session, the Codex thread) in a session of its own, one per parent
        session and agent, so two harness agents of one team or workflow never share a conversation
        and the parent's session row is never overwritten. The parent stores the agent's runs in its
        own session. ``parent_id`` is the team or workflow id passed on each call, so the same agent
        instance still saves its standalone runs normally.
        """
        if parent_id is None:
            return session_id
        return f"{session_id}:{self.get_id()}"

    def _sandboxed_member_kwargs(
        self,
        kwargs: Dict[str, Any],
        team_session_id: str,
        member_run_id: str,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """A sandboxed team member's or workflow step's run options: the ones a sandbox takes, on the
        agent's own session and run. Pass ``team_id`` for a member or ``workflow_id`` for a step.

        The member's sandbox session, which holds its computer binding, checkpoints and native
        conversation, is the same per-member session a member without a sandbox keeps its
        conversation in, so the team's session is never bound to one member's computer. The
        sandbox also records the turn as a run of that session, under its own id: a run never
        changes sessions once stored, and the team stores the member's result in the team
        session under the id it assigned, so the two records cannot share one row.
        """
        from agno.sandbox._harness import SANDBOX_RUN_OPTIONS

        # A team or workflow hands its agents native run options; the sandbox refuses the ones it does not take.
        forwarded = {key: value for key, value in kwargs.items() if key in SANDBOX_RUN_OPTIONS}
        if forwarded.get("metadata") is not None:
            # The sandbox takes metadata as JSON. Values such as datetimes become text, as Agno stores them
            # elsewhere; a value JSON cannot hold fails the member's run instead of the team's tool call.
            forwarded["metadata"] = json.loads(json.dumps(forwarded["metadata"], default=json_serializer))
        forwarded["session_id"] = self._state_session_id(team_session_id, self._parent_id(team_id, workflow_id))
        # The sandbox creates this session; this links it back to its team or workflow, as for other agents.
        forwarded["_session_metadata"] = self._parent_metadata(team_id, workflow_id)
        forwarded["run_id"] = f"{member_run_id}.sandbox"
        return forwarded

    def _as_team_member_output(self, item: Any, team_session_id: str, member_run_id: str, sandbox_run_id: str) -> Any:
        """Report a sandboxed member's run and events under the team's session and the run id it assigned.

        The run keeps a pointer to the sandbox's own run in metadata.sandbox.run_id.
        """
        # Runs and run events carry session_id and run_id; anything else in a stream is passed through untouched.
        if isinstance(item, (str, bytes)):
            return item
        # The sandbox keeps its own objects after yielding them (it records its events for its own run),
        # so the team gets a copy under the team's ids and the sandbox's objects keep the sandbox's.
        item = copy(item)
        if getattr(item, "session_id", None) is not None:
            item.session_id = team_session_id
        if getattr(item, "run_id", None) == sandbox_run_id:
            item.run_id = member_run_id
        if isinstance(item, RunOutput):
            sandbox = dict((item.metadata or {}).get("sandbox") or {})
            sandbox["run_id"] = sandbox_run_id
            item.metadata = {**(item.metadata or {}), "sandbox": sandbox}
        return item

    @staticmethod
    async def _araise_if_member_cancelled(member_run_id: str) -> None:
        """Raise when the team cancelled this member's run before it was linked to the sandbox's run.

        Cancelling the member run cascades only to runs already linked to it, so a cancel that arrived
        before the link would otherwise never reach the sandbox."""
        from agno.run.cancel import ais_cancelled

        if await ais_cancelled(member_run_id):
            raise RunCancelledException("Run cancelled")

    def _sandboxed_member_failure(
        self, error: Exception, team_session_id: str, member_run_id: str, input: Any, kwargs: Dict[str, Any]
    ) -> RunOutput:
        """The member's run, recorded as cancelled or failed, for a sandboxed turn that did not complete.

        The team stores it like any member run, and the leader reads its content instead of an exception."""
        cancelled = isinstance(error, RunCancelledException)
        if not cancelled:
            log_warning(f"Sandboxed agent '{self.get_id()}' failed as a team member or workflow step: {error}")
        run = self._build_run_output(
            member_run_id,
            team_session_id,
            kwargs.get("user_id"),
            input,
            "Run cancelled" if cancelled else str(error),
            RunStatus.cancelled if cancelled else RunStatus.error,
            media=kwargs.get("media"),
        )
        if not cancelled:
            run.metadata = self._failure_metadata(error)
        return run

    def _terminal_event_for(self, run: RunOutput) -> RunOutputEvent:
        """The closing stream event for a member run that was cancelled or failed."""
        if run.status == RunStatus.cancelled:
            return RunCancelledEvent(
                run_id=run.run_id, session_id=run.session_id, agent_id=self.get_id(), reason="Run cancelled"
            )
        return RunErrorEvent(
            run_id=run.run_id,
            session_id=run.session_id,
            agent_id=self.get_id(),
            content=str(run.content),
            error_type=(run.metadata or {}).get("error_type"),
        )

    async def _apersist_member_state(self, session: AgentSession) -> None:
        """Save a team member's own session, which holds its native conversation ids, without runs."""
        try:
            await self.aupsert_session(session)
        except Exception as error:
            log_warning(f"Failed to persist team member state for {self.sdk} agent '{self.id}': {error}")
            if self.strict_persistence:
                raise

    def read_or_create_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> AgentSession:
        """Read a session from the DB, or create a new one."""
        session = None
        if self.db is not None and isinstance(self.db, BaseDb):
            session = self.db.get_session(session_id=session_id, session_type=SessionType.AGENT)

        if session is not None and isinstance(session, dict):
            session = AgentSession.from_dict(session)

        if session is None or not isinstance(session, AgentSession):
            session = self._create_session(session_id, user_id, team_id, workflow_id)

        return session

    async def aread_or_create_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> AgentSession:
        """Async read a session from the DB, or create a new one."""
        session = None
        if self.db is not None:
            if isinstance(self.db, AsyncBaseDb):
                session = await self.db.get_session(session_id=session_id, session_type=SessionType.AGENT)
            elif isinstance(self.db, BaseDb):
                session = self.db.get_session(session_id=session_id, session_type=SessionType.AGENT)

        if session is not None and isinstance(session, dict):
            session = AgentSession.from_dict(session)

        if session is None or not isinstance(session, AgentSession):
            session = self._create_session(session_id, user_id, team_id, workflow_id)

        return session

    def upsert_session(self, session: AgentSession) -> None:
        """Persist a session to the DB (sync)."""
        if self.db is None or not isinstance(self.db, BaseDb):
            return
        session.updated_at = int(time())
        self.db.upsert_session(session)

    async def aupsert_session(self, session: AgentSession) -> None:
        """Persist a session to the DB (async)."""
        if self.db is None:
            return
        session.updated_at = int(time())
        if isinstance(self.db, AsyncBaseDb):
            await self.db.upsert_session(session)
        elif isinstance(self.db, BaseDb):
            self.db.upsert_session(session)

    async def _apersist_run_in_session(
        self, session: AgentSession, run_output: RunOutput, *, strict: bool = False
    ) -> None:
        """Append the run to the session and persist both (v3 denormalized storage).

        upsert_session writes only the session row — runs live in their own
        table and must be written via upsert_run, or history is silently lost.
        Worker-owned writes propagate failures so the queue cannot settle an unpersisted run.
        """
        from agno.run.concurrency import get_worker_ownership

        session.upsert_run(run=run_output)
        self._update_session_metrics(session, run_output)
        worker_owned = get_worker_ownership(run_output.run_id or "") is not None
        try:
            if self.db is not None:
                from agno.run.status_persist import apersist_worker_owned_run
                from agno.session._utils import resolve_run_index

                if await apersist_worker_owned_run(
                    self.db,
                    run_output,
                    session.session_id,
                    run_output.user_id or session.user_id,
                    session_data=session.session_data or {},
                ):
                    return
                await self.aupsert_session(session)
                run_index = resolve_run_index(session, run_output)
                user_id = run_output.user_id or session.user_id
                try:
                    if isinstance(self.db, AsyncBaseDb):
                        await self.db.upsert_run(
                            run=run_output, session_id=session.session_id, user_id=user_id, run_index=run_index
                        )
                    elif isinstance(self.db, BaseDb):
                        self.db.upsert_run(
                            run=run_output, session_id=session.session_id, user_id=user_id, run_index=run_index
                        )
                except NotImplementedError:
                    # Adapter not ported to v3 storage; strict runtimes require explicit run rows.
                    if strict or self.strict_persistence:
                        raise
        except Exception as upsert_err:
            log_warning(f"Failed to persist run for {self.sdk} agent '{self.id}': {upsert_err}")
            if strict or worker_owned or self.strict_persistence:
                raise

    async def _arewrite_run_row(self, session: AgentSession, run_output: RunOutput) -> None:
        """Write the run's row again with its current fields; no session metrics are re-added.

        Used after the run was already persisted, when a field only known later (the terminal
        event's stream index) must reach storage. A failure is logged and not raised: the run
        itself is already stored.
        """
        if self.db is None:
            return
        from agno.run.status_persist import apersist_worker_owned_run
        from agno.session._utils import resolve_run_index

        session.upsert_run(run=run_output)
        user_id = run_output.user_id or session.user_id
        try:
            # A queued attempt's write goes through the attempt fence, so a stale attempt cannot
            # overwrite the row a newer attempt owns.
            if await apersist_worker_owned_run(self.db, run_output, session.session_id, user_id):
                return
            run_index = resolve_run_index(session, run_output)
            if isinstance(self.db, AsyncBaseDb):
                await self.db.upsert_run(
                    run=run_output, session_id=session.session_id, user_id=user_id, run_index=run_index
                )
            elif isinstance(self.db, BaseDb):
                self.db.upsert_run(run=run_output, session_id=session.session_id, user_id=user_id, run_index=run_index)
        except NotImplementedError:
            if self.strict_persistence:
                raise
        except Exception as upsert_err:
            log_warning(f"Failed to rewrite run row for {self.framework} agent '{self.id}': {upsert_err}")
            if self.strict_persistence:
                raise

    def get_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[AgentSession]:
        """Read a session scoped to this agent and, when supplied, its user."""
        if self.db is None:
            return None
        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("Use aget_session with an async database")
        session = self.db.get_session(session_id=session_id, session_type=SessionType.AGENT, user_id=user_id)
        if isinstance(session, dict):
            session = AgentSession.from_dict(session)
        if not isinstance(session, AgentSession) or session.agent_id != self.get_id():
            return None
        return session

    async def aget_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[AgentSession]:
        """Read a persisted session without creating a missing session."""
        if self.db is None:
            return None
        if isinstance(self.db, BaseDb):
            # Match the synchronous persistence path, including thread-local in-memory SQLite.
            return self.get_session(session_id, user_id)
        session = await self.db.get_session(session_id=session_id, session_type=SessionType.AGENT, user_id=user_id)
        if isinstance(session, dict):
            session = AgentSession.from_dict(session)
        if not isinstance(session, AgentSession) or session.agent_id != self.get_id():
            return None
        return session

    def cancel_run(self, run_id: str) -> bool:
        """Store cancellation intent and interrupt a live local SDK handle."""
        from agno.run.cancel import cancel_run

        registered = cancel_run(run_id)
        live = _live_handles.get(run_id)
        if live is not None and not live.loop.is_closed():
            asyncio.run_coroutine_threadsafe(live.agent._ainterrupt_live_handle(run_id), live.loop)
        else:
            run_coroutine_sync(self._acancel_unowned_row(run_id))
        return registered

    async def acancel_run(self, run_id: str) -> bool:
        """Store cancellation intent and interrupt the owning process's handle."""
        from agno.run.cancel import acancel_run

        registered = await acancel_run(run_id)
        live = _live_handles.get(run_id)
        if live is not None and not live.loop.is_closed():
            if live.loop is asyncio.get_running_loop():
                await live.agent._ainterrupt_live_handle(run_id)
            else:
                await asyncio.wrap_future(
                    asyncio.run_coroutine_threadsafe(live.agent._ainterrupt_live_handle(run_id), live.loop)
                )
        else:
            await self._acancel_unowned_row(run_id)
        return registered

    async def _acancel_unowned_row(self, run_id: str) -> None:
        """Cancel an unfinished row, including an orphaned native permission wait, without a live handle.

        A row left pending or running by a process that stopped mid-run keeps its session busy,
        and nothing else finishes it, so cancelling it is how the session is freed. The
        cancellation manager's registration is not a reliable sign of a live run: a shared
        (Redis) manager keeps a crashed process's registration until its TTL, a day by default,
        so the row is marked whenever no live handle exists here. A run that is live on another
        replica sees the cancellation through the manager and ends cancelled as well.
        """
        if self.sandbox is not None:
            await _sandbox_harness().acancel_unowned_row(self, run_id)
            return
        if self.db is None:
            return
        from agno.run.status_persist import apersist_run_transition

        try:
            if isinstance(self.db, AsyncBaseDb):
                row = await self.db.get_run(run_id)
            else:
                row = self.db.get_run(run_id)
            if isinstance(row, dict):
                row = RunOutput.from_dict(row)
            if not isinstance(row, RunOutput) or row.agent_id != self.get_id() or row.session_id is None:
                return
            from agno.agents._hitl import KEY as native_key

            native = (row.metadata or {}).get(native_key)
            statuses = [RunStatus.pending.value, RunStatus.running.value]
            if native:
                statuses.extend([RunStatus.paused.value, RunStatus.cancelled.value])
            if getattr(row.status, "value", row.status) not in statuses:
                return
            row.status = RunStatus.cancelled
            extra_fields: Dict[str, Any] = {}
            if not row.content:
                row.content = "Run cancelled"
                extra_fields["content"] = row.content
            if native:
                # The waiting native execution reads the cancelled run and stops; no request stays pending.
                row.requirements = []
                row.metadata = {**(row.metadata or {}), native_key: {**native, "pending": []}}
                extra_fields.update(requirements=[], metadata=row.metadata)
            await apersist_run_transition(
                self, "agent", row.session_id, row, user_id=row.user_id, extra_fields=extra_fields
            )
        except Exception as error:
            log_warning(
                f"Could not mark unowned run {run_id} cancelled for {self.framework} agent '{self.id}': {error}"
            )

    def _set_run_handle(self, run_id: str, handle: Any) -> None:
        _live_handles[run_id] = _LiveHandle(self, handle, asyncio.get_running_loop(), owner=_handle_owner.get())

    def _clear_run_handle(self, run_id: str) -> None:
        """Drop this attempt's handle. A handle a newer attempt registered for the same run is kept."""
        live = _live_handles.get(run_id)
        owner = _handle_owner.get()
        if live is not None and (owner is None or live.owner is owner):
            _live_handles.pop(run_id, None)

    async def _ainterrupt_run(self, handle: Any) -> None:
        """Interrupt an adapter's active SDK handle."""
        raise NotImplementedError

    async def _ainterrupt_live_handle(self, run_id: str) -> None:
        live = _live_handles.get(run_id)
        if live is None or live.interrupted:
            return
        live.interrupted = True
        try:
            await live.agent._ainterrupt_run(live.handle)
        except Exception as error:
            live.interrupted = False
            log_warning(f"Could not interrupt external run {run_id}: {error}")

    @asynccontextmanager
    async def _run_cancellation(self, run_id: str) -> AsyncIterator[None]:
        from agno.run.cancel import acleanup_run, ais_cancelled, araise_if_cancelled, aregister_run

        await aregister_run(run_id)
        owner_token = _handle_owner.set(object())

        async def watch() -> None:
            while True:
                try:
                    if await ais_cancelled(run_id):
                        await self._ainterrupt_live_handle(run_id)
                except Exception as error:
                    log_warning(f"Cancellation check failed for external run {run_id}: {error}")
                await asyncio.sleep(0.5)

        watcher = asyncio.create_task(watch())
        try:
            await araise_if_cancelled(run_id)
            yield
            await araise_if_cancelled(run_id)
        except Exception:
            await araise_if_cancelled(run_id)
            raise
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            self._clear_run_handle(run_id)
            _handle_owner.reset(owner_token)
            await acleanup_run(run_id)

    # ---------------------------------------------------------------------------
    # Structured output
    # ---------------------------------------------------------------------------

    def _check_output_schema(self, output_schema: Any) -> None:
        """Reject an output_schema the adapter cannot send: unsupported adapters, and schemas whose
        root is not a JSON object. Claude Code delivers the object through a tool whose input must
        be an object, and Codex's response format requires an object root, so a list or scalar at
        the top level (a RootModel[List[...]], {"type": "array"}) fails the run on the provider
        side. Wrap such a value in a model field instead."""
        if output_schema is None:
            return
        if not self._supports_output_schema:
            raise ValueError(f"{type(self).__name__} does not support output_schema")
        schema = output_schema if isinstance(output_schema, dict) else output_schema.model_json_schema()
        root_type = schema.get("type")
        if root_type != "object" and not (root_type is None and "properties" in schema):
            raise ValueError(
                f"{type(self).__name__} output_schema must describe a JSON object (got type {root_type!r}); "
                "wrap a list or scalar in a model field"
            )

    def _resolve_output_schema(self, kwargs: Dict[str, Any]) -> Optional[Union[Type[BaseModel], Dict[str, Any]]]:
        """The run's output_schema, the call's over the agent's, left in kwargs for the adapter."""
        output_schema = kwargs.get("output_schema")
        if output_schema is None:
            output_schema = self.output_schema
        self._check_output_schema(output_schema)
        if output_schema is not None:
            kwargs["output_schema"] = output_schema
        return output_schema

    @staticmethod
    def _output_json_schema(output_schema: Union[Type[BaseModel], Dict[str, Any]], provider: str) -> Dict[str, Any]:
        """JSON Schema for the framework: a dict is passed as given, a model is normalized for the provider."""
        if isinstance(output_schema, dict):
            return output_schema
        from agno.utils.models.schema_utils import get_response_schema_for_provider

        return get_response_schema_for_provider(output_schema, provider)

    def _apply_output_schema(
        self,
        run: RunOutput,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]],
        structured_output: Any = None,
    ) -> None:
        """Replace a completed run's content with its answer parsed into output_schema."""
        if output_schema is None or run.status != RunStatus.completed:
            return
        answer = structured_output if structured_output is not None else run.content
        parsed: Any = None
        # A decoded value (the framework already parsed the JSON) is validated as it is; only text
        # goes through the JSON parsers, which also strip fences and surrounding prose.
        if isinstance(output_schema, dict):
            parsed = parse_response_dict_str(answer) if isinstance(answer, str) else answer
            content_type = "dict"
        else:
            content_type = output_schema.__name__
            try:
                if isinstance(answer, str):
                    parsed = parse_response_model_str(answer, output_schema)
                else:
                    parsed = output_schema.model_validate(answer)
            except ValidationError as error:
                log_warning(f"{self.framework} answer does not match {content_type}: {error}")
        if parsed is None:
            log_warning(f"Could not parse the {self.framework} answer into the output_schema; keeping the text")
            return
        run.content = parsed
        run.content_type = content_type

    def _retry_delay(self, attempt: int) -> int:
        if self.exponential_backoff:
            return self.delay_between_retries * (2**attempt)
        return self.delay_between_retries

    def _is_retryable_error(self, error: Exception) -> bool:
        """Whether a failed attempt is worth retrying. Unknown errors are retried; adapters
        override this for errors that fail the same way every time or would bypass a limit.
        An input check error (unsupported or unstageable attachments) fails the same way on
        every attempt."""
        return not isinstance(error, (ImportError, InputCheckError))

    def _failure_metadata(self, error: Exception) -> Dict[str, Any]:
        """Recorded on a run that ends in error. The durable job queue reads ``retryable`` so a
        failure that would repeat (a limit, authentication, billing, a bad request) fails the job
        at once instead of being re-driven for every remaining queue attempt."""
        return {
            "retryable": self._is_retryable_error(error),
            "error_type": error_type_of(error),
        }

    def _should_retry(self, error: Exception, attempt: int, num_attempts: int) -> bool:
        if attempt >= num_attempts - 1:
            return False
        if not self._is_retryable_error(error):
            log_warning(f"{self.framework} agent '{self.id}' hit a non-retryable error, not retrying: {error}")
            return False
        return True

    @staticmethod
    def _collect_attempt_tools(run_state: Dict[str, Any], carried: Dict[str, ToolExecution]) -> None:
        """Take the tool calls a failed attempt left in run_state["tools"] (a dict keyed by call id,
        or a list) so the run keeps them. Adapters set it as tools complete."""
        recorded = run_state.pop("tools", None)
        values = recorded.values() if isinstance(recorded, dict) else (recorded or [])
        for tool in values:
            carried[tool.tool_call_id or str(uuid4())] = tool

    @staticmethod
    def _merge_tools(
        carried: Dict[str, ToolExecution], final: Optional[List[ToolExecution]]
    ) -> Optional[List[ToolExecution]]:
        if not carried:
            return final
        merged = dict(carried)
        for tool in final or []:
            merged[tool.tool_call_id or str(uuid4())] = tool
        return list(merged.values())

    def _retry_warning(self, attempt: int, num_attempts: int, error: Exception) -> Dict[str, Any]:
        return {
            "type": "retry",
            "attempt": attempt + 1,
            "attempts": num_attempts,
            "delay": self._retry_delay(attempt),
            "error": str(error),
            "message": f"Attempt {attempt + 1} of {num_attempts} failed and is being retried; "
            "output streamed before this point came from the failed attempt.",
        }

    async def _await_retry(self, run_id: str, attempt: int, num_attempts: int, error: Exception) -> None:
        """Wait out the backoff before the next attempt, ending early if the run is cancelled."""
        from agno.run.cancel import araise_if_cancelled

        await araise_if_cancelled(run_id)
        delay = self._retry_delay(attempt)
        log_warning(
            f"{self.framework} agent '{self.id}' attempt {attempt + 1}/{num_attempts} failed. "
            f"Retrying in {delay}s...: {error}"
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + delay
        while (remaining := deadline - loop.time()) > 0:
            await asyncio.sleep(min(remaining, 0.5))
            await araise_if_cancelled(run_id)

    async def _aprepare_pending_run(
        self,
        run_id: str,
        session_id: str,
        user_id: Optional[str],
        input: Any,
        queued: bool = False,
        media: Optional[List[Dict[str, Any]]] = None,
    ) -> RunOutput:
        """Persist an idempotent PENDING row before background or queued execution."""
        if self.sandbox is not None:
            return await _sandbox_harness().aprepare_pending_run(self, run_id, session_id, user_id, input, media)
        from agno.os.job_queue import _aappend_pending_run

        run = RunOutput(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            agent_id=self.get_id(),
            agent_name=self.name,
            input=RunInput(input_content=input),
            status=RunStatus.pending,
            # 0 marks a durable queue ticket's row before any claim; in-process rows stay None.
            queue_attempt=0 if queued else None,
        )
        session = await _aappend_pending_run(
            self, session_id, run.to_dict(), user_id, lambda: self.aread_or_create_session(session_id, user_id)
        )
        if session is not None and session.get_run(run_id) is None:
            await self._apersist_run_in_session(session, run, strict=True)
        return run

    def _queue_terminal_writer(self) -> Optional[Callable[..., Awaitable[Any]]]:
        """Queue terminal writer that retires sandbox compute before the ticket settles."""
        if self.sandbox is None:
            return None
        return partial(_sandbox_harness().apersist_queue_terminal, self)

    async def _apersist_run_fallback(
        self, session_id: str, run_response: RunOutput, user_id: Optional[str] = None
    ) -> None:
        """Re-read the session and persist one run; completed or cancelled rows win."""
        if self.sandbox is not None:
            _sandbox_harness().refuse_fallback()
        session = await self.aread_or_create_session(session_id, user_id)
        existing = session.get_run(run_response.run_id or "")
        if existing is not None and existing.status in (RunStatus.completed, RunStatus.cancelled):
            return
        await self._apersist_run_in_session(session, run_response, strict=True)

    async def _astart_background(
        self,
        input: Any,
        *,
        run_id: str,
        session_id: str,
        user_id: Optional[str],
        stream: bool,
        yield_run_output: bool,
        **kwargs: Any,
    ) -> Any:
        if self.sandbox is not None:
            return await _sandbox_harness().astart_background(
                self,
                input,
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                yield_run_output=yield_run_output,
                **kwargs,
            )
        from agno.run.background import _BackgroundStream, _execute_background, _spawn_background
        from agno.run.cancel import aregister_run
        from agno.run.status_persist import apersist_run_transition

        # Checked before the pending row is written, so a busy session is refused at submission.
        self._assert_session_free(await self.aread_or_create_session(session_id, user_id), session_id, run_id)
        run = await self._aprepare_pending_run(run_id, session_id, user_id, input)
        await aregister_run(run_id)
        transport = (
            _BackgroundStream(run, yield_run_output=yield_run_output, end_at_pause=self._uses_native_hitl)
            if stream
            else None
        )
        if transport is not None:
            await transport.register()

        async def transition(full_run: bool) -> None:
            await apersist_run_transition(self, "agent", session_id, run, user_id=user_id, full_run=full_run)

        async def execute() -> None:
            if transport is None:
                result = await self._arun_non_stream(
                    input, run_id=run_id, session_id=session_id, user_id=user_id, **kwargs
                )
                run.__dict__.update(result.__dict__)
            else:
                async for event in self._arun_stream(
                    input, run_id=run_id, session_id=session_id, user_id=user_id, yield_run_output=True, **kwargs
                ):
                    if isinstance(event, RunOutput):
                        run.__dict__.update(event.__dict__)
                    else:
                        await transport.publish(event)
            await transition(True)

        async def failure() -> None:
            if transport is not None:
                if run.status == RunStatus.cancelled:
                    event: RunOutputEvent = RunCancelledEvent(
                        run_id=run_id, session_id=session_id, agent_id=self.get_id(), reason="Run cancelled"
                    )
                else:
                    event = RunErrorEvent(
                        run_id=run_id,
                        session_id=session_id,
                        agent_id=self.get_id(),
                        content=str(run.content or "Background run failed"),
                    )
                await transport.publish(event)

        _spawn_background(
            _execute_background(
                run,
                execute,
                transition,
                on_running=transport.running if transport else None,
                on_terminal=transport.complete if transport else None,
                on_failure=failure,
            )
        )
        return transport if transport is not None else run

    async def _arun_background_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[Any]:
        if self.sandbox is not None:
            events = _sandbox_harness().astream_background(self, input, **kwargs)
            try:
                async for item in events:
                    yield item
            finally:
                await events.aclose()
            return
        transport = await self._astart_background(input, stream=True, **kwargs)
        pump = transport.pump()
        try:
            async for item in pump:
                yield item
        finally:
            await pump.aclose()

    # Run inspection (used by AgentOS /agents/{id}/runs/{run_id} for external agents)

    @staticmethod
    def _find_run_in_session(session: AgentSession, run_id: str) -> Optional[RunOutput]:
        """Find a persisted run by id within the given session."""
        run = session.get_run(run_id)
        return run if isinstance(run, RunOutput) else None

    def get_run_output(
        self, run_id: str, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> Optional[RunOutput]:
        """Get a persisted RunOutput for this adapter."""
        if not session_id:
            return None
        session = self.get_session(session_id, user_id)
        return self._find_run_in_session(session, run_id) if session else None

    async def aget_run_output(
        self, run_id: str, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> Optional[RunOutput]:
        """Get a persisted RunOutput for this adapter."""
        if not session_id:
            return None
        session = await self.aget_session(session_id, user_id)
        return self._find_run_in_session(session, run_id) if session else None

    # ---------------------------------------------------------------------------
    # Sandbox checkpoints
    # ---------------------------------------------------------------------------

    @property
    def checkpoint_store(self) -> "CheckpointStore":
        """The store this agent's sandbox turns checkpoint to.

        The sandbox's ``checkpoints=`` store, else the host-local file default. The default
        is refused while a durable queue worker is active, as the coordinator refuses it,
        because another replica cannot read this host's disk.
        """
        return _sandbox_harness().store(self)

    @asynccontextmanager
    async def aopen_run_checkpoint(self, run_id: str) -> AsyncIterator[Path]:
        """Open the checkpoint a completed sandbox run committed and yield its archive path.

        The path holds the archive's stored bytes, verified by the store before it is yielded,
        read-only, and is valid only inside the context. Extract them with
        ``CheckpointArchive.arestore(path, destination)``, which documents the restored layout.
        Refused when the run is unknown, belongs to another agent, is not COMPLETED or
        committed no checkpoint. A session keeps only its last ``retain_checkpoints`` on the
        sandbox, so an older run's checkpoint raises ``CheckpointObjectNotFound`` once deleted.
        """
        store = self.checkpoint_store
        reference = self._run_checkpoint_ref(run_id, await self._aread_run_row(run_id))
        async with store.aopen_archive(reference) as archive:
            yield archive

    @contextmanager
    def open_run_checkpoint(self, run_id: str) -> Iterator[Path]:
        """Sync ``aopen_run_checkpoint``; an async database must use the async form, as with ``get_session``."""
        store = self.checkpoint_store
        reference = self._run_checkpoint_ref(run_id, self._read_run_row(run_id))
        with store.open_archive(reference) as archive:
            yield archive

    def _read_run_row(self, run_id: str) -> Any:
        if self.db is None:
            raise ValueError(f"{type(self).__name__} has no database to read run {run_id} from")
        if isinstance(self.db, AsyncBaseDb):
            # An async engine's pooled connections belong to the loop that first used them, and a
            # query on another loop fails inside get_run, which would then look like a missing run.
            raise ValueError("Use aopen_run_checkpoint with an async database")
        return self.db.get_run(run_id, deserialize=False)

    async def _aread_run_row(self, run_id: str) -> Any:
        if self.db is None:
            raise ValueError(f"{type(self).__name__} has no database to read run {run_id} from")
        if isinstance(self.db, BaseDb):
            return self.db.get_run(run_id, deserialize=False)
        return await self.db.get_run(run_id, deserialize=False)

    def _run_checkpoint_ref(self, run_id: str, row: Any) -> "CheckpointRef":
        """The checkpoint reference a completed run of this agent committed, from its stored row."""
        from agno.sandbox.checkpoint import CheckpointRef

        if not isinstance(row, dict):
            raise ValueError(f"Run {run_id} does not exist")
        if row.get("agent_id") != self.get_id():
            raise ValueError(f"Run {run_id} belongs to another agent")
        run_data = row.get("run_data") or {}
        if isinstance(run_data, str):
            run_data = json.loads(run_data)
        status = str(row.get("status") or run_data.get("status") or "").upper()
        if status != RunStatus.completed.value:
            raise ValueError(
                f"Run {run_id} is {status or 'unknown'}, not COMPLETED; only a completed turn commits a checkpoint"
            )
        checkpoint = ((run_data.get("metadata") or {}).get("sandbox") or {}).get("checkpoint")
        if not isinstance(checkpoint, dict):
            raise ValueError(f"Run {run_id} committed no sandbox checkpoint")
        return CheckpointRef(**checkpoint)

    # ---------------------------------------------------------------------------
    # One turn per session
    # ---------------------------------------------------------------------------

    @staticmethod
    def _run_in_flight(session: Any, exclude_run_id: Optional[str] = None) -> Optional[RunOutput]:
        """The session's unfinished run (pending or running), other than ``exclude_run_id``."""
        for run in getattr(session, "runs", None) or []:
            status = getattr(run.status, "value", run.status)
            if run.run_id != exclude_run_id and status in (
                RunStatus.pending.value,
                RunStatus.running.value,
                RunStatus.paused.value,
            ):
                return run
        return None

    @staticmethod
    def _run_ahead(session: Any, run_id: str) -> Optional[RunOutput]:
        """The unfinished run a turn starting as ``run_id`` must wait for.

        A running row always blocks. A pending row blocks only when it was accepted before
        ``run_id`` (session runs are in acceptance order), so two queued turns do not each
        refuse the other. A run with no row of its own counts as accepted last. When the
        queue already elected this turn, pending queue tickets ahead are skipped, but
        in-process turns the queue cannot see still block.
        """
        from agno.run.concurrency import get_worker_ownership

        ownership = get_worker_ownership(run_id)
        # A serialized queue has already elected the executable ticket. Pending
        # session rows can arrive in a different order from queue acceptance.
        queue_ordered = ownership is not None and ownership.session_serialized
        ahead = True
        for run in getattr(session, "runs", None) or []:
            if run.run_id == run_id:
                ahead = False
                continue
            status = getattr(run.status, "value", run.status)
            if status in (RunStatus.running.value, RunStatus.paused.value):
                return run
            elected_ahead = queue_ordered and getattr(run, "queue_attempt", None) is not None
            if ahead and status == RunStatus.pending.value and not elected_ahead:
                return run
        return None

    def _assert_session_free(self, session: Any, session_id: str, run_id: str, starting: bool = False) -> None:
        """Raise SessionBusyError when another turn is in flight on the session.

        Two checks: the turns this process is running (exact, no database needed), then the
        session's stored runs, where a pending or running row is a turn accepted on any
        replica. At submission any unfinished row blocks; when a turn starts, only rows ahead
        of it do. A row left unfinished by a crash keeps the session busy until that run is
        cancelled, so the error names the run.
        """
        other = self._sessions_in_flight.get(session_id)
        if other is None:
            if starting:
                blocking = self._run_ahead(session, run_id)
            else:
                blocking = self._run_in_flight(session, exclude_run_id=run_id)
            other = blocking.run_id if blocking is not None else None
        if other is not None and other != run_id:
            raise SessionBusyError(
                f"Session {session_id} already has run {other} in flight. A session takes one turn at a "
                "time: wait for that run to finish, or cancel it, then send the turn again.",
                run_id=other,
                session_id=session_id,
            )

    def _claim_session(self, session: Any, session_id: str, run_id: str) -> None:
        """Hold the session for one turn of ``run_id``; a second turn is rejected until released."""
        self._assert_session_free(session, session_id, run_id, starting=True)
        self._sessions_in_flight[session_id] = run_id

    def _release_session(self, session_id: str, run_id: str) -> None:
        if self._sessions_in_flight.get(session_id) == run_id:
            del self._sessions_in_flight[session_id]

    def _build_run_output(
        self,
        run_id: str,
        session_id: Optional[str],
        user_id: Optional[str],
        input_text: Any,
        content: Any,
        status: RunStatus,
        tools: Optional[List[ToolExecution]] = None,
        metrics: Optional[RunMetrics] = None,
        media: Optional[Dict[str, Any]] = None,
    ) -> RunOutput:
        """Build a RunOutput with properly populated messages for chat history."""
        now = int(time())
        messages: List[Message] = []
        # Skip synthetic user messages for replay/fork (input is None)
        if input_text is not None:
            messages.append(Message(role="user", content=str(input_text), created_at=now))

        # Add tool call messages between user and assistant
        if tools:
            for tool in tools:
                # Tool call request
                tool_call_id = tool.tool_call_id or str(uuid4())
                tool_call_data = {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool.tool_name or "",
                        "arguments": json.dumps(tool.tool_args or {}),
                    },
                }
                messages.append(
                    Message(
                        role="assistant",
                        tool_calls=[tool_call_data],
                        created_at=now,
                    )
                )
                # Tool result
                messages.append(
                    Message(
                        role="tool",
                        tool_call_id=tool_call_id,
                        content=str(tool.result or ""),
                        created_at=now,
                    )
                )

        messages.append(
            Message(role="assistant", content=str(content), created_at=now),
        )

        model_id, model_provider = self._run_model()
        return RunOutput(
            run_id=run_id,
            agent_id=self.get_id(),
            agent_name=self.name,
            session_id=session_id,
            user_id=user_id,
            model=model_id,
            model_provider=model_provider,
            input=(
                RunInput(
                    input_content=str(input_text),
                    images=(media or {}).get("images"),
                    files=(media or {}).get("files"),
                )
                if input_text is not None
                else None
            ),
            content=content,
            messages=messages,
            tools=tools,
            status=status,
            metrics=metrics,
            created_at=now,
        )

    @staticmethod
    def _build_metrics(
        totals: BaseMetrics,
        models: Sequence[ModelMetrics],
        additional_metrics: Optional[Dict[str, Any]] = None,
    ) -> RunMetrics:
        """Assemble RunMetrics from a framework's turn totals and its per-model entries.

        Adapters only parse their SDK's usage object into these two pieces; the totals are
        the framework's own figures for the turn and are not recomputed from the models,
        because frameworks may count helper models separately from the main conversation.
        """
        return RunMetrics(
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            total_tokens=totals.total_tokens,
            cache_read_tokens=totals.cache_read_tokens,
            cache_write_tokens=totals.cache_write_tokens,
            reasoning_tokens=totals.reasoning_tokens,
            cost=totals.cost,
            details={"model": list(models)} if models else None,
            additional_metrics=additional_metrics or None,
        )

    def _run_model(self) -> Tuple[Optional[str], Optional[str]]:
        """The model id and provider recorded on the run, as Agent records its model's id and
        provider. AgentOS's metrics page counts runs per model from these two fields and skips
        runs without one. An adapter with a default model, like a native model has, names the
        model that effectively ran; the default records nothing."""
        return None, None

    @staticmethod
    def _finish_metrics(timer: RunMetrics, adapter_metrics: Optional[RunMetrics]) -> Optional[RunMetrics]:
        """Stop the run timer and merge its timing into the metrics the adapter reported.

        Token counts and cost come from the framework; wall-clock duration and time to
        first token are measured here so every external agent reports them the same way.
        """
        timer.stop_timer()
        metrics = adapter_metrics if adapter_metrics is not None else RunMetrics()
        if metrics.duration is None:
            metrics.duration = timer.duration
        if metrics.time_to_first_token is None:
            metrics.time_to_first_token = timer.time_to_first_token
        return metrics

    @staticmethod
    def _update_session_metrics(session: AgentSession, run_output: RunOutput) -> None:
        """Add a completed run's metrics to the session totals AgentOS reads from session_data."""
        if run_output.metrics is None or run_output.status != RunStatus.completed:
            return
        if session.session_data is None:
            session.session_data = {}
        stored = session.session_data.get("session_metrics")
        session_metrics = SessionMetrics.from_dict(stored) if isinstance(stored, dict) else SessionMetrics()
        session_metrics.accumulate_from_run(run_output.metrics)
        session.session_data["session_metrics"] = session_metrics.to_dict()

    def _finish_run_output(
        self, run: RunOutput, run_state: Dict[str, Any], continuation: Optional[ExternalContinuation]
    ) -> None:
        """Prepend a continuation's kept transcript, then let the adapter annotate messages."""
        if continuation is not None:
            run.messages = continuation.messages + (run.messages or [])
            run.tools = (continuation.tools or []) + (run.tools or []) or None
            run.input = continuation.source_input
            run.forked_from_run_id = continuation.forked_from_run_id
            run.forked_from_message_index = continuation.forked_from_message_index
        self._annotate_run_output(run, run_state)

    def _annotate_run_output(self, run: RunOutput, run_state: Dict[str, Any]) -> None:
        """Attach adapter-specific per-message data recorded in run_state during the run."""

    def _get_history_from_session(
        self, session: AgentSession, exclude_run_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Extract conversation history from session runs for adapters to use.

        Includes user, assistant, and tool messages so adapters have full
        context of prior turns including tool call results.

        Each entry has:
        - role: "user", "assistant", or "tool"
        - content: message text
        - tool_calls: (assistant only) list of tool call dicts if present
        - tool_call_id: (tool only) ID linking to the assistant's tool_call
        """
        history: List[Dict[str, Any]] = []
        for run in session_branch(session.runs, exclude_run_id=exclude_run_id):
            for msg in run.messages or []:
                if msg.role == "assistant" and msg.tool_calls:
                    # Assistant message with tool calls (no text content)
                    history.append(
                        {
                            "role": "assistant",
                            "content": str(msg.content) if msg.content else "",
                            "tool_calls": msg.tool_calls,
                        }
                    )
                elif msg.role == "tool" and msg.content:
                    history.append(
                        {
                            "role": "tool",
                            "content": str(msg.content),
                            "tool_call_id": msg.tool_call_id or "",
                        }
                    )
                elif msg.role in ("user", "assistant") and msg.content:
                    history.append({"role": msg.role, "content": str(msg.content)})
        return history

    @staticmethod
    def _truncate_tool_result(result: str) -> str:
        """Shorten a replayed tool result but keep its end, where the exit status lives."""
        if len(result) <= _HISTORY_TOOL_RESULT_MAX_CHARS:
            return result
        head = result[: _HISTORY_TOOL_RESULT_MAX_CHARS - _HISTORY_TOOL_RESULT_TAIL_CHARS]
        tail = result[-_HISTORY_TOOL_RESULT_TAIL_CHARS:]
        omitted = len(result) - len(head) - len(tail)
        return f"{head}\n[... {omitted} characters truncated ...]\n{tail}"

    @staticmethod
    def _history_lines(message: Dict[str, Any]) -> List[str]:
        """Render one history entry: text, tool calls with their arguments, or a tool result."""
        role = message.get("role")
        content = message.get("content")
        lines: List[str] = []
        if role == "assistant" and message.get("tool_calls"):
            if content:
                lines.append(f"assistant: {content}")
            for tool_call in message["tool_calls"]:
                function = tool_call.get("function") or {}
                lines.append(f"assistant called {function.get('name') or 'tool'}({function.get('arguments') or ''})")
        elif role == "tool" and content:
            lines.append(f"tool result: {BaseExternalAgent._truncate_tool_result(str(content))}")
        elif role in ("user", "assistant") and content:
            lines.append(f"{role}: {content}")
        return lines

    def _check_native_resume(self, native_id: Optional[str], session: Optional[AgentSession]) -> None:
        if self.require_native_resume and not native_id and session is not None:
            if any(run.status == RunStatus.completed for run in session.runs or []):
                raise ValueError("Native conversation identity is missing; restore its checkpoint before continuing")

    @staticmethod
    def _input_text(input: Any) -> Any:
        """Text for input a team hands over as a Message or a list of them.

        A team leader delegates a task string, but with determine_input_for_members=False it
        forwards the team's own input, which can be a Message or a list of messages. The
        harnesses take text, so each message becomes its role and content. Anything else,
        including a plain string or a list of content blocks, is returned unchanged.
        """
        if isinstance(input, Message):
            return input.get_content_string()
        if not isinstance(input, list) or not input:
            return input
        lines: List[str] = []
        for item in input:
            role: str
            content: str
            if isinstance(item, Message):
                role, content = item.role, item.get_content_string() if item.content else ""
            elif isinstance(item, dict) and isinstance(item.get("role"), str):
                raw = item.get("content")
                role, content = item["role"], raw if isinstance(raw, str) else ("" if raw is None else str(raw))
            else:
                return input
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _build_prompt(input: Any, history: Optional[List[Dict[str, Any]]], resumed: bool) -> str:
        """Plain prompt when the framework's own session carries the context; otherwise
        prepend the persisted chat history so a fresh session does not lose it.

        Tool calls and results are replayed too, since for a coding harness they are most of
        what happened. The replay is bounded: long tool results are shortened and, past a
        total budget, the oldest entries are dropped.
        """
        text = str(input)
        if resumed or not history:
            return text
        rendered = [BaseExternalAgent._history_lines(message) for message in history]
        kept: List[List[str]] = []
        budget = _HISTORY_MAX_CHARS
        for lines in reversed(rendered):
            if not lines:
                continue
            size = sum(len(line) + 1 for line in lines)
            if size > budget:
                break
            budget -= size
            kept.append(lines)
        if not kept:
            return text
        kept.reverse()
        prompt_lines = ["Previous conversation (for context, do not repeat it):"]
        if len(kept) < sum(1 for lines in rendered if lines):
            prompt_lines.append("[earlier history omitted]")
        for lines in kept:
            prompt_lines.extend(lines)
        prompt_lines.extend(["", "Current message:", text])
        return "\n".join(prompt_lines)

    # ---------------------------------------------------------------------------
    # Internal: non-streaming
    # ---------------------------------------------------------------------------

    async def _arun_non_stream(self, input: Any, **kwargs: Any) -> RunOutput:
        if self._uses_native_hitl:
            events = self._arun_stream(input, **{**kwargs, "yield_run_output": True, "_native_non_stream": True})
            try:
                async for item in events:
                    if isinstance(item, RunOutput):
                        return item
            finally:
                await events.aclose()  # type: ignore[attr-defined]
            raise RuntimeError("Paused native run produced no result")
        team_id, workflow_id = self._pop_run_parent(kwargs)
        parent_id = self._parent_id(team_id, workflow_id)
        if self.sandbox is not None:
            if parent_id is None:
                return await _sandbox_harness().arun(self, input, **kwargs)
            from agno.run.cancel import acleanup_member_runs, aregister_member_run

            team_session_id = kwargs.get("session_id") or str(uuid4())
            member_run_id = kwargs.get("run_id") or str(uuid4())
            text = self._input_text(input)
            try:
                forwarded = self._sandboxed_member_kwargs(kwargs, team_session_id, member_run_id, team_id, workflow_id)
                # Cancelling the member run the team registered reaches the sandbox's run through this link.
                await aregister_member_run(member_run_id, forwarded["run_id"])
                try:
                    await self._araise_if_member_cancelled(member_run_id)
                    run = await _sandbox_harness().arun(self, text, **forwarded)
                finally:
                    await acleanup_member_runs(member_run_id)
            except Exception as error:
                return self._sandboxed_member_failure(error, team_session_id, member_run_id, text, kwargs)
            return self._as_team_member_output(run, team_session_id, member_run_id, forwarded["run_id"])
        run_id = kwargs.pop("run_id", None) or str(uuid4())
        session_id = kwargs.get("session_id") or str(uuid4())
        kwargs["session_id"] = session_id
        user_id = kwargs.get("user_id")
        continuation: Optional[ExternalContinuation] = kwargs.get("continuation")
        # Convert before claiming the session, so the stored input is the text the agent received
        # and nothing between the claim and the try below can leave the session claimed.
        input = self._input_text(input)
        record_input = input if continuation is None else continuation.record_input
        output_schema = self._resolve_output_schema(kwargs)
        run_state: Dict[str, Any] = {}
        state_session_id = self._state_session_id(session_id, parent_id)
        session = (
            await self.aread_or_create_session(state_session_id, user_id, team_id, workflow_id) if self.db else None
        )
        self._claim_session(session, state_session_id, run_id)
        try:
            history = (
                self._get_history_from_session(session, exclude_run_id=run_id) if session and not continuation else None
            )
            # Tool calls from attempts that failed; they ran, so the stored run keeps them.
            carried_tools: Dict[str, ToolExecution] = {}
            attempts_made = 0
            timer = RunMetrics()
            timer.start_timer()
            try:
                async with self._run_cancellation(run_id):
                    num_attempts = self.retries + 1
                    for attempt in range(num_attempts):
                        attempts_made = attempt + 1
                        try:
                            content = await self._arun_adapter(
                                input, history=history, run_id=run_id, session=session, run_state=run_state, **kwargs
                            )
                            break
                        except RunCancelledException:
                            raise
                        except Exception as error:
                            self._collect_attempt_tools(run_state, carried_tools)
                            if not self._should_retry(error, attempt, num_attempts):
                                raise
                            await self._await_retry(run_id, attempt, num_attempts, error)
                run_output = self._build_run_output(
                    run_id,
                    session_id,
                    user_id,
                    record_input,
                    content.content if isinstance(content, ExternalRunResult) else content,
                    RunStatus.completed,
                    tools=self._merge_tools(
                        carried_tools, content.tools if isinstance(content, ExternalRunResult) else None
                    ),
                    metrics=self._finish_metrics(
                        timer, content.metrics if isinstance(content, ExternalRunResult) else None
                    ),
                    media=kwargs.get("media"),
                )
                if isinstance(content, ExternalRunResult) and content.warnings:
                    run_output.metadata = {"warnings": content.warnings}
                self._apply_output_schema(
                    run_output,
                    output_schema,
                    content.structured_output if isinstance(content, ExternalRunResult) else None,
                )
            except RunCancelledException:
                # Cancelled mid-attempt or during a retry backoff: the tools that completed ran. A
                # failed attempt's tools were already moved into carried_tools before the backoff.
                self._collect_attempt_tools(run_state, carried_tools)
                run_output = self._build_run_output(
                    run_id,
                    session_id,
                    user_id,
                    record_input,
                    "Run cancelled",
                    RunStatus.cancelled,
                    tools=list(carried_tools.values()) or None,
                    media=kwargs.get("media"),
                )
            except Exception as error:
                log_exception(f"Error in {self.sdk} agent '{self.id}': {error}")
                run_output = self._build_run_output(
                    run_id,
                    session_id,
                    user_id,
                    record_input,
                    str(error),
                    RunStatus.error,
                    tools=list(carried_tools.values()) or None,
                    media=kwargs.get("media"),
                )
                run_output.metadata = self._failure_metadata(error)
            if attempts_made > 1:
                run_output.metadata = {**(run_output.metadata or {}), "attempts": attempts_made}
            self._finish_run_output(run_output, run_state, continuation)
            if session is not None and parent_id is not None:
                await self._apersist_member_state(session)
            elif session is not None:
                await self._apersist_run_in_session(session, run_output)
            return run_output
        finally:
            self._release_session(state_session_id, run_id)

    async def _native_non_stream_events(self, input: Any, **kwargs: Any) -> AsyncIterator[Any]:
        """Keep the adapter's nonstreaming result contract while multiplexing permission events."""
        result = await self._arun_adapter(input, **kwargs)
        if isinstance(result, ExternalRunResult):
            for tool in result.tools or []:
                yield ToolCallCompletedEvent(tool=tool)
            for warning in result.warnings or []:
                yield ExternalRunWarningEvent(warning=warning)
            if result.metrics is not None:
                yield ExternalRunMetricsEvent(metrics=result.metrics)
            if result.structured_output is not None:
                yield ExternalRunStructuredOutputEvent(structured_output=result.structured_output)
            yield RunContentEvent(content=result.content)
        else:
            yield RunContentEvent(content=result)

    async def _arun_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[Any]:
        native_non_stream = kwargs.pop("_native_non_stream", False)
        team_id, workflow_id = self._pop_run_parent(kwargs)
        parent_id = self._parent_id(team_id, workflow_id)
        if self.sandbox is not None:
            if parent_id is None:
                events = _sandbox_harness().astream(self, input, **kwargs)
                try:
                    async for item in events:
                        yield item
                finally:
                    await events.aclose()
                return
            from agno.run.cancel import acleanup_member_runs, aregister_member_run

            team_session_id = kwargs.get("session_id") or str(uuid4())
            member_run_id = kwargs.get("run_id") or str(uuid4())
            text = self._input_text(input)
            failure: Optional[Exception] = None
            try:
                forwarded = self._sandboxed_member_kwargs(kwargs, team_session_id, member_run_id, team_id, workflow_id)
                await aregister_member_run(member_run_id, forwarded["run_id"])
            except Exception as error:
                failure = error
            if failure is None:
                try:
                    await self._araise_if_member_cancelled(member_run_id)
                    events = _sandbox_harness().astream(self, text, **forwarded)
                    try:
                        async for item in events:
                            yield self._as_team_member_output(item, team_session_id, member_run_id, forwarded["run_id"])
                    finally:
                        await events.aclose()
                except Exception as error:
                    failure = error
                finally:
                    await acleanup_member_runs(member_run_id)
            if failure is not None:
                failed = self._sandboxed_member_failure(failure, team_session_id, member_run_id, text, kwargs)
                yield self._terminal_event_for(failed)
                if kwargs.get("yield_run_output", False):
                    yield failed
            return
        run_id = kwargs.pop("run_id", None) or str(uuid4())
        session_id = kwargs.get("session_id") or str(uuid4())
        kwargs["session_id"] = session_id
        user_id = kwargs.get("user_id")
        yield_run_output = kwargs.pop("yield_run_output", False)
        continuation: Optional[ExternalContinuation] = kwargs.get("continuation")
        # Convert before claiming the session, as in the non-streaming path.
        input = self._input_text(input)
        output_schema = self._resolve_output_schema(kwargs)
        run_state: Dict[str, Any] = {}
        state_session_id = self._state_session_id(session_id, parent_id)
        session = (
            await self.aread_or_create_session(state_session_id, user_id, team_id, workflow_id) if self.db else None
        )
        self._claim_session(session, state_session_id, run_id)
        try:
            history = (
                self._get_history_from_session(session, exclude_run_id=run_id) if session and not continuation else None
            )
            stored_events: Optional[List[Any]] = [] if self.store_events or self._uses_native_hitl else None
            skipped = {event.value for event in self.events_to_skip or []}

            def keep(event: Any) -> Any:
                # Record an event on the run before it is yielded, unless the agent skips its kind.
                if stored_events is not None and getattr(event, "event", None) not in skipped:
                    stored_events.append(event)
                return event

            yield keep(
                RunStartedEvent(
                    run_id=run_id, agent_id=self.get_id(), agent_name=self.name or "", session_id=session_id
                )
            )
            accumulated_content = ""
            warnings: List[Dict[str, Any]] = []
            tools: Dict[str, ToolExecution] = {}
            bridge = None
            if self._uses_native_hitl:
                from agno.agents._hitl import HITLBridge, validate_native_hitl

                validate_native_hitl(self)
                allow_requests = parent_id is None and not getattr(self, "_nested_native_hitl", False)
                bridge = HITLBridge(self, run_id, session_id, user_id, allow_requests=allow_requests)
            status = RunStatus.completed
            run_error: Optional[Exception] = None
            attempts_made = 0
            adapter_metrics: Optional[RunMetrics] = None
            structured_output: Any = None
            timer = RunMetrics()
            timer.start_timer()
            try:
                async with self._run_cancellation(run_id):
                    num_attempts = self.retries + 1
                    for attempt in range(num_attempts):
                        attempts_made = attempt + 1
                        # Content is the final attempt's answer; tool calls from every attempt ran, so they are kept.
                        accumulated_content = ""
                        adapter_metrics = None
                        structured_output = None
                        try:
                            adapter = self._arun_adapter_stream
                            if native_non_stream and type(self)._arun_adapter is not BaseExternalAgent._arun_adapter:
                                adapter = self._native_non_stream_events
                            source = adapter(
                                input, history=history, run_id=run_id, session=session, run_state=run_state, **kwargs
                            )
                            if bridge is not None:
                                if bridge.closed:
                                    bridge = HITLBridge(
                                        self, run_id, session_id, user_id, allow_requests=allow_requests
                                    )
                                source = bridge.events(source)
                            try:
                                async for event in source:
                                    if isinstance(event, ExternalRunMetricsEvent):
                                        adapter_metrics = event.metrics
                                        continue
                                    if isinstance(event, ExternalRunStructuredOutputEvent):
                                        structured_output = event.structured_output
                                        continue
                                    if isinstance(event, ExternalRunWarningEvent) and event.warning is not None:
                                        warnings.append(event.warning)
                                    if isinstance(event, RunContentEvent):
                                        if event.content:
                                            timer.set_time_to_first_token()
                                        accumulated_content += event.content or ""
                                    elif (
                                        isinstance(event, (ToolCallStartedEvent, ToolCallCompletedEvent)) and event.tool
                                    ):
                                        key = event.tool.tool_call_id or str(uuid4())
                                        if key not in tools:
                                            tools[key] = copy(event.tool)
                                        elif isinstance(event, ToolCallCompletedEvent):
                                            tools[key].result = event.tool.result
                                            tools[key].tool_call_error = event.tool.tool_call_error
                                    if isinstance(event, (RunPausedEvent, RunContinuedEvent)) and bridge is not None:
                                        if isinstance(event, RunPausedEvent):
                                            for tool in event.tools or []:
                                                tools[tool.tool_call_id or ""] = tool
                                        from agno.agents._hitl import KEY as native_key

                                        # The paused run is the shared state: its requirements are what the
                                        # chat confirms, and its metadata is how the continuation finds them.
                                        snapshot = self._build_run_output(
                                            run_id,
                                            session_id,
                                            user_id,
                                            input,
                                            accumulated_content,
                                            RunStatus.paused if bridge.pending else RunStatus.running,
                                            list(tools.values()) or None,
                                        )
                                        snapshot.requirements = bridge.pending_requirements()
                                        snapshot.metadata = {native_key: bridge.state()}
                                        if isinstance(event, RunPausedEvent):
                                            event.content = accumulated_content
                                            event.tools = list(tools.values())
                                        keep(event)
                                        snapshot.events = list(stored_events or [])
                                        if session is not None:
                                            await self._apersist_run_in_session(session, snapshot, strict=True)
                                        yield event
                                    else:
                                        yield keep(event)
                            finally:
                                if bridge is not None:
                                    await source.aclose()  # type: ignore[attr-defined]
                            break
                        except RunCancelledException:
                            raise
                        except Exception as error:
                            if native_non_stream:
                                self._collect_attempt_tools(run_state, tools)
                            if (bridge is not None and bridge.requests) or not self._should_retry(
                                error, attempt, num_attempts
                            ):
                                raise
                            # The failed attempt's events already reached the consumer. Say so before
                            # the retry streams a fresh answer, and keep it in the stored run's warnings.
                            warning = self._retry_warning(attempt, num_attempts, error)
                            warnings.append(warning)
                            yield keep(ExternalRunWarningEvent(run_id=run_id, agent_id=self.get_id(), warning=warning))
                            await self._await_retry(run_id, attempt, num_attempts, error)
            except RunCancelledException:
                status = RunStatus.cancelled
            except Exception as error:
                log_exception(f"Error in {self.sdk} agent '{self.id}': {error}")
                run_error = error
                status = RunStatus.error
            run = self._build_run_output(
                run_id,
                session_id,
                user_id,
                input if continuation is None else continuation.record_input,
                str(run_error) if run_error else accumulated_content,
                status,
                list(tools.values()) or None,
                metrics=self._finish_metrics(timer, adapter_metrics) if status == RunStatus.completed else None,
                media=kwargs.get("media"),
            )
            if warnings:
                run.metadata = {"warnings": warnings}
            if run_error is not None:
                run.metadata = {**(run.metadata or {}), **self._failure_metadata(run_error)}
            if attempts_made > 1:
                run.metadata = {**(run.metadata or {}), "attempts": attempts_made}
            if bridge is not None and bridge.requests:
                from agno.agents._hitl import KEY as native_key

                run.metadata = {**(run.metadata or {}), native_key: {**bridge.state(), "pending": []}}
                if run_error is not None:
                    run.metadata["retryable"] = False
            self._apply_output_schema(run, output_schema, structured_output)
            self._finish_run_output(run, run_state, continuation)
            fields: Dict[str, Any] = dict(
                run_id=run_id,
                session_id=session_id,
                agent_id=self.get_id(),
                agent_name=self.name or "",
                content=run.content,
            )
            # The terminal event is built before the run is persisted so the stored run ends with it,
            # which is what a replay from the database needs to know the run is over.
            terminal: Any
            if status == RunStatus.cancelled:
                terminal = RunCancelledEvent(
                    run_id=run_id, session_id=session_id, agent_id=self.get_id(), reason="Run cancelled"
                )
            elif run_error is not None:
                terminal = RunErrorEvent(**fields, error_type=error_type_of(run_error))
            else:
                terminal = RunCompletedEvent(**fields, content_type=run.content_type, metrics=run.metrics)
            keep(terminal)
            if stored_events is not None:
                run.events = list(stored_events)
            if session is not None and parent_id is not None:
                await self._apersist_member_state(session)
            elif session is not None:
                await self._apersist_run_in_session(session, run, strict=bridge is not None)
            yield terminal
            if (
                stored_events is not None
                and session is not None
                and parent_id is None
                and getattr(terminal, "event_index", None) is not None
            ):
                # The consumer stamped the terminal event with its stream index while we were suspended
                # on the yield (the event stream writes it on the object). Write the row again so the
                # stored event carries that index and a replay from the database stays in order.
                await self._arewrite_run_row(session, run)
            if yield_run_output:
                yield run
        finally:
            self._release_session(state_session_id, run_id)

    def _run_stream(self, input: Any, **kwargs: Any) -> Iterator[Union[RunOutputEvent, RunOutput]]:
        """Sync streaming wrapper. Runs the async stream on a background thread."""
        import queue
        import threading

        event_queue: queue.Queue = queue.Queue()
        _sentinel = object()
        thread_error: List[BaseException] = []

        def _run_async():
            async def _produce():
                async for event in self._arun_stream(input, **kwargs):
                    event_queue.put(event)

            # Sentinel goes out in finally so the consumer never blocks forever, even
            # if anything above _arun_stream's own try/except raises (e.g. db load).
            try:
                asyncio.run(_produce())
            except BaseException as e:
                thread_error.append(e)
            finally:
                event_queue.put(_sentinel)

        thread = threading.Thread(target=_run_async, daemon=True)
        thread.start()

        while True:
            item = event_queue.get()
            if item is _sentinel:
                break
            yield item

        thread.join()
        if thread_error:
            raise thread_error[0]

    # ---------------------------------------------------------------------------
    # Subclass hooks (must be implemented by adapters)
    # ---------------------------------------------------------------------------

    async def _arun_adapter(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> Union[str, ExternalRunResult]:
        """Non-streaming execution. Return content and optional tool executions.

        kwargs includes `session` (the loaded AgentSession, or None if no db).
        Mutate `session.session_data` in place to persist adapter-specific
        per-session state — the base class upserts the session after this
        returns, so no separate DB write is needed.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement _arun_adapter")

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming execution. Yield RunContentEvent, ToolCallStartedEvent, etc.

        Do NOT yield RunStartedEvent or RunCompletedEvent -- those are handled by the base class.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement _arun_adapter_stream")
        yield  # type: ignore  # make this a generator
