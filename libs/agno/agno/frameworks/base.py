import asyncio
from dataclasses import dataclass
from time import time
from typing import Any, AsyncIterator, Iterator, List, Optional, Sequence, Union
from uuid import uuid4

from agno.media import Audio, File, Image, Video
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunEvent,
    RunOutput,
    RunOutputEvent,
    RunStartedEvent,
)
from agno.run.base import RunStatus
from agno.utils.log import logger


@dataclass
class BaseExternalAgent:
    """Base class for external framework adapters.

    Provides shared infrastructure for:
    - ID and name management
    - Run lifecycle event emission (RunStarted, RunCompleted, RunError)
    - Tool call event wrapping
    - Sync/async run and print_response methods

    Subclasses must implement:
    - _arun_impl(input, **kwargs) -> str  (non-streaming)
    - _arun_stream_impl(input, **kwargs) -> AsyncIterator[RunOutputEvent]  (streaming)
    """

    agent_id: str
    agent_name: Optional[str] = None
    description: Optional[str] = None
    framework: str = "external"
    markdown: bool = True

    @property
    def id(self) -> str:
        return self.agent_id

    @property
    def name(self) -> Optional[str]:
        return self.agent_name or self.agent_id

    # ---------------------------------------------------------------------------
    # Public async API (satisfies AgentLike protocol)
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
        """Synchronous run. Returns RunOutput (non-streaming) or Iterator[RunOutputEvent] (streaming)."""
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
    # Internal: non-streaming
    # ---------------------------------------------------------------------------

    async def _arun_non_stream(self, input: Any, **kwargs: Any) -> RunOutput:
        run_id = str(uuid4())
        session_id = kwargs.get("session_id")
        user_id = kwargs.get("user_id")
        try:
            content = await self._arun_impl(input, run_id=run_id, **kwargs)
            return RunOutput(
                run_id=run_id,
                agent_id=self.id,
                agent_name=self.name,
                session_id=session_id,
                user_id=user_id,
                content=content,
                status=RunStatus.completed,
                created_at=int(time()),
            )
        except Exception as e:
            logger.error(f"Error in {self.framework} agent '{self.id}': {e}")
            return RunOutput(
                run_id=run_id,
                agent_id=self.id,
                agent_name=self.name,
                session_id=session_id,
                user_id=user_id,
                content=str(e),
                status=RunStatus.error,
                created_at=int(time()),
            )

    # ---------------------------------------------------------------------------
    # Internal: streaming
    # ---------------------------------------------------------------------------

    async def _arun_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        run_id = str(uuid4())
        session_id = kwargs.get("session_id")

        yield RunStartedEvent(
            run_id=run_id,
            agent_id=self.id,
            agent_name=self.name or "",
            session_id=session_id,
        )

        try:
            accumulated_content = ""
            async for event in self._arun_stream_impl(input, run_id=run_id, **kwargs):
                if isinstance(event, RunContentEvent):
                    accumulated_content += event.content or ""
                yield event

            yield RunCompletedEvent(
                run_id=run_id,
                agent_id=self.id,
                agent_name=self.name or "",
                session_id=session_id,
                content=accumulated_content,
            )
        except Exception as e:
            logger.error(f"Error in {self.framework} agent '{self.id}': {e}")
            yield RunErrorEvent(
                run_id=run_id,
                agent_id=self.id,
                agent_name=self.name or "",
                session_id=session_id,
                content=str(e),
            )

    def _run_stream(self, input: Any, **kwargs: Any) -> Iterator[RunOutputEvent]:
        """Sync streaming wrapper that yields events in real-time using a background thread."""
        import queue
        import threading

        event_queue: queue.Queue = queue.Queue()
        _sentinel = object()

        def _run_async():
            async def _produce():
                async for event in self._arun_stream(input, **kwargs):
                    event_queue.put(event)
                event_queue.put(_sentinel)

            asyncio.run(_produce())

        thread = threading.Thread(target=_run_async, daemon=True)
        thread.start()

        while True:
            item = event_queue.get()
            if item is _sentinel:
                break
            yield item

        thread.join()

    # ---------------------------------------------------------------------------
    # Subclass hooks (must be implemented by adapters)
    # ---------------------------------------------------------------------------

    async def _arun_impl(self, input: Any, **kwargs: Any) -> Any:
        """Non-streaming execution. Return the response content."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement _arun_impl")

    async def _arun_stream_impl(self, input: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        """Streaming execution. Yield RunContentEvent, ToolCallStartedEvent, etc.

        Do NOT yield RunStartedEvent or RunCompletedEvent -- those are handled by the base class.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement _arun_stream_impl")
        yield  # type: ignore  # make this a generator
