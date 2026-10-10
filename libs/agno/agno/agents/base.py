import asyncio
import json
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, List, Optional, Sequence, Union
from uuid import uuid4

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.exceptions import RunCancelledException
from agno.media import Audio, File, Image, Video
from agno.metrics import BaseMetrics, ModelMetrics, RunMetrics, SessionMetrics
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import (
    CustomEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunEvent,
    RunInput,
    RunOutput,
    RunOutputEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from agno.utils.events import error_type_of
from agno.utils.log import log_exception, log_warning

if TYPE_CHECKING:
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


@dataclass
class ExternalRunWarningEvent(CustomEvent):
    """Nonfatal adapter warning emitted to streaming consumers."""

    warning: Optional[Dict[str, Any]] = None


@dataclass
class ExternalRunMetricsEvent(CustomEvent):
    """Token usage and cost reported by a streaming adapter; consumed by the base, not forwarded."""

    metrics: Optional[RunMetrics] = None


@dataclass
class ExternalRunResult:
    """Adapter output with tool executions retained for session history."""

    content: str
    tools: Optional[List[ToolExecution]] = None
    warnings: Optional[List[Dict[str, Any]]] = None
    metrics: Optional[RunMetrics] = None


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


@dataclass
class BaseExternalAgent:
    """Base class for external framework adapters.

    Structurally satisfies the AgentProtocol (agno.agent.protocol) — any subclass
    that implements the two hooks below will automatically be compatible with
    AgentOS routing, SSE streaming, and the agent os.

    Provides shared infrastructure for:
    - ID and name management
    - Run lifecycle event emission (RunStarted, RunCompleted, RunError)
    - Tool call event wrapping
    - Sync/async run and print_response methods
    - Session persistence via Agno's DB (when db is configured)

    Subclasses must implement:
    - _arun_adapter(input, **kwargs) -> str | ExternalRunResult  (non-streaming)
    - _arun_adapter_stream(input, **kwargs) -> AsyncIterator[RunOutputEvent]  (streaming)
    """

    name: Optional[str] = None
    id: Optional[str] = None
    description: Optional[str] = None
    framework: str = "external"
    markdown: bool = True
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None

    def __post_init__(self) -> None:
        from agno.utils.string import generate_id_from_name

        if self.id is None:
            self.id = generate_id_from_name(self.name)

    def get_id(self) -> str:
        """Return the agent ID, guaranteed non-None after __post_init__."""
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
        background: bool = False,
        run_id: Optional[str] = None,
        yield_run_output: bool = False,
        **kwargs: Any,
    ) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]:
        run_id = run_id or str(uuid4())
        session_id = session_id or str(uuid4())
        kwargs.update(run_id=run_id, session_id=session_id, user_id=user_id)
        if background:
            if self.db is None:
                raise ValueError("Background execution requires a database")
            if stream:
                return self._arun_background_stream(input, yield_run_output=yield_run_output, **kwargs)
            return self._astart_background(input, stream=False, yield_run_output=yield_run_output, **kwargs)  # type: ignore[return-value]
        if stream:
            return self._arun_stream(input, yield_run_output=yield_run_output, **kwargs)
        return self._arun_non_stream(input, **kwargs)  # type: ignore[return-value]

    # ---------------------------------------------------------------------------
    # Public sync API (convenience wrappers)
    # ---------------------------------------------------------------------------

    def run(
        self,
        input: Any,
        *,
        stream: bool = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Union[RunOutput, Iterator[RunOutputEvent]]:
        """Synchronous run. Dispatches to the async internals."""
        if kwargs.pop("background", False):
            raise ValueError("Use arun(background=True) on a persistent event loop")
        if stream:
            return self._run_stream(input, session_id=session_id, user_id=user_id, **kwargs)
        else:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        self._arun_non_stream(input, session_id=session_id, user_id=user_id, **kwargs),
                    ).result()
                return result
            else:
                return asyncio.run(self._arun_non_stream(input, session_id=session_id, user_id=user_id, **kwargs))

    def print_response(
        self,
        input: Any,
        *,
        stream: bool = True,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        markdown: Optional[bool] = None,
        show_message: bool = True,
        **kwargs: Any,
    ) -> None:
        """Print agent response to terminal with Rich formatting."""
        from rich.console import Console, Group
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel, format_tool_calls

        console = Console()
        use_markdown = markdown if markdown is not None else self.markdown
        accumulated_tool_calls: List[ToolExecution] = []

        if stream:
            _response_content: str = ""

            with Live(console=console) as live_log:
                status = Status("Working...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
                live_log.update(status)

                panels: list = [status]
                if show_message and input is not None:
                    message_panel = create_panel(
                        content=Text(str(input), style="green"),
                        title="Message",
                        border_style="cyan",
                    )
                    panels.append(message_panel)
                    live_log.update(Group(*panels))

                for event in self.run(input=input, stream=True, session_id=session_id, user_id=user_id, **kwargs):  # type: ignore[union-attr]
                    if event.event == RunEvent.run_content.value:  # type: ignore
                        if hasattr(event, "content") and isinstance(event.content, str):
                            _response_content += event.content

                    if (
                        event.event == RunEvent.tool_call_started.value
                        and hasattr(event, "tool")
                        and event.tool is not None
                    ):  # type: ignore
                        accumulated_tool_calls.append(event.tool)  # type: ignore

                    # Rebuild panels
                    panels = [status]
                    if show_message and input is not None:
                        message_panel = create_panel(
                            content=Text(str(input), style="green"),
                            title="Message",
                            border_style="cyan",
                        )
                        panels.append(message_panel)

                    if accumulated_tool_calls:
                        formatted = format_tool_calls(accumulated_tool_calls)
                        tool_text = Text("\n".join(f" - {tc}" for tc in formatted))
                        tool_panel = create_panel(content=tool_text, title="Tool Calls", border_style="yellow")
                        panels.append(tool_panel)

                    if _response_content:
                        if use_markdown:
                            content_renderable: Any = Markdown(_response_content)
                        else:
                            content_renderable = Text(_response_content)
                        response_panel = create_panel(
                            content=content_renderable,
                            title=f"Response ({self.framework}:{self.name})",
                            border_style="blue",
                        )
                        panels.append(response_panel)

                    live_log.update(Group(*panels))

                # Final update: remove spinner
                panels = [p for p in panels if not isinstance(p, Status)]
                live_log.update(Group(*panels))
        else:
            run_output = self.run(input=input, stream=False, session_id=session_id, user_id=user_id, **kwargs)
            assert isinstance(run_output, RunOutput)

            panels = []
            if show_message and input is not None:
                message_panel = create_panel(
                    content=Text(str(input), style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)

            if run_output.tools:
                formatted = format_tool_calls(run_output.tools)
                tool_text = Text("\n".join(f" - {tc}" for tc in formatted))
                tool_panel = create_panel(content=tool_text, title="Tool Calls", border_style="yellow")
                panels.append(tool_panel)

            content = run_output.content or ""
            if use_markdown and isinstance(content, str):
                content_renderable = Markdown(content)
            elif isinstance(content, str):
                content_renderable = Text(content)
            else:
                content_renderable = Text(str(content))

            response_panel = create_panel(
                content=content_renderable,
                title=f"Response ({self.framework}:{self.name})",
                border_style="blue",
            )
            panels.append(response_panel)
            console.print(Group(*panels))

    async def aprint_response(
        self,
        input: Any,
        *,
        stream: bool = True,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        markdown: Optional[bool] = None,
        show_message: bool = True,
        **kwargs: Any,
    ) -> None:
        """Async version of print_response."""
        from rich.console import Console, Group
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel, format_tool_calls

        console = Console()
        use_markdown = markdown if markdown is not None else self.markdown
        accumulated_tool_calls: List[ToolExecution] = []

        if stream:
            _response_content: str = ""

            with Live(console=console) as live_log:
                status = Status("Working...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
                live_log.update(status)

                panels: list = [status]
                if show_message and input is not None:
                    message_panel = create_panel(
                        content=Text(str(input), style="green"),
                        title="Message",
                        border_style="cyan",
                    )
                    panels.append(message_panel)
                    live_log.update(Group(*panels))

                async for event in self._arun_stream(input, session_id=session_id, user_id=user_id, **kwargs):
                    if event.event == RunEvent.run_content.value:  # type: ignore
                        if hasattr(event, "content") and isinstance(event.content, str):
                            _response_content += event.content

                    if (
                        event.event == RunEvent.tool_call_started.value
                        and hasattr(event, "tool")
                        and event.tool is not None
                    ):  # type: ignore
                        accumulated_tool_calls.append(event.tool)  # type: ignore

                    panels = [status]
                    if show_message and input is not None:
                        message_panel = create_panel(
                            content=Text(str(input), style="green"),
                            title="Message",
                            border_style="cyan",
                        )
                        panels.append(message_panel)

                    if accumulated_tool_calls:
                        formatted = format_tool_calls(accumulated_tool_calls)
                        tool_text = Text("\n".join(f" - {tc}" for tc in formatted))
                        tool_panel = create_panel(content=tool_text, title="Tool Calls", border_style="yellow")
                        panels.append(tool_panel)

                    if _response_content:
                        if use_markdown:
                            content_renderable: Any = Markdown(_response_content)
                        else:
                            content_renderable = Text(_response_content)
                        response_panel = create_panel(
                            content=content_renderable,
                            title=f"Response ({self.framework}:{self.name})",
                            border_style="blue",
                        )
                        panels.append(response_panel)

                    live_log.update(Group(*panels))

                panels = [p for p in panels if not isinstance(p, Status)]
                live_log.update(Group(*panels))
        else:
            run_output = await self._arun_non_stream(input, session_id=session_id, user_id=user_id, **kwargs)

            panels = []
            if show_message and input is not None:
                message_panel = create_panel(
                    content=Text(str(input), style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)

            if run_output.tools:
                formatted = format_tool_calls(run_output.tools)
                tool_text = Text("\n".join(f" - {tc}" for tc in formatted))
                tool_panel = create_panel(content=tool_text, title="Tool Calls", border_style="yellow")
                panels.append(tool_panel)

            content = run_output.content or ""
            if use_markdown and isinstance(content, str):
                content_renderable = Markdown(content)
            elif isinstance(content, str):
                content_renderable = Text(content)
            else:
                content_renderable = Text(str(content))

            response_panel = create_panel(
                content=content_renderable,
                title=f"Response ({self.framework}:{self.name})",
                border_style="blue",
            )
            panels.append(response_panel)
            console.print(Group(*panels))

    # ---------------------------------------------------------------------------
    # Session persistence helpers
    # ---------------------------------------------------------------------------

    def _create_session(self, session_id: str, user_id: Optional[str] = None) -> AgentSession:
        """Create a new AgentSession."""
        return AgentSession(
            session_id=session_id,
            agent_id=self.get_id(),
            user_id=user_id,
            session_data={},
            agent_data={"agent_id": self.id, "agent_name": self.name, "framework": self.framework},
            metadata={},
            runs=[],
            created_at=int(time()),
        )

    def _owned_session_or_new(self, row: Any, session_id: str, user_id: Optional[str]) -> AgentSession:
        """The stored session, claimed by the caller when unowned, or a new one. Refuses one the caller cannot access."""
        from agno.session.sharing import can_run_in_session

        session = AgentSession.from_dict(row) if isinstance(row, dict) else row
        if not isinstance(session, AgentSession):
            return self._create_session(session_id, user_id)
        if not can_run_in_session(session, user_id):
            # Writing here would add this run to another user's history.
            raise ValueError(f"Session {session_id} belongs to another user")
        if session.user_id is None and user_id is not None:
            session.user_id = user_id
        return session

    def read_or_create_session(self, session_id: str, user_id: Optional[str] = None) -> AgentSession:
        """Read a session from the DB, or create a new one. Refuses a session owned by another user."""
        row = None
        if self.db is not None and isinstance(self.db, BaseDb):
            row = self.db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        return self._owned_session_or_new(row, session_id, user_id)

    async def aread_or_create_session(self, session_id: str, user_id: Optional[str] = None) -> AgentSession:
        """Async read a session from the DB, or create a new one. Refuses a session owned by another user."""
        row = None
        if self.db is not None:
            if isinstance(self.db, AsyncBaseDb):
                row = await self.db.get_session(session_id=session_id, session_type=SessionType.AGENT)
            elif isinstance(self.db, BaseDb):
                row = self.db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        return self._owned_session_or_new(row, session_id, user_id)

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
                    # Adapter not ported to v3 storage; runs persist inline via upsert_session
                    pass
        except Exception as upsert_err:
            log_warning(f"Failed to persist run for {self.framework} agent '{self.id}': {upsert_err}")
            if strict or worker_owned:
                raise

    def _visible_session(self, row: Any, user_id: Optional[str]) -> Optional[AgentSession]:
        from agno.session.sharing import can_read_session

        session = AgentSession.from_dict(row) if isinstance(row, dict) else row
        if not isinstance(session, AgentSession) or session.agent_id != self.get_id():
            return None
        return session if can_read_session(session, user_id) else None

    def get_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[AgentSession]:
        """Read a session scoped to this agent; with user_id, only one that user owns or is shared with."""
        if self.db is None:
            return None
        if isinstance(self.db, AsyncBaseDb):
            raise ValueError("Use aget_session with an async database")
        row = self.db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        return self._visible_session(row, user_id)

    async def aget_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[AgentSession]:
        """Read a persisted session without creating a missing session."""
        if self.db is None:
            return None
        if isinstance(self.db, BaseDb):
            # Match the synchronous persistence path, including thread-local in-memory SQLite.
            return self.get_session(session_id, user_id)
        row = await self.db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        return self._visible_session(row, user_id)

    def cancel_run(self, run_id: str) -> bool:
        """Store cancellation intent and interrupt a live local SDK handle."""
        from agno.run.cancel import cancel_run

        registered = cancel_run(run_id)
        live = _live_handles.get(run_id)
        if live is not None and not live.loop.is_closed():
            asyncio.run_coroutine_threadsafe(live.agent._ainterrupt_live_handle(run_id), live.loop)
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
        return registered

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

    async def _aprepare_pending_run(
        self, run_id: str, session_id: str, user_id: Optional[str], input: Any
    ) -> RunOutput:
        """Persist an idempotent PENDING row before background or queued execution."""
        from agno.os.job_queue import _aappend_pending_run

        run = RunOutput(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            agent_id=self.get_id(),
            agent_name=self.name,
            input=RunInput(input_content=input),
            status=RunStatus.pending,
        )
        # Check ownership first: the atomic append does not, and would add the run to another user's session.
        loaded = await self.aread_or_create_session(session_id, user_id)

        async def load_session() -> AgentSession:
            return loaded

        session = await _aappend_pending_run(self, session_id, run.to_dict(), user_id, load_session)
        if session is not None and session.get_run(run_id) is None:
            await self._apersist_run_in_session(session, run, strict=True)
        return run

    async def _apersist_run_fallback(
        self, session_id: str, run_response: RunOutput, user_id: Optional[str] = None
    ) -> None:
        """Re-read the session and persist one run; completed or cancelled rows win."""
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
        from agno.run.background import _BackgroundStream, _execute_background, _spawn_background
        from agno.run.cancel import aregister_run
        from agno.run.status_persist import apersist_run_transition

        run = await self._aprepare_pending_run(run_id, session_id, user_id, input)
        await aregister_run(run_id)
        transport = _BackgroundStream(run, yield_run_output=yield_run_output) if stream else None
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

        return RunOutput(
            run_id=run_id,
            agent_id=self.get_id(),
            agent_name=self.name,
            session_id=session_id,
            user_id=user_id,
            input=RunInput(input_content=str(input_text)) if input_text is not None else None,
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
        if not session.runs:
            return history
        # A fork already contains the retained prefix of its source run. Its
        # predecessor is the source's predecessor, not the most recent sibling.
        # Keep predecessor links so forks of older branches also discard any
        # intervening turns, without copying the entire history for every run.
        runs: List[RunOutput] = []
        predecessors: List[Optional[int]] = []
        indexes: Dict[str, int] = {}
        head: Optional[int] = None
        for run in session.runs:
            if not isinstance(run, RunOutput) or not run.messages or run.run_id == exclude_run_id:
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

        branch: List[RunOutput] = []
        while head is not None:
            branch.append(runs[head])
            head = predecessors[head]
        for run in reversed(branch):
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
        run_id = kwargs.pop("run_id", None) or str(uuid4())
        session_id = kwargs.get("session_id") or str(uuid4())
        kwargs["session_id"] = session_id
        user_id = kwargs.get("user_id")
        continuation: Optional[ExternalContinuation] = kwargs.get("continuation")
        record_input = input if continuation is None else continuation.record_input
        run_state: Dict[str, Any] = {}
        session = await self.aread_or_create_session(session_id, user_id) if self.db else None
        history = (
            self._get_history_from_session(session, exclude_run_id=run_id) if session and not continuation else None
        )
        timer = RunMetrics()
        timer.start_timer()
        try:
            async with self._run_cancellation(run_id):
                content = await self._arun_adapter(
                    input, history=history, run_id=run_id, session=session, run_state=run_state, **kwargs
                )
            run_output = self._build_run_output(
                run_id,
                session_id,
                user_id,
                record_input,
                content.content if isinstance(content, ExternalRunResult) else content,
                RunStatus.completed,
                tools=content.tools if isinstance(content, ExternalRunResult) else None,
                metrics=self._finish_metrics(
                    timer, content.metrics if isinstance(content, ExternalRunResult) else None
                ),
            )
            if isinstance(content, ExternalRunResult) and content.warnings:
                run_output.metadata = {"warnings": content.warnings}
        except RunCancelledException:
            run_output = self._build_run_output(
                run_id,
                session_id,
                user_id,
                record_input,
                "Run cancelled",
                RunStatus.cancelled,
                tools=list(run_state.get("tools", {}).values()) or None,
            )
        except Exception as error:
            log_exception(f"Error in {self.framework} agent '{self.id}': {error}")
            run_output = self._build_run_output(
                run_id,
                session_id,
                user_id,
                record_input,
                str(error),
                RunStatus.error,
                tools=list(run_state.get("tools", {}).values()) or None,
            )
        self._finish_run_output(run_output, run_state, continuation)
        if session is not None:
            await self._apersist_run_in_session(session, run_output)
        return run_output

    async def _arun_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[Any]:
        run_id = kwargs.pop("run_id", None) or str(uuid4())
        session_id = kwargs.get("session_id") or str(uuid4())
        kwargs["session_id"] = session_id
        user_id = kwargs.get("user_id")
        yield_run_output = kwargs.pop("yield_run_output", False)
        continuation: Optional[ExternalContinuation] = kwargs.get("continuation")
        run_state: Dict[str, Any] = {}
        session = await self.aread_or_create_session(session_id, user_id) if self.db else None
        history = (
            self._get_history_from_session(session, exclude_run_id=run_id) if session and not continuation else None
        )
        yield RunStartedEvent(run_id=run_id, agent_id=self.get_id(), agent_name=self.name or "", session_id=session_id)
        accumulated_content = ""
        warnings: List[Dict[str, Any]] = []
        tools: Dict[str, ToolExecution] = {}
        status = RunStatus.completed
        run_error: Optional[Exception] = None
        adapter_metrics: Optional[RunMetrics] = None
        timer = RunMetrics()
        timer.start_timer()
        try:
            async with self._run_cancellation(run_id):
                async for event in self._arun_adapter_stream(
                    input, history=history, run_id=run_id, session=session, run_state=run_state, **kwargs
                ):
                    if isinstance(event, ExternalRunMetricsEvent):
                        adapter_metrics = event.metrics
                        continue
                    if isinstance(event, ExternalRunWarningEvent) and event.warning is not None:
                        warnings.append(event.warning)
                    if isinstance(event, RunContentEvent):
                        if event.content:
                            timer.set_time_to_first_token()
                        accumulated_content += event.content or ""
                    elif isinstance(event, (ToolCallStartedEvent, ToolCallCompletedEvent)) and event.tool:
                        key = event.tool.tool_call_id or str(uuid4())
                        if key not in tools:
                            tools[key] = event.tool
                        elif isinstance(event, ToolCallCompletedEvent):
                            tools[key].result = event.tool.result
                            tools[key].tool_call_error = event.tool.tool_call_error
                    yield event
        except RunCancelledException:
            status = RunStatus.cancelled
        except Exception as error:
            log_exception(f"Error in {self.framework} agent '{self.id}': {error}")
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
        )
        if warnings:
            run.metadata = {"warnings": warnings}
        self._finish_run_output(run, run_state, continuation)
        if session is not None:
            await self._apersist_run_in_session(session, run)
        fields: Dict[str, Any] = dict(
            run_id=run_id,
            session_id=session_id,
            agent_id=self.get_id(),
            agent_name=self.name or "",
            content=run.content,
        )
        if status == RunStatus.cancelled:
            yield RunCancelledEvent(
                run_id=run_id, session_id=session_id, agent_id=self.get_id(), reason="Run cancelled"
            )
        elif run_error is not None:
            yield RunErrorEvent(**fields, error_type=error_type_of(run_error))
        else:
            yield RunCompletedEvent(**fields, metrics=run.metrics)
        if yield_run_output:
            yield run

    def _run_stream(self, input: Any, **kwargs: Any) -> Iterator[RunOutputEvent]:
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
