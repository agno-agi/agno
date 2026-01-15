import json
import warnings
from collections.abc import Set
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union, cast, get_args

from pydantic import BaseModel
from rich.console import Group
from rich.json import JSON
from rich.live import Live
from rich.markdown import Markdown
from rich.status import Status
from rich.text import Text

from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunContentEvent, RunEvent, RunOutput, RunOutputEvent, RunPausedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    LoopIterationCompletedEvent,
    LoopIterationStartedEvent,
    ParallelExecutionCompletedEvent,
    ParallelExecutionStartedEvent,
    RouterExecutionCompletedEvent,
    RouterExecutionStartedEvent,
    StepCompletedEvent,
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutputEvent,
    WorkflowStartedEvent,
)
from agno.utils.log import log_warning
from agno.utils.message import get_text_from_message
from agno.utils.print_response.helpers import build_workflow_step_panel
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
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    debug_mode: Optional[bool] = None,
    markdown: bool = False,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
    console: Optional[Any] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
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

        input_content = get_text_from_message(input)

        # Track workflow state
        workflow_step_panels: List[Any] = []
        current_workflow_step_name: str = ""
        current_workflow_step_content: str = ""
        workflow_in_progress: bool = False
        all_panels: List[Any] = []

        for response_event in agent.run(
            input=input,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=True,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            dependencies=dependencies,
            metadata=metadata,
            **kwargs,
        ):
            if isinstance(response_event, tuple(get_args(WorkflowRunOutputEvent))):
                if isinstance(response_event, WorkflowStartedEvent):
                    workflow_in_progress = True
                    status.update(f"Workflow started: {response_event.workflow_name or 'Workflow'}...")
                    live_log.update(Group(*panels, status))
                    continue

                elif isinstance(response_event, StepStartedEvent):
                    step_name = response_event.step_name or "Unknown"
                    current_workflow_step_name = step_name
                    current_workflow_step_content = ""
                    status.update(f"Running step: {step_name}...")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, StepCompletedEvent):
                    step_name = response_event.step_name or "Unknown"
                    step_content = current_workflow_step_content or (
                        str(response_event.content) if response_event.content else ""
                    )
                    if step_content:
                        step_panel = create_panel(
                            content=Markdown(step_content) if markdown else Text(step_content),
                            title=f"Step: {step_name} (Completed)",
                            border_style="orange3",
                        )
                        workflow_step_panels.append(step_panel)
                    status.update(f"Completed step: {step_name}")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    current_workflow_step_name = ""
                    current_workflow_step_content = ""
                    continue

                elif isinstance(response_event, LoopExecutionStartedEvent):
                    status.update(
                        f"Starting loop: {response_event.step_name or 'Loop'} (max {response_event.max_iterations} iterations)..."
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, LoopIterationStartedEvent):
                    status.update(
                        f"Loop iteration {response_event.iteration}/{response_event.max_iterations}: {response_event.step_name}..."
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, LoopIterationCompletedEvent):
                    status.update(
                        f"Completed iteration {response_event.iteration}/{response_event.max_iterations}: {response_event.step_name}"
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, LoopExecutionCompletedEvent):
                    status.update(
                        f"Completed loop: {response_event.step_name or 'Loop'} ({response_event.total_iterations} iterations)"
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, ParallelExecutionStartedEvent):
                    status.update(f"Starting parallel execution: {response_event.step_name or 'Parallel'}...")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, ParallelExecutionCompletedEvent):
                    status.update(f"Completed parallel execution: {response_event.step_name or 'Parallel'}")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, ConditionExecutionStartedEvent):
                    condition_result = "true" if response_event.condition_result else "false"
                    status.update(
                        f"Evaluating condition: {response_event.step_name or 'Condition'} ({condition_result})..."
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, ConditionExecutionCompletedEvent):
                    condition_result = "true" if response_event.condition_result else "false"
                    status.update(
                        f"Completed condition: {response_event.step_name or 'Condition'} ({condition_result}, {response_event.executed_steps or 0} steps)"
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, RouterExecutionStartedEvent):
                    selected = ", ".join(response_event.selected_steps) if response_event.selected_steps else "none"
                    status.update(f"Router selecting: {response_event.step_name or 'Router'} -> [{selected}]...")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, RouterExecutionCompletedEvent):
                    selected = ", ".join(response_event.selected_steps) if response_event.selected_steps else "none"
                    status.update(
                        f"Completed router: {response_event.step_name or 'Router'} -> [{selected}] ({response_event.executed_steps or 0} steps)"
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, StepsExecutionStartedEvent):
                    status.update(
                        f"Starting steps: {response_event.step_name or 'Steps'} ({response_event.steps_count or 0} steps)..."
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, StepsExecutionCompletedEvent):
                    status.update(
                        f"Completed steps: {response_event.step_name or 'Steps'} ({response_event.executed_steps or 0}/{response_event.steps_count or 0} steps)"
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(response_event, WorkflowCompletedEvent):
                    workflow_in_progress = False
                    status.update("Workflow completed")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

            if workflow_in_progress and isinstance(response_event, (RunContentEvent, TeamRunContentEvent)):
                if response_event.content is not None and isinstance(response_event.content, str):
                    current_workflow_step_content += response_event.content
                    current_step_panel = build_workflow_step_panel(
                        current_workflow_step_name, current_workflow_step_content, markdown, create_panel, running=True
                    )
                    display_panels = panels + workflow_step_panels
                    if current_step_panel:
                        display_panels = display_panels + [current_step_panel]
                    live_log.update(Group(*display_panels, status))
                    continue
                continue

            if isinstance(response_event, tuple(get_args(RunOutputEvent))):
                if response_event.is_paused:  # type: ignore
                    response_event = cast(RunPausedEvent, response_event)  # type: ignore
                    response_panel = create_paused_run_output_panel(response_event)  # type: ignore
                    panels.append(response_panel)
                    live_log.update(Group(*panels))
                    return

                if response_event.event == RunEvent.pre_hook_completed:  # type: ignore
                    if response_event.run_input is not None:  # type: ignore
                        input_content = get_text_from_message(response_event.run_input.input_content)  # type: ignore

                if (
                    response_event.event == RunEvent.tool_call_started  # type: ignore
                    and hasattr(response_event, "tool")
                    and response_event.tool is not None
                ):
                    accumulated_tool_calls.append(response_event.tool)

                if response_event.event == RunEvent.run_content:  # type: ignore
                    if hasattr(response_event, "content"):
                        if isinstance(response_event.content, str):
                            # Don't accumulate text content, parser_model will replace it
                            if not (agent.parser_model is not None and agent.output_schema is not None):
                                _response_content += response_event.content
                        elif agent.output_schema is not None and isinstance(response_event.content, BaseModel):
                            try:
                                response_content_batch = JSON(  # type: ignore
                                    response_event.content.model_dump_json(exclude_none=True), indent=2
                                )
                            except Exception as e:
                                log_warning(f"Failed to convert response to JSON: {e}")
                        elif agent.output_schema is not None and isinstance(response_event.content, dict):
                            try:
                                response_content_batch = JSON(json.dumps(response_event.content), indent=2)  # type: ignore
                            except Exception as e:
                                log_warning(f"Failed to convert response to JSON: {e}")
                        else:
                            try:
                                response_content_batch = JSON(json.dumps(response_event.content), indent=4)
                            except Exception as e:
                                log_warning(f"Failed to convert response to JSON: {e}")
                    if hasattr(response_event, "reasoning_content") and response_event.reasoning_content is not None:  # type: ignore
                        _response_reasoning_content += response_event.reasoning_content  # type: ignore

                # Handle streaming reasoning content delta events
                if response_event.event == RunEvent.reasoning_content_delta:  # type: ignore
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
                message_panel = create_panel(
                    content=Text(input_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)

            if workflow_in_progress:
                additional_panels = build_panels_stream(
                    response_content=None,
                    response_event=response_event,  # type: ignore
                    response_timer=response_timer,
                    response_reasoning_content_buffer=_response_reasoning_content,
                    reasoning_steps=reasoning_steps,
                    show_reasoning=show_reasoning,
                    show_full_reasoning=show_full_reasoning,
                    accumulated_tool_calls=accumulated_tool_calls,
                    compression_manager=agent.compression_manager,
                )
                panels.extend(additional_panels)
                all_panels = panels + workflow_step_panels
            else:
                additional_panels = build_panels_stream(
                    response_content=response_content,
                    response_event=response_event,  # type: ignore
                    response_timer=response_timer,
                    response_reasoning_content_buffer=_response_reasoning_content,
                    reasoning_steps=reasoning_steps,
                    show_reasoning=show_reasoning,
                    show_full_reasoning=show_full_reasoning,
                    accumulated_tool_calls=accumulated_tool_calls,
                    compression_manager=agent.compression_manager,
                )
                all_panels = panels + workflow_step_panels + additional_panels

            if all_panels:
                live_log.update(Group(*all_panels))

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

        if agent.compression_manager is not None:
            agent.compression_manager.stats.clear()

        response_timer.stop()

        final_panels = [p for p in all_panels if not isinstance(p, Status)]
        live_log.update(Group(*final_panels))


async def aprint_response_stream(
    agent: "Agent",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    debug_mode: Optional[bool] = None,
    markdown: bool = False,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
    console: Optional[Any] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
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
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=True,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            dependencies=dependencies,
            metadata=metadata,
            **kwargs,
        )

        input_content = get_text_from_message(input)

        # Track workflow state for displaying workflow events from tools
        workflow_step_panels: List[Any] = []
        current_workflow_step_name: str = ""
        current_workflow_step_content: str = ""
        workflow_in_progress: bool = False
        all_panels: List[Any] = []

        async for resp in result:  # type: ignore
            if isinstance(resp, tuple(get_args(WorkflowRunOutputEvent))):
                if isinstance(resp, WorkflowStartedEvent):
                    workflow_in_progress = True
                    status.update(f"Workflow started: {resp.workflow_name or 'Workflow'}...")
                    live_log.update(Group(*panels, status))
                    continue

                elif isinstance(resp, StepStartedEvent):
                    step_name = resp.step_name or "Unknown"
                    current_workflow_step_name = step_name
                    current_workflow_step_content = ""
                    status.update(f"Running step: {step_name}...")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, StepCompletedEvent):
                    step_name = resp.step_name or "Unknown"
                    step_content = current_workflow_step_content or (str(resp.content) if resp.content else "")
                    if step_content:
                        step_panel = create_panel(
                            content=Markdown(step_content) if markdown else Text(step_content),
                            title=f"Step: {step_name} (Completed)",
                            border_style="orange3",
                        )
                        workflow_step_panels.append(step_panel)
                    status.update(f"Completed step: {step_name}")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    current_workflow_step_name = ""
                    current_workflow_step_content = ""
                    continue

                elif isinstance(resp, LoopExecutionStartedEvent):
                    status.update(
                        f"Starting loop: {resp.step_name or 'Loop'} (max {resp.max_iterations} iterations)..."
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, LoopIterationStartedEvent):
                    status.update(f"Loop iteration {resp.iteration}/{resp.max_iterations}: {resp.step_name}...")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, LoopIterationCompletedEvent):
                    status.update(f"Completed iteration {resp.iteration}/{resp.max_iterations}: {resp.step_name}")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, LoopExecutionCompletedEvent):
                    status.update(f"Completed loop: {resp.step_name or 'Loop'} ({resp.total_iterations} iterations)")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, ParallelExecutionStartedEvent):
                    status.update(f"Starting parallel execution: {resp.step_name or 'Parallel'}...")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, ParallelExecutionCompletedEvent):
                    status.update(f"Completed parallel execution: {resp.step_name or 'Parallel'}")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, ConditionExecutionStartedEvent):
                    condition_result = "true" if resp.condition_result else "false"
                    status.update(f"Evaluating condition: {resp.step_name or 'Condition'} ({condition_result})...")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, ConditionExecutionCompletedEvent):
                    condition_result = "true" if resp.condition_result else "false"
                    status.update(
                        f"Completed condition: {resp.step_name or 'Condition'} ({condition_result}, {resp.executed_steps or 0} steps)"
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, RouterExecutionStartedEvent):
                    selected = ", ".join(resp.selected_steps) if resp.selected_steps else "none"
                    status.update(f"Router selecting: {resp.step_name or 'Router'} -> [{selected}]...")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, RouterExecutionCompletedEvent):
                    selected = ", ".join(resp.selected_steps) if resp.selected_steps else "none"
                    status.update(
                        f"Completed router: {resp.step_name or 'Router'} -> [{selected}] ({resp.executed_steps or 0} steps)"
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, StepsExecutionStartedEvent):
                    status.update(f"Starting steps: {resp.step_name or 'Steps'} ({resp.steps_count or 0} steps)...")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, StepsExecutionCompletedEvent):
                    status.update(
                        f"Completed steps: {resp.step_name or 'Steps'} ({resp.executed_steps or 0}/{resp.steps_count or 0} steps)"
                    )
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

                elif isinstance(resp, WorkflowCompletedEvent):
                    workflow_in_progress = False
                    status.update("Workflow completed")
                    live_log.update(Group(*panels, *workflow_step_panels, status))
                    continue

            if workflow_in_progress and isinstance(resp, (RunContentEvent, TeamRunContentEvent)):
                if resp.content is not None and isinstance(resp.content, str):
                    current_workflow_step_content += resp.content
                    current_step_panel = build_workflow_step_panel(
                        current_workflow_step_name, current_workflow_step_content, markdown, create_panel, running=True
                    )
                    display_panels = panels + workflow_step_panels
                    if current_step_panel:
                        display_panels = display_panels + [current_step_panel]
                    live_log.update(Group(*display_panels, status))
                    continue
                continue

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

                if resp.event == RunEvent.pre_hook_completed:  # type: ignore
                    if resp.run_input is not None:  # type: ignore
                        input_content = get_text_from_message(resp.run_input.input_content)  # type: ignore

                if resp.event == RunEvent.run_content:  # type: ignore
                    if isinstance(resp.content, str):
                        # Don't accumulate text content, parser_model will replace it
                        if not (agent.parser_model is not None and agent.output_schema is not None):
                            _response_content += resp.content
                    elif agent.output_schema is not None and isinstance(resp.content, BaseModel):
                        try:
                            response_content_batch = JSON(resp.content.model_dump_json(exclude_none=True), indent=2)  # type: ignore
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    elif agent.output_schema is not None and isinstance(resp.content, dict):
                        try:
                            response_content_batch = JSON(json.dumps(resp.content), indent=2)  # type: ignore
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    else:
                        try:
                            response_content_batch = JSON(json.dumps(resp.content), indent=4)
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    if resp.reasoning_content is not None:  # type: ignore
                        _response_reasoning_content += resp.reasoning_content  # type: ignore

                # Handle streaming reasoning content delta events
                if resp.event == RunEvent.reasoning_content_delta:  # type: ignore
                    if hasattr(resp, "reasoning_content") and resp.reasoning_content is not None:  # type: ignore
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

            if input_content and show_message:
                render = True
                # Convert message to a panel
                message_panel = create_panel(
                    content=Text(input_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)

            if workflow_in_progress:
                additional_panels = build_panels_stream(
                    response_content=None,
                    response_event=resp,  # type: ignore
                    response_timer=response_timer,
                    response_reasoning_content_buffer=_response_reasoning_content,
                    reasoning_steps=reasoning_steps,
                    show_reasoning=show_reasoning,
                    show_full_reasoning=show_full_reasoning,
                    accumulated_tool_calls=accumulated_tool_calls,
                    compression_manager=agent.compression_manager,
                )
                panels.extend(additional_panels)
                all_panels = panels + workflow_step_panels
            else:
                additional_panels = build_panels_stream(
                    response_content=response_content,
                    response_event=resp,  # type: ignore
                    response_timer=response_timer,
                    response_reasoning_content_buffer=_response_reasoning_content,
                    reasoning_steps=reasoning_steps,
                    show_reasoning=show_reasoning,
                    show_full_reasoning=show_full_reasoning,
                    accumulated_tool_calls=accumulated_tool_calls,
                    compression_manager=agent.compression_manager,
                )
                all_panels = panels + workflow_step_panels + additional_panels

            if all_panels:
                live_log.update(Group(*all_panels))

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

        if agent.compression_manager is not None:
            agent.compression_manager.stats.clear()

        response_timer.stop()

        final_panels = [p for p in all_panels if not isinstance(p, Status)]
        live_log.update(Group(*final_panels))


def build_panels_stream(
    response_content: Optional[Union[str, JSON, Markdown]],
    response_event: RunOutputEvent,
    response_timer: Timer,
    response_reasoning_content_buffer: str,
    reasoning_steps: List[ReasoningStep],
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    accumulated_tool_calls: Optional[List] = None,
    compression_manager: Optional[Any] = None,
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

    if len(response_reasoning_content_buffer) > 0 and show_reasoning:
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

        tool_calls_text = tool_calls_content.plain.rstrip()

        # Add compression stats if available (don't clear - caller will clear after final display)
        if compression_manager is not None and compression_manager.stats:
            stats = compression_manager.stats
            saved = stats.get("original_size", 0) - stats.get("compressed_size", 0)
            orig = stats.get("original_size", 1)
            if stats.get("tool_results_compressed", 0) > 0:
                tool_calls_text += f"\n\ncompressed: {stats.get('tool_results_compressed', 0)} | Saved: {saved:,} chars ({saved / orig * 100:.0f}%)"

        tool_calls_panel = create_panel(
            content=tool_calls_text,
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
        md_lines = []

        # Add search queries if present
        if response_event.citations.search_queries:
            md_lines.append("**Search Queries:**")
            for query in response_event.citations.search_queries:
                md_lines.append(f"- {query}")
            md_lines.append("")  # Empty line before URLs

        # Add URL citations
        md_lines.extend(
            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
            for i, citation in enumerate(response_event.citations.urls)
            if citation.url  # Only include citations with valid URLs
        )

        md_content = "\n".join(md_lines)
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
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    stream_events: Optional[bool] = None,
    stream_intermediate_steps: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
    markdown: bool = False,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
    console: Optional[Any] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
):
    if stream_events is not None:
        warnings.warn(
            "The 'stream_events' parameter is deprecated and will be removed in future versions. Event streaming is always enabled using the print_response function.",
            DeprecationWarning,
            stacklevel=2,
        )
    if stream_intermediate_steps is not None:
        warnings.warn(
            "The 'stream_intermediate_steps' parameter is deprecated and will be removed in future versions. Event streaming is always enabled using the print_response function.",
            DeprecationWarning,
            stacklevel=2,
        )

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
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=False,
            stream_events=True,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            dependencies=dependencies,
            metadata=metadata,
            **kwargs,
        )
        response_timer.stop()

        if run_response.input is not None and run_response.input.input_content != input:
            # Input was modified during the run
            panels = [status]
            if show_message:
                # Convert message to a panel
                message_content = get_text_from_message(run_response.input.input_content)
                message_panel = create_panel(
                    content=Text(message_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)  # type: ignore
                live_log.update(Group(*panels))

        additional_panels = build_panels(
            run_response=run_response,
            output_schema=agent.output_schema,  # type: ignore
            response_timer=response_timer,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            markdown=markdown,
            compression_manager=agent.compression_manager,
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
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    debug_mode: Optional[bool] = None,
    markdown: bool = False,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    stream_events: Optional[bool] = None,
    stream_intermediate_steps: Optional[bool] = None,
    tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
    console: Optional[Any] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
):
    if stream_events is not None:
        warnings.warn(
            "The 'stream_events' parameter is deprecated and will be removed in future versions. Event streaming is always enabled using the aprint_response function.",
            DeprecationWarning,
            stacklevel=2,
        )
    if stream_intermediate_steps is not None:
        warnings.warn(
            "The 'stream_intermediate_steps' parameter is deprecated and will be removed in future versions. Event streaming is always enabled using the aprint_response function.",
            DeprecationWarning,
            stacklevel=2,
        )

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
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=False,
            stream_events=True,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            dependencies=dependencies,
            metadata=metadata,
            **kwargs,
        )
        response_timer.stop()

        if run_response.input is not None and run_response.input.input_content != input:
            # Input was modified during the run
            panels = [status]
            if show_message:
                # Convert message to a panel
                message_content = get_text_from_message(run_response.input.input_content)
                message_panel = create_panel(
                    content=Text(message_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)  # type: ignore
                live_log.update(Group(*panels))

        additional_panels = build_panels(
            run_response=run_response,
            output_schema=agent.output_schema,  # type: ignore
            response_timer=response_timer,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            markdown=markdown,
            compression_manager=agent.compression_manager,
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
    compression_manager: Optional[Any] = None,
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

    if isinstance(run_response, RunOutput) and run_response.reasoning_content is not None and show_reasoning:
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

        tool_calls_text = tool_calls_content.plain.rstrip()

        # Add compression stats if available
        if compression_manager is not None and compression_manager.stats:
            stats = compression_manager.stats
            saved = stats.get("original_size", 0) - stats.get("compressed_size", 0)
            orig = stats.get("original_size", 1)
            if stats.get("tool_results_compressed", 0) > 0:
                tool_calls_text += f"\n\ncompressed: {stats.get('tool_results_compressed', 0)} | Saved: {saved:,} chars ({saved / orig * 100:.0f}%)"
            compression_manager.stats.clear()

        tool_calls_panel = create_panel(
            content=tool_calls_text,
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
        elif output_schema is not None and isinstance(run_response.content, dict):
            try:
                response_content_batch = JSON(json.dumps(run_response.content), indent=2)
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
        md_lines = []

        # Add search queries if present
        if run_response.citations.search_queries:
            md_lines.append("**Search Queries:**")
            for query in run_response.citations.search_queries:
                md_lines.append(f"- {query}")
            md_lines.append("")  # Empty line before URLs

        # Add URL citations
        md_lines.extend(
            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
            for i, citation in enumerate(run_response.citations.urls)
            if citation.url  # Only include citations with valid URLs
        )

        md_content = "\n".join(md_lines)
        if md_content:  # Only create panel if there are citations
            citations_panel = create_panel(
                content=Markdown(md_content),
                title="Citations",
                border_style="green",
            )
            panels.append(citations_panel)

    return panels
