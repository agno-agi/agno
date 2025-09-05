import json
from collections.abc import Set
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union, cast, get_args

from pydantic import BaseModel
from rich.console import Group
from rich.json import JSON
from rich.live import Live
from rich.markdown import Markdown
from rich.status import Status
from rich.text import Text

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunEvent, RunOutput, RunOutputEvent, RunPausedEvent
from agno.utils.log import log_warning
from agno.utils.message import get_text_from_message
from agno.utils.response import create_panel, create_paused_run_output_panel, escape_markdown_tags, format_tool_calls
from agno.utils.timer import Timer

if TYPE_CHECKING:
    from agno.agent.agent import Agent


def print_response_stream(
    agent: "Agent",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    stream_intermediate_steps: bool = False,
    knowledge_filters: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    markdown: bool = False,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
    console: Optional[Any] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
):
    _response_content: str = ""
    _response_reasoning_content: str = ""
    response_content_batch: Union[str, JSON, Markdown] = ""
    reasoning_steps: List[ReasoningStep] = []
    accumulated_tool_calls: List = []

    with Live(console=console) as live_log:
        status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
        live_log.update(status)
        response_timer = Timer()
        response_timer.start()
        # Flag which indicates if the panels should be rendered
        render = False
        # Panels to be rendered
        panels = [status]
        # First render the message panel if the message is not None
        if input and show_message:
            render = True
            # Convert message to a panel
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            panels.append(message_panel)
        if render:
            live_log.update(Group(*panels))

        for response_event in agent.run(
            input=input,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=True,
            stream_intermediate_steps=stream_intermediate_steps,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            metadata=metadata,
            **kwargs,
        ):
            if isinstance(response_event, tuple(get_args(RunOutputEvent))):
                if response_event.is_paused:  # type: ignore
                    response_event = cast(RunPausedEvent, response_event)  # type: ignore
                    response_panel = create_paused_run_output_panel(response_event)  # type: ignore
                    panels.append(response_panel)
                    live_log.update(Group(*panels))
                    return

                if (
                    response_event.event == RunEvent.tool_call_started  # type: ignore
                    and hasattr(response_event, "tool")
                    and response_event.tool is not None
                ):
                    accumulated_tool_calls.append(response_event.tool)

                if response_event.event == RunEvent.run_content:  # type: ignore
                    if hasattr(response_event, "content"):
                        if isinstance(response_event.content, str):
                            _response_content += response_event.content
                        elif agent.output_schema is not None and isinstance(response_event.content, BaseModel):
                            try:
                                response_content_batch = JSON(  # type: ignore
                                    response_event.content.model_dump_json(exclude_none=True), indent=2
                                )
                            except Exception as e:
                                log_warning(f"Failed to convert response to JSON: {e}")
                        else:
                            try:
                                response_content_batch = JSON(json.dumps(response_event.content), indent=4)
                            except Exception as e:
                                log_warning(f"Failed to convert response to JSON: {e}")
                    if hasattr(response_event, "reasoning_content") and response_event.reasoning_content is not None:  # type: ignore
                        _response_reasoning_content += response_event.reasoning_content  # type: ignore
                if hasattr(response_event, "reasoning_steps") and response_event.reasoning_steps is not None:  # type: ignore
                    reasoning_steps = response_event.reasoning_steps  # type: ignore

            # Escape special tags before markdown conversion
            if markdown:
                escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)  # type: ignore
                response_content_batch = Markdown(escaped_content)

            response_content_stream: str = _response_content

            # Check if we have any response content to display
            if response_content_stream and not markdown:
                response_content = response_content_stream
            else:
                response_content = response_content_batch  # type: ignore

            # Sanitize empty Markdown content
            if isinstance(response_content, Markdown):
                if not (response_content.markup and response_content.markup.strip()):
                    response_content = None  # type: ignore

            panels = [status]
            if show_message:
                # Convert message to a panel
                message_content = get_text_from_message(input)
                message_panel = create_panel(
                    content=Text(message_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)

            additional_panels = build_panels_stream(
                response_content=response_content,
                response_event=response_event,  # type: ignore
                response_timer=response_timer,
                response_reasoning_content_buffer=_response_reasoning_content,
                reasoning_steps=reasoning_steps,
                show_reasoning=show_reasoning,
                show_full_reasoning=show_full_reasoning,
                accumulated_tool_calls=accumulated_tool_calls,
            )
            panels.extend(additional_panels)
            if panels:
                live_log.update(Group(*panels))

        if agent.memory_manager is not None and agent.memory_manager.memories_updated:
            memory_panel = create_panel(
                content=Text("Memories updated"),
                title="Memories",
                border_style="green",
            )
            panels.append(memory_panel)
            live_log.update(Group(*panels))
            agent.memory_manager.memories_updated = False

        if agent.session_summary_manager is not None and agent.session_summary_manager.summaries_updated:
            summary_panel = create_panel(
                content=Text("Session summary updated"),
                title="Session Summary",
                border_style="green",
            )
            panels.append(summary_panel)
            live_log.update(Group(*panels))
            agent.session_summary_manager.summaries_updated = False

        response_timer.stop()

        # Final update to remove the "Thinking..." status
        panels = [p for p in panels if not isinstance(p, Status)]
        live_log.update(Group(*panels))


async def aprint_response_stream(
    agent: "Agent",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    stream_intermediate_steps: bool = False,
    knowledge_filters: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    markdown: bool = False,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
    console: Optional[Any] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
):
    _response_content: str = ""
    _response_reasoning_content: str = ""
    reasoning_steps: List[ReasoningStep] = []
    response_content_batch: Union[str, JSON, Markdown] = ""
    accumulated_tool_calls: List = []

    with Live(console=console) as live_log:
        status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
        live_log.update(status)
        response_timer = Timer()
        response_timer.start()
        # Flag which indicates if the panels should be rendered
        render = False
        # Panels to be rendered
        panels = [status]
        # First render the message panel if the message is not None
        if input and show_message:
            render = True
            # Convert message to a panel
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            panels.append(message_panel)
        if render:
            live_log.update(Group(*panels))

        result = agent.arun(
            input=input,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=True,
            stream_intermediate_steps=stream_intermediate_steps,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            metadata=metadata,
            **kwargs,
        )

        async for resp in result:  # type: ignore
            if isinstance(resp, tuple(get_args(RunOutputEvent))):
                if resp.is_paused:
                    response_panel = create_paused_run_output_panel(resp)  # type: ignore
                    panels.append(response_panel)
                    live_log.update(Group(*panels))
                    break

                if (
                    resp.event == RunEvent.tool_call_started  # type: ignore
                    and hasattr(resp, "tool")
                    and resp.tool is not None
                ):
                    accumulated_tool_calls.append(resp.tool)

                if resp.event == RunEvent.run_content:  # type: ignore
                    if isinstance(resp.content, str):
                        _response_content += resp.content
                    elif agent.output_schema is not None and isinstance(resp.content, BaseModel):
                        try:
                            response_content_batch = JSON(resp.content.model_dump_json(exclude_none=True), indent=2)  # type: ignore
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    else:
                        try:
                            response_content_batch = JSON(json.dumps(resp.content), indent=4)
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    if resp.reasoning_content is not None:  # type: ignore
                        _response_reasoning_content += resp.reasoning_content  # type: ignore

                if hasattr(resp, "reasoning_steps") and resp.reasoning_steps is not None:  # type: ignore
                    reasoning_steps = resp.reasoning_steps  # type: ignore

            response_content_stream: str = _response_content

            # Escape special tags before markdown conversion
            if markdown:
                escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)  # type: ignore
                response_content_batch = Markdown(escaped_content)

            # Check if we have any response content to display
            if response_content_stream and not markdown:
                response_content = response_content_stream
            else:
                response_content = response_content_batch  # type: ignore

            # Sanitize empty Markdown content
            if isinstance(response_content, Markdown):
                if not (response_content.markup and response_content.markup.strip()):
                    response_content = None  # type: ignore

            panels = [status]

            if input and show_message:
                render = True
                # Convert message to a panel
                message_content = get_text_from_message(input)
                message_panel = create_panel(
                    content=Text(message_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)

            additional_panels = build_panels_stream(
                response_content=response_content,
                response_event=resp,  # type: ignore
                response_timer=response_timer,
                response_reasoning_content_buffer=_response_reasoning_content,
                reasoning_steps=reasoning_steps,
                show_reasoning=show_reasoning,
                show_full_reasoning=show_full_reasoning,
                accumulated_tool_calls=accumulated_tool_calls,
            )
            panels.extend(additional_panels)
            if panels:
                live_log.update(Group(*panels))

        if agent.memory_manager is not None and agent.memory_manager.memories_updated:
            memory_panel = create_panel(
                content=Text("Memories updated"),
                title="Memories",
                border_style="green",
            )
            panels.append(memory_panel)
            live_log.update(Group(*panels))
            agent.memory_manager.memories_updated = False

        if agent.session_summary_manager is not None and agent.session_summary_manager.summaries_updated:
            summary_panel = create_panel(
                content=Text("Session summary updated"),
                title="Session Summary",
                border_style="green",
            )
            panels.append(summary_panel)
            live_log.update(Group(*panels))
            agent.session_summary_manager.summaries_updated = False

        response_timer.stop()

        # Final update to remove the "Thinking..." status
        panels = [p for p in panels if not isinstance(p, Status)]
        live_log.update(Group(*panels))


def build_panels_stream(
    response_content: Union[str, JSON, Markdown],
    response_event: RunOutputEvent,
    response_timer: Timer,
    response_reasoning_content_buffer: str,
    reasoning_steps: List[ReasoningStep],
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    accumulated_tool_calls: Optional[List] = None,
):
    panels = []

    if len(reasoning_steps) > 0 and show_reasoning:
        # Create panels for reasoning steps
        for i, step in enumerate(reasoning_steps, 1):
            # Build step content
            step_content = Text.assemble()
            if step.title is not None:
                step_content.append(f"{step.title}\n", "bold")
            if step.action is not None:
                step_content.append(Text.from_markup(f"[bold]Action:[/bold] {step.action}\n", style="dim"))
            if step.result is not None:
                step_content.append(Text.from_markup(step.result, style="dim"))

            if show_full_reasoning:
                # Add detailed reasoning information if available
                if step.reasoning is not None:
                    step_content.append(Text.from_markup(f"\n[bold]Reasoning:[/bold] {step.reasoning}", style="dim"))
                if step.confidence is not None:
                    step_content.append(Text.from_markup(f"\n[bold]Confidence:[/bold] {step.confidence}", style="dim"))
            reasoning_panel = create_panel(content=step_content, title=f"Reasoning step {i}", border_style="green")
            panels.append(reasoning_panel)

    if len(response_reasoning_content_buffer) > 0:
        # Create panel for thinking
        thinking_panel = create_panel(
            content=Text(response_reasoning_content_buffer),
            title=f"Thinking ({response_timer.elapsed:.1f}s)",
            border_style="green",
        )
        panels.append(thinking_panel)

    if accumulated_tool_calls:  # Use accumulated tool calls instead of just current event
        # Create bullet points for each tool call
        tool_calls_content = Text()
        formatted_tool_calls = format_tool_calls(accumulated_tool_calls)
        for formatted_tool_call in formatted_tool_calls:
            tool_calls_content.append(f"• {formatted_tool_call}\n")

        tool_calls_panel = create_panel(
            content=tool_calls_content.plain.rstrip(),
            title="Tool Calls",
            border_style="yellow",
        )
        panels.append(tool_calls_panel)

    response_panel = None
    if response_content:
        response_panel = create_panel(
            content=response_content,
            title=f"Response ({response_timer.elapsed:.1f}s)",
            border_style="blue",
        )
        panels.append(response_panel)

    if (
        isinstance(response_event, tuple(get_args(RunOutputEvent)))
        and hasattr(response_event, "citations")
        and response_event.citations is not None
        and response_event.citations.urls is not None
    ):
        md_content = "\n".join(
            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
            for i, citation in enumerate(response_event.citations.urls)
            if citation.url  # Only include citations with valid URLs
        )
        if md_content:  # Only create panel if there are citations
            citations_panel = create_panel(
                content=Markdown(md_content),
                title="Citations",
                border_style="green",
            )
            panels.append(citations_panel)

    return panels


def print_response(
    agent: "Agent",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    stream_intermediate_steps: bool = False,
    knowledge_filters: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    markdown: bool = False,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
    console: Optional[Any] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
):
    with Live(console=console) as live_log:
        status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
        live_log.update(status)
        response_timer = Timer()
        response_timer.start()
        # Panels to be rendered
        panels = [status]
        # First render the message panel if the message is not None
        if input and show_message:
            # Convert message to a panel
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            panels.append(message_panel)  # type: ignore
            live_log.update(Group(*panels))

        # Run the agent
        run_response = agent.run(
            input=input,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=False,
            stream_intermediate_steps=stream_intermediate_steps,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            metadata=metadata,
            **kwargs,
        )
        response_timer.stop()

        additional_panels = build_panels(
            run_response=run_response,
            output_schema=agent.output_schema,  # type: ignore
            response_timer=response_timer,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            markdown=markdown,
        )
        panels.extend(additional_panels)

        if agent.memory_manager is not None and agent.memory_manager.memories_updated:
            memory_panel = create_panel(
                content=Text("Memories updated"),
                title="Memories",
                border_style="green",
            )
            panels.append(memory_panel)
            live_log.update(Group(*panels))
            agent.memory_manager.memories_updated = False

        if agent.session_summary_manager is not None and agent.session_summary_manager.summaries_updated:
            summary_panel = create_panel(
                content=Text("Session summary updated"),
                title="Session Summary",
                border_style="green",
            )
            panels.append(summary_panel)
            live_log.update(Group(*panels))
            agent.session_summary_manager.summaries_updated = False

        # Final update to remove the "Thinking..." status
        panels = [p for p in panels if not isinstance(p, Status)]
        live_log.update(Group(*panels))


async def aprint_response(
    agent: "Agent",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    stream_intermediate_steps: bool = False,
    knowledge_filters: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    markdown: bool = False,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
    console: Optional[Any] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
):
    with Live(console=console) as live_log:
        status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
        live_log.update(status)
        response_timer = Timer()
        response_timer.start()
        # Panels to be rendered
        panels = [status]
        # First render the message panel if the message is not None
        if input and show_message:
            # Convert message to a panel
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            panels.append(message_panel)
            live_log.update(Group(*panels))

        # Run the agent
        run_response = await agent.arun(
            input=input,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=False,
            stream_intermediate_steps=stream_intermediate_steps,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            metadata=metadata,
            **kwargs,
        )
        response_timer.stop()

        additional_panels = build_panels(
            run_response=run_response,
            output_schema=agent.output_schema,  # type: ignore
            response_timer=response_timer,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            markdown=markdown,
        )
        panels.extend(additional_panels)

        if agent.memory_manager is not None and agent.memory_manager.memories_updated:
            memory_panel = create_panel(
                content=Text("Memories updated"),
                title="Memories",
                border_style="green",
            )
            panels.append(memory_panel)
            live_log.update(Group(*panels))
            agent.memory_manager.memories_updated = False

        if agent.session_summary_manager is not None and agent.session_summary_manager.summaries_updated is not None:
            summary_panel = create_panel(
                content=Text("Session summary updated"),
                title="Session Summary",
                border_style="green",
            )
            agent.session_summary_manager.summaries_updated = False
            panels.append(summary_panel)
            live_log.update(Group(*panels))

        # Final update to remove the "Thinking..." status
        panels = [p for p in panels if not isinstance(p, Status)]
        live_log.update(Group(*panels))


def build_panels(
    run_response: RunOutput,
    response_timer: Timer,
    output_schema: Optional[BaseModel] = None,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    markdown: bool = False,
):
    panels = []

    reasoning_steps = []

    if isinstance(run_response, RunOutput) and run_response.is_paused:
        response_panel = create_paused_run_output_panel(run_response)
        panels.append(response_panel)
        return panels

    if isinstance(run_response, RunOutput) and run_response.reasoning_steps is not None:
        reasoning_steps = run_response.reasoning_steps

    if len(reasoning_steps) > 0 and show_reasoning:
        # Create panels for reasoning steps
        for i, step in enumerate(reasoning_steps, 1):
            # Build step content
            step_content = Text.assemble()
            if step.title is not None:
                step_content.append(f"{step.title}\n", "bold")
            if step.action is not None:
                step_content.append(Text.from_markup(f"[bold]Action:[/bold] {step.action}\n", style="dim"))
            if step.result is not None:
                step_content.append(Text.from_markup(step.result, style="dim"))

            if show_full_reasoning:
                # Add detailed reasoning information if available
                if step.reasoning is not None:
                    step_content.append(Text.from_markup(f"\n[bold]Reasoning:[/bold] {step.reasoning}", style="dim"))
                if step.confidence is not None:
                    step_content.append(Text.from_markup(f"\n[bold]Confidence:[/bold] {step.confidence}", style="dim"))
            reasoning_panel = create_panel(content=step_content, title=f"Reasoning step {i}", border_style="green")
            panels.append(reasoning_panel)

    if isinstance(run_response, RunOutput) and run_response.reasoning_content is not None:
        # Create panel for thinking
        thinking_panel = create_panel(
            content=Text(run_response.reasoning_content),
            title=f"Thinking ({response_timer.elapsed:.1f}s)",
            border_style="green",
        )
        panels.append(thinking_panel)

    # Add tool calls panel if available
    if isinstance(run_response, RunOutput) and run_response.tools:
        # Create bullet points for each tool call
        tool_calls_content = Text()
        formatted_tool_calls = format_tool_calls(run_response.tools)
        for formatted_tool_call in formatted_tool_calls:
            tool_calls_content.append(f"• {formatted_tool_call}\n")

        tool_calls_panel = create_panel(
            content=tool_calls_content.plain.rstrip(),
            title="Tool Calls",
            border_style="yellow",
        )
        panels.append(tool_calls_panel)

    response_content_batch: Union[str, JSON, Markdown] = ""  # type: ignore
    if isinstance(run_response, RunOutput):
        if isinstance(run_response.content, str):
            if markdown:
                escaped_content = escape_markdown_tags(run_response.content, tags_to_include_in_markdown)  # type: ignore
                response_content_batch = Markdown(escaped_content)
            else:
                response_content_batch = run_response.get_content_as_string(indent=4)
        elif output_schema is not None and isinstance(run_response.content, BaseModel):
            try:
                response_content_batch = JSON(run_response.content.model_dump_json(exclude_none=True), indent=2)
            except Exception as e:
                log_warning(f"Failed to convert response to JSON: {e}")
        else:
            try:
                response_content_batch = JSON(json.dumps(run_response.content), indent=4)
            except Exception as e:
                log_warning(f"Failed to convert response to JSON: {e}")

    # Create panel for response
    response_panel = create_panel(
        content=response_content_batch,
        title=f"Response ({response_timer.elapsed:.1f}s)",
        border_style="blue",
    )
    panels.append(response_panel)

    if (
        isinstance(run_response, RunOutput)
        and run_response.citations is not None
        and run_response.citations.urls is not None
    ):
        md_content = "\n".join(
            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
            for i, citation in enumerate(run_response.citations.urls)
            if citation.url  # Only include citations with valid URLs
        )
        if md_content:  # Only create panel if there are citations
            citations_panel = create_panel(
                content=Markdown(md_content),
                title="Citations",
                border_style="green",
            )
            panels.append(citations_panel)

    return panels
