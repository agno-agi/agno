import asyncio
import json
from dataclasses import dataclass
from time import time
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Sequence, Union
from uuid import uuid4

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import (
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
from agno.utils.log import log_exception, log_warning


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
    - _arun_adapter(input, **kwargs) -> str  (non-streaming)
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
        **kwargs: Any,
    ) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]:
        if stream:
            return self._arun_stream(
                input,
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )
        else:
            # Returns a coroutine that the caller (router) awaits
            return self._arun_non_stream(  # type: ignore[return-value]
                input,
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )

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

    def read_or_create_session(self, session_id: str, user_id: Optional[str] = None) -> AgentSession:
        """Read a session from the DB, or create a new one."""
        session = None
        if self.db is not None and isinstance(self.db, BaseDb):
            session = self.db.get_session(session_id=session_id, session_type=SessionType.AGENT)

        if session is not None and isinstance(session, dict):
            session = AgentSession.from_dict(session)

        if session is None or not isinstance(session, AgentSession):
            session = self._create_session(session_id, user_id)

        return session

    async def aread_or_create_session(self, session_id: str, user_id: Optional[str] = None) -> AgentSession:
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
            session = self._create_session(session_id, user_id)

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

    # Run inspection (used by AgentOS /agents/{id}/runs/{run_id} for external agents)

    @staticmethod
    def _find_run_in_session(session: AgentSession, run_id: str) -> Optional[RunOutput]:
        """Find a persisted run by id within the given session."""
        for run in session.runs or []:
            if isinstance(run, RunOutput) and run.run_id == run_id:
                return run
        return None

    def get_run_output(self, run_id: str, session_id: Optional[str] = None) -> Optional[RunOutput]:
        """Get a persisted RunOutput for this adapter."""
        if not session_id:
            return None
        session = self.read_or_create_session(session_id)
        return self._find_run_in_session(session, run_id)

    async def aget_run_output(self, run_id: str, session_id: Optional[str] = None) -> Optional[RunOutput]:
        """Get a persisted RunOutput for this adapter."""
        if not session_id:
            return None
        session = await self.aread_or_create_session(session_id)
        return self._find_run_in_session(session, run_id)

    def _build_run_output(
        self,
        run_id: str,
        session_id: Optional[str],
        user_id: Optional[str],
        input_text: Any,
        content: Any,
        status: RunStatus,
        tools: Optional[List[ToolExecution]] = None,
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
            created_at=now,
        )

    def _get_history_from_session(self, session: AgentSession) -> List[Dict[str, Any]]:
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
        for run in session.runs:
            if not isinstance(run, RunOutput) or not run.messages:
                continue
            for msg in run.messages:
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

    # ---------------------------------------------------------------------------
    # Internal: non-streaming
    # ---------------------------------------------------------------------------

    async def _arun_non_stream(self, input: Any, **kwargs: Any) -> RunOutput:
        run_id = str(uuid4())
        session_id = kwargs.get("session_id") or str(uuid4())
        user_id = kwargs.get("user_id")

        # Load session and extract history for the adapter
        session = None
        history: Optional[List[Dict[str, Any]]] = None
        if self.db is not None:
            session = await self.aread_or_create_session(session_id, user_id)
            history = self._get_history_from_session(session)

        try:
            content = await self._arun_adapter(input, history=history, run_id=run_id, **kwargs)
            run_output = self._build_run_output(
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                input_text=input,
                content=content,
                status=RunStatus.completed,
            )
        except Exception as e:
            log_exception(f"Error in {self.framework} agent '{self.id}': {e}")
            run_output = self._build_run_output(
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                input_text=input,
                content=str(e),
                status=RunStatus.error,
            )

        # Persist the run to the session. Swallow DB failures so the caller still
        # receives the RunOutput — matching agent/_storage.aupsert_session semantics.
        if session is not None:
            if session.runs is None:
                session.runs = []
            session.runs.append(run_output)
            try:
                await self.aupsert_session(session)
            except Exception as upsert_err:
                log_warning(f"Failed to persist run for {self.framework} agent '{self.id}': {upsert_err}")

        return run_output

    # ---------------------------------------------------------------------------
    # Internal: streaming
    # ---------------------------------------------------------------------------

    async def _arun_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        run_id = str(uuid4())
        session_id = kwargs.get("session_id") or str(uuid4())
        user_id = kwargs.get("user_id")

        # Load session and extract history for the adapter
        session = None
        history: Optional[List[Dict[str, Any]]] = None
        if self.db is not None:
            session = await self.aread_or_create_session(session_id, user_id)
            history = self._get_history_from_session(session)

        yield RunStartedEvent(
            run_id=run_id,
            agent_id=self.get_id(),
            agent_name=self.name or "",
            session_id=session_id,
        )

        accumulated_content = ""
        accumulated_tools: List[ToolExecution] = []
        run_error: Optional[Exception] = None

        try:
            # Map tool_call_id -> ToolExecution for merging started+completed
            tool_map: Dict[str, ToolExecution] = {}

            async for event in self._arun_adapter_stream(input, history=history, run_id=run_id, **kwargs):
                if isinstance(event, RunContentEvent):
                    accumulated_content += event.content or ""
                elif isinstance(event, ToolCallStartedEvent) and event.tool:
                    tool = ToolExecution(
                        tool_call_id=event.tool.tool_call_id,
                        tool_name=event.tool.tool_name,
                        tool_args=event.tool.tool_args,
                    )
                    tool_map[event.tool.tool_call_id or ""] = tool
                    accumulated_tools.append(tool)
                elif isinstance(event, ToolCallCompletedEvent) and event.tool:
                    # Merge result into the existing tool entry
                    existing = tool_map.get(event.tool.tool_call_id or "")
                    if existing:
                        existing.result = event.tool.result
                    else:
                        accumulated_tools.append(event.tool)
                yield event
        except Exception as e:
            log_exception(f"Error in {self.framework} agent '{self.id}': {e}")
            run_error = e

        # Persist the run to the session. Swallow DB failures so the consumer
        # still receives the terminal RunCompletedEvent / RunErrorEvent below.
        if session is not None:
            run_output = self._build_run_output(
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                input_text=input,
                content=str(run_error) if run_error is not None else accumulated_content,
                status=RunStatus.error if run_error is not None else RunStatus.completed,
                tools=accumulated_tools if accumulated_tools else None,
            )
            if session.runs is None:
                session.runs = []
            session.runs.append(run_output)
            try:
                await self.aupsert_session(session)
            except Exception as upsert_err:
                log_warning(f"Failed to persist run for {self.framework} agent '{self.id}': {upsert_err}")

        if run_error is not None:
            yield RunErrorEvent(
                run_id=run_id,
                agent_id=self.get_id(),
                agent_name=self.name or "",
                session_id=session_id,
                content=str(run_error),
            )
        else:
            yield RunCompletedEvent(
                run_id=run_id,
                agent_id=self.get_id(),
                agent_name=self.name or "",
                session_id=session_id,
                content=accumulated_content,
            )

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

    async def _arun_adapter(self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> Any:
        """Non-streaming execution. Return the response content."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement _arun_adapter")

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming execution. Yield RunContentEvent, ToolCallStartedEvent, etc.

        Do NOT yield RunStartedEvent or RunCompletedEvent -- those are handled by the base class.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement _arun_adapter_stream")
        yield  # type: ignore  # make this a generator
