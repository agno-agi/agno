from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from pydantic import BaseModel
from rich.console import Group
from rich.live import Live
from rich.markdown import Markdown
from rich.status import Status
from rich.text import Text

from agno.media import Audio, Image, Video
from agno.models.message import Message
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
    StepOutputEvent,
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
    WorkflowStartedEvent,
)
from agno.utils.response import create_panel
from agno.utils.timer import Timer
from agno.workflow.types import StepOutput

if TYPE_CHECKING:
    from agno.workflow.workflow import Workflow


def print_response(
    workflow: "Workflow",
    input: Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    additional_data: Optional[Dict[str, Any]] = None,
    audio: Optional[List[Audio]] = None,
    images: Optional[List[Image]] = None,
    videos: Optional[List[Video]] = None,
    markdown: bool = True,
    show_time: bool = True,
    show_step_details: bool = True,
    console: Optional[Any] = None,
    **kwargs: Any,
) -> None:
    """Print workflow execution with rich formatting (non-streaming)"""
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.status import Status
    from rich.text import Text

    from agno.utils.response import create_panel
    from agno.utils.timer import Timer

    if console is None:
        from rich.console import Console

        console = Console()

    # Show workflow info
    media_info = []
    if audio:
        media_info.append(f"Audio files: {len(audio)}")
    if images:
        media_info.append(f"Images: {len(images)}")
    if videos:
        media_info.append(f"Videos: {len(videos)}")

    workflow_info = f"""**Workflow:** {workflow.name}"""
    if workflow.description:
        workflow_info += f"""\n\n**Description:** {workflow.description}"""
    workflow_info += f"""\n\n**Steps:** {workflow._get_step_count()} steps"""
    if input:
        if isinstance(input, str):
            workflow_info += f"""\n\n**Message:** {input}"""
        else:
            # Handle structured input message
            if isinstance(input, BaseModel):
                data_display = input.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(input, (dict, list)):
                import json

                data_display = json.dumps(input, indent=2, default=str)
            else:
                data_display = str(input)
            workflow_info += f"""\n\n**Structured Input:**\n```json\n{data_display}\n```"""
    if user_id:
        workflow_info += f"""\n\n**User ID:** {user_id}"""
    if session_id:
        workflow_info += f"""\n\n**Session ID:** {session_id}"""
    workflow_info = workflow_info.strip()

    workflow_panel = create_panel(
        content=Markdown(workflow_info) if markdown else workflow_info,
        title="Workflow Information",
        border_style="cyan",
    )
    console.print(workflow_panel)  # type: ignore

    # Start timer
    response_timer = Timer()
    response_timer.start()

    with Live(console=console) as live_log:
        status = Status("Starting workflow...", spinner="dots")
        live_log.update(status)

        try:
            # Execute workflow and get the response directly
            workflow_response: WorkflowRunOutput = workflow.run(
                input=input,
                user_id=user_id,
                session_id=session_id,
                additional_data=additional_data,
                audio=audio,
                images=images,
                videos=videos,
                **kwargs,
            )  # type: ignore

            response_timer.stop()

            if show_step_details and workflow_response.step_results:
                for i, step_output in enumerate(workflow_response.step_results):
                    print_step_output_recursive(step_output, i + 1, markdown, console)  # type: ignore

            # For callable functions, show the content directly since there are no step_results
            elif show_step_details and callable(workflow.steps) and workflow_response.content:
                step_panel = create_panel(
                    content=Markdown(workflow_response.content) if markdown else workflow_response.content,  # type: ignore
                    title="Custom Function (Completed)",
                    border_style="orange3",
                )
                console.print(step_panel)  # type: ignore

            # Show final summary
            if workflow_response.metadata:
                status = workflow_response.status.value  # type: ignore
                summary_content = ""
                summary_content += f"""\n\n**Status:** {status}"""
                summary_content += f"""\n\n**Steps Completed:** {len(workflow_response.step_results) if workflow_response.step_results else 0}"""
                summary_content = summary_content.strip()

                summary_panel = create_panel(
                    content=Markdown(summary_content) if markdown else summary_content,
                    title="Execution Summary",
                    border_style="blue",
                )
                console.print(summary_panel)  # type: ignore

            live_log.update("")

            # Final completion message
            if show_time:
                completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                console.print(completion_text)  # type: ignore

        except Exception as e:
            import traceback

            traceback.print_exc()
            response_timer.stop()
            error_panel = create_panel(
                content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
            )
            console.print(error_panel)  # type: ignore


def print_response_stream(
    workflow: "Workflow",
    input: Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    additional_data: Optional[Dict[str, Any]] = None,
    audio: Optional[List[Audio]] = None,
    images: Optional[List[Image]] = None,
    videos: Optional[List[Video]] = None,
    stream_intermediate_steps: bool = False,
    markdown: bool = True,
    show_time: bool = True,
    show_step_details: bool = True,
    console: Optional[Any] = None,
    **kwargs: Any,
) -> None:
    """Print workflow execution with clean streaming"""
    if console is None:
        from rich.console import Console

        console = Console()

    stream_intermediate_steps = True  # With streaming print response, we need to stream intermediate steps

    # Show workflow info (same as before)
    media_info = []
    if audio:
        media_info.append(f"Audio files: {len(audio)}")
    if images:
        media_info.append(f"Images: {len(images)}")
    if videos:
        media_info.append(f"Videos: {len(videos)}")

    workflow_info = f"""**Workflow:** {workflow.name}"""
    if workflow.description:
        workflow_info += f"""\n\n**Description:** {workflow.description}"""
    workflow_info += f"""\n\n**Steps:** {workflow._get_step_count()} steps"""
    if input:
        if isinstance(input, str):
            workflow_info += f"""\n\n**Message:** {input}"""
        else:
            # Handle structured input message
            if isinstance(input, BaseModel):
                data_display = input.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(input, (dict, list)):
                import json

                data_display = json.dumps(input, indent=2, default=str)
            else:
                data_display = str(input)
            workflow_info += f"""\n\n**Structured Input:**\n```json\n{data_display}\n```"""
    if user_id:
        workflow_info += f"""\n\n**User ID:** {user_id}"""
    if session_id:
        workflow_info += f"""\n\n**Session ID:** {session_id}"""
    workflow_info = workflow_info.strip()

    workflow_panel = create_panel(
        content=Markdown(workflow_info) if markdown else workflow_info,
        title="Workflow Information",
        border_style="cyan",
    )
    console.print(workflow_panel)  # type: ignore

    # Start timer
    response_timer = Timer()
    response_timer.start()

    # Streaming execution variables with smart step tracking
    current_step_content = ""
    current_step_name = ""
    current_step_index = 0
    step_results = []
    step_started_printed = False
    is_callable_function = callable(workflow.steps)

    # Smart step hierarchy tracking
    current_primitive_context = None  # Current primitive being executed (parallel, loop, etc.)
    step_display_cache = {}  # type: ignore

    def get_step_display_number(step_index: Union[int, tuple], step_name: str = "") -> str:
        """Generate clean two-level step numbering: x.y format only"""

        # Handle tuple format for child steps
        if isinstance(step_index, tuple):
            if len(step_index) >= 2:
                parent_idx, sub_idx = step_index[0], step_index[1]

                # Extract base parent index if it's nested
                if isinstance(parent_idx, tuple):
                    base_idx = parent_idx[0] if len(parent_idx) > 0 else 0
                    while isinstance(base_idx, tuple) and len(base_idx) > 0:
                        base_idx = base_idx[0]
                else:
                    base_idx = parent_idx

                # Check context for parallel special case
                if current_primitive_context and current_primitive_context["type"] == "parallel":
                    # For parallel child steps, all get the same number based on their actual step_index
                    return f"Step {base_idx + 1}.{sub_idx + 1}"
                elif current_primitive_context and current_primitive_context["type"] == "loop":
                    iteration = current_primitive_context.get("current_iteration", 1)
                    return f"Step {base_idx + 1}.{sub_idx + 1} (Iteration {iteration})"
                else:
                    # Regular child step numbering
                    return f"Step {base_idx + 1}.{sub_idx + 1}"  # type: ignore
            else:
                # Single element tuple - treat as main step
                return f"Step {step_index[0] + 1}"

        # Handle integer step_index - main step
        if not current_primitive_context:
            # Regular main step
            return f"Step {step_index + 1}"
        else:
            # This shouldn't happen with the new logic, but fallback
            return f"Step {step_index + 1}"

    with Live(console=console, refresh_per_second=10) as live_log:
        status = Status("Starting workflow...", spinner="dots")
        live_log.update(status)

        try:
            for response in workflow.run(
                input=input,
                user_id=user_id,
                session_id=session_id,
                additional_data=additional_data,
                audio=audio,
                images=images,
                videos=videos,
                stream=True,
                stream_intermediate_steps=stream_intermediate_steps,
                **kwargs,
            ):  # type: ignore
                # Handle the new event types
                if isinstance(response, WorkflowStartedEvent):
                    status.update("Workflow started...")
                    if is_callable_function:
                        current_step_name = "Custom Function"
                        current_step_index = 0
                    live_log.update(status)

                elif isinstance(response, StepStartedEvent):
                    current_step_name = response.step_name or "Unknown"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Generate smart step number
                    step_display = get_step_display_number(current_step_index, current_step_name)
                    status.update(f"Starting {step_display}: {current_step_name}...")
                    live_log.update(status)

                elif isinstance(response, StepCompletedEvent):
                    step_name = response.step_name or "Unknown"
                    step_index = response.step_index or 0

                    # Generate smart step number for completion (will use cached value)
                    step_display = get_step_display_number(step_index, step_name)
                    status.update(f"Completed {step_display}: {step_name}")

                    if response.content:
                        step_results.append(
                            {
                                "step_name": step_name,
                                "step_index": step_index,
                                "content": response.content,
                                "event": response.event,
                            }
                        )

                    # Print the final step result in orange (only once)
                    if show_step_details and current_step_content and not step_started_printed:
                        live_log.update(status, refresh=True)

                        final_step_panel = create_panel(
                            content=Markdown(current_step_content) if markdown else current_step_content,
                            title=f"{step_display}: {step_name} (Completed)",
                            border_style="orange3",
                        )
                        console.print(final_step_panel)  # type: ignore
                        step_started_printed = True

                elif isinstance(response, LoopExecutionStartedEvent):
                    current_step_name = response.step_name or "Loop"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Set up loop context
                    current_primitive_context = {
                        "type": "loop",
                        "step_index": current_step_index,
                        "sub_step_counter": 0,
                        "current_iteration": 1,
                        "max_iterations": response.max_iterations,
                    }

                    # Clear cache for this primitive's sub-steps
                    step_display_cache.clear()

                    status.update(f"Starting loop: {current_step_name} (max {response.max_iterations} iterations)...")
                    live_log.update(status)

                elif isinstance(response, LoopIterationStartedEvent):
                    if current_primitive_context and current_primitive_context["type"] == "loop":
                        current_primitive_context["current_iteration"] = response.iteration
                        current_primitive_context["sub_step_counter"] = 0  # Reset for new iteration
                        # Clear cache for new iteration
                        step_display_cache.clear()

                    status.update(
                        f"Loop iteration {response.iteration}/{response.max_iterations}: {response.step_name}..."
                    )
                    live_log.update(status)

                elif isinstance(response, LoopIterationCompletedEvent):
                    status.update(
                        f"Completed iteration {response.iteration}/{response.max_iterations}: {response.step_name}"
                    )

                elif isinstance(response, LoopExecutionCompletedEvent):
                    step_name = response.step_name or "Loop"
                    step_index = response.step_index or 0

                    status.update(f"Completed loop: {step_name} ({response.total_iterations} iterations)")
                    live_log.update(status, refresh=True)

                    # Print loop summary
                    if show_step_details:
                        summary_content = "**Loop Summary:**\n\n"
                        summary_content += (
                            f"- Total iterations: {response.total_iterations}/{response.max_iterations}\n"
                        )
                        summary_content += (
                            f"- Total steps executed: {sum(len(iteration) for iteration in response.all_results)}\n"
                        )

                        loop_summary_panel = create_panel(
                            content=Markdown(summary_content) if markdown else summary_content,
                            title=f"Loop {step_name} (Completed)",
                            border_style="yellow",
                        )
                        console.print(loop_summary_panel)  # type: ignore

                    # Reset context
                    current_primitive_context = None
                    step_display_cache.clear()
                    step_started_printed = True

                elif isinstance(response, ParallelExecutionStartedEvent):
                    current_step_name = response.step_name or "Parallel Steps"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Set up parallel context
                    current_primitive_context = {
                        "type": "parallel",
                        "step_index": current_step_index,
                        "sub_step_counter": 0,
                        "total_steps": response.parallel_step_count,
                    }

                    # Clear cache for this primitive's sub-steps
                    step_display_cache.clear()

                    # Print parallel execution summary panel
                    live_log.update(status, refresh=True)
                    parallel_summary = f"**Parallel Steps:** {response.parallel_step_count}"
                    # Use get_step_display_number for consistent numbering
                    step_display = get_step_display_number(current_step_index, current_step_name)
                    parallel_panel = create_panel(
                        content=Markdown(parallel_summary) if markdown else parallel_summary,
                        title=f"{step_display}: {current_step_name}",
                        border_style="cyan",
                    )
                    console.print(parallel_panel)  # type: ignore

                    status.update(
                        f"Starting parallel execution: {current_step_name} ({response.parallel_step_count} steps)..."
                    )
                    live_log.update(status)

                elif isinstance(response, ParallelExecutionCompletedEvent):
                    step_name = response.step_name or "Parallel Steps"
                    step_index = response.step_index or 0

                    status.update(f"Completed parallel execution: {step_name}")

                    # Reset context
                    current_primitive_context = None
                    step_display_cache.clear()

                elif isinstance(response, ConditionExecutionStartedEvent):
                    current_step_name = response.step_name or "Condition"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Set up condition context
                    current_primitive_context = {
                        "type": "condition",
                        "step_index": current_step_index,
                        "sub_step_counter": 0,
                        "condition_result": response.condition_result,
                    }

                    # Clear cache for this primitive's sub-steps
                    step_display_cache.clear()

                    condition_text = "met" if response.condition_result else "not met"
                    status.update(f"Starting condition: {current_step_name} (condition {condition_text})...")
                    live_log.update(status)

                elif isinstance(response, ConditionExecutionCompletedEvent):
                    step_name = response.step_name or "Condition"
                    step_index = response.step_index or 0

                    status.update(f"Completed condition: {step_name}")

                    # Reset context
                    current_primitive_context = None
                    step_display_cache.clear()

                elif isinstance(response, RouterExecutionStartedEvent):
                    current_step_name = response.step_name or "Router"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Set up router context
                    current_primitive_context = {
                        "type": "router",
                        "step_index": current_step_index,
                        "sub_step_counter": 0,
                        "selected_steps": response.selected_steps,
                    }

                    # Clear cache for this primitive's sub-steps
                    step_display_cache.clear()

                    selected_steps_text = ", ".join(response.selected_steps) if response.selected_steps else "none"
                    status.update(f"Starting router: {current_step_name} (selected: {selected_steps_text})...")
                    live_log.update(status)

                elif isinstance(response, RouterExecutionCompletedEvent):
                    step_name = response.step_name or "Router"
                    step_index = response.step_index or 0

                    status.update(f"Completed router: {step_name}")

                    # Print router summary
                    if show_step_details:
                        selected_steps_text = ", ".join(response.selected_steps) if response.selected_steps else "none"
                        summary_content = "**Router Summary:**\n\n"
                        summary_content += f"- Selected steps: {selected_steps_text}\n"
                        summary_content += f"- Executed steps: {response.executed_steps or 0}\n"

                        router_summary_panel = create_panel(
                            content=Markdown(summary_content) if markdown else summary_content,
                            title=f"Router {step_name} (Completed)",
                            border_style="purple",
                        )
                        console.print(router_summary_panel)  # type: ignore

                    # Reset context
                    current_primitive_context = None
                    step_display_cache.clear()
                    step_started_printed = True

                elif isinstance(response, StepsExecutionStartedEvent):
                    current_step_name = response.step_name or "Steps"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False
                    status.update(f"Starting steps: {current_step_name} ({response.steps_count} steps)...")
                    live_log.update(status)

                elif isinstance(response, StepsExecutionCompletedEvent):
                    step_name = response.step_name or "Steps"
                    step_index = response.step_index or 0

                    status.update(f"Completed steps: {step_name}")

                    # Add results from executed steps to step_results
                    if response.step_results:
                        for i, step_result in enumerate(response.step_results):
                            # Use the same numbering system as other primitives
                            step_display_number = get_step_display_number(step_index, step_result.step_name or "")
                            step_results.append(
                                {
                                    "step_name": f"{step_display_number}: {step_result.step_name}",
                                    "step_index": step_index,
                                    "content": step_result.content,
                                    "event": "StepsStepResult",
                                }
                            )

                    # Print steps summary
                    if show_step_details:
                        summary_content = "**Steps Summary:**\n\n"
                        summary_content += f"- Total steps: {response.steps_count or 0}\n"
                        summary_content += f"- Executed steps: {response.executed_steps or 0}\n"

                        steps_summary_panel = create_panel(
                            content=Markdown(summary_content) if markdown else summary_content,
                            title=f"Steps {step_name} (Completed)",
                            border_style="yellow",
                        )
                        console.print(steps_summary_panel)  # type: ignore

                    step_started_printed = True

                elif isinstance(response, WorkflowCompletedEvent):
                    status.update("Workflow completed!")

                    # For callable functions, print the final content block here since there are no step events
                    if is_callable_function and show_step_details and current_step_content and not step_started_printed:
                        final_step_panel = create_panel(
                            content=Markdown(current_step_content) if markdown else current_step_content,
                            title="Custom Function (Completed)",
                            border_style="orange3",
                        )
                        console.print(final_step_panel)  # type: ignore
                        step_started_printed = True

                    live_log.update(status, refresh=True)

                    # Show final summary
                    if response.metadata:
                        status = response.status
                        summary_content = ""
                        summary_content += f"""\n\n**Status:** {status}"""
                        summary_content += (
                            f"""\n\n**Steps Completed:** {len(response.step_results) if response.step_results else 0}"""
                        )
                        summary_content = summary_content.strip()

                        summary_panel = create_panel(
                            content=Markdown(summary_content) if markdown else summary_content,
                            title="Execution Summary",
                            border_style="blue",
                        )
                        console.print(summary_panel)  # type: ignore

                else:
                    # Handle streaming content
                    if isinstance(response, str):
                        response_str = response
                    elif isinstance(response, StepOutputEvent):
                        response_str = response.content or ""  # type: ignore
                    else:
                        from agno.run.agent import RunContentEvent
                        from agno.run.team import RunContentEvent as TeamRunContentEvent

                        current_step_executor_type = None
                        # Handle both integer and tuple step indices for parallel execution
                        actual_step_index = current_step_index
                        if isinstance(current_step_index, tuple):
                            # For tuple indices, use the first element (parent step index)
                            actual_step_index = current_step_index[0]
                            # If it's nested tuple, keep extracting until we get an integer
                            while isinstance(actual_step_index, tuple) and len(actual_step_index) > 0:
                                actual_step_index = actual_step_index[0]

                        if not is_callable_function and workflow.steps and actual_step_index < len(workflow.steps):  # type: ignore
                            step = workflow.steps[actual_step_index]  # type: ignore
                            if hasattr(step, "executor_type"):
                                current_step_executor_type = step.executor_type

                        # Check if this is a streaming content event from agent or team
                        if isinstance(response, (TeamRunContentEvent, WorkflowRunOutputEvent)):  # type: ignore
                            # Check if this is a team's final structured output
                            is_structured_output = (
                                isinstance(response, TeamRunContentEvent)
                                and hasattr(response, "content_type")
                                and response.content_type != "str"
                                and response.content_type != ""
                            )
                            response_str = response.content  # type: ignore
                        elif isinstance(response, RunContentEvent) and current_step_executor_type != "team":
                            response_str = response.content  # type: ignore
                        else:
                            continue

                    # Use the unified formatting function for consistency
                    response_str = format_step_content_for_display(response_str)  # type: ignore

                    # Filter out empty responses and add to current step content
                    if response_str and response_str.strip():
                        # If it's a structured output from a team, replace the content instead of appending
                        if "is_structured_output" in locals() and is_structured_output:
                            current_step_content = response_str
                        else:
                            current_step_content += response_str

                        # Live update the step panel with streaming content
                        if show_step_details and not step_started_printed:
                            # Generate smart step number for streaming title (will use cached value)
                            step_display = get_step_display_number(current_step_index, current_step_name)
                            title = f"{step_display}: {current_step_name} (Streaming...)"
                            if is_callable_function:
                                title = "Custom Function (Streaming...)"

                            # Show the streaming content live in orange panel
                            live_step_panel = create_panel(
                                content=Markdown(current_step_content) if markdown else current_step_content,
                                title=title,
                                border_style="orange3",
                            )

                            # Create group with status and current step content
                            group = Group(status, live_step_panel)
                            live_log.update(group)

            response_timer.stop()

            live_log.update("")

            # Final completion message
            if show_time:
                completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                console.print(completion_text)  # type: ignore

        except Exception as e:
            import traceback

            traceback.print_exc()
            response_timer.stop()
            error_panel = create_panel(
                content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
            )
            console.print(error_panel)  # type: ignore


def print_step_output_recursive(
    step_output: StepOutput, step_number: int, markdown: bool, console, depth: int = 0
) -> None:
    """Recursively print step output and its nested steps"""
    from rich.markdown import Markdown

    from agno.utils.response import create_panel

    # Print the current step
    if step_output.content:
        formatted_content = format_step_content_for_display(step_output)

        # Create title with proper nesting indication
        if depth == 0:
            title = f"Step {step_number}: {step_output.step_name} (Completed)"
        else:
            title = f"{'  ' * depth}└─ {step_output.step_name} (Completed)"

        step_panel = create_panel(
            content=Markdown(formatted_content) if markdown else formatted_content,
            title=title,
            border_style="orange3",
        )
        console.print(step_panel)

    # Print nested steps if they exist
    if step_output.steps:
        for j, nested_step in enumerate(step_output.steps):
            print_step_output_recursive(nested_step, j + 1, markdown, console, depth + 1)


def format_step_content_for_display(step_output: StepOutput) -> str:
    """Format content for display, handling structured outputs. Works for both raw content and StepOutput objects."""
    # If it's a StepOutput, extract the content
    if hasattr(step_output, "content"):
        actual_content = step_output.content
    else:
        actual_content = step_output

    if not actual_content:
        return ""

    # If it's already a string, return as-is
    if isinstance(actual_content, str):
        return actual_content

    # If it's a structured output (BaseModel or dict), format it nicely
    if isinstance(actual_content, BaseModel):
        return f"**Structured Output:**\n\n```json\n{actual_content.model_dump_json(indent=2, exclude_none=True)}\n```"
    elif isinstance(actual_content, (dict, list)):
        import json

        return f"**Structured Output:**\n\n```json\n{json.dumps(actual_content, indent=2, default=str)}\n```"
    else:
        # Fallback to string conversion
        return str(actual_content)


async def aprint_response(
    workflow: "Workflow",
    input: Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]],
    additional_data: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    audio: Optional[List[Audio]] = None,
    images: Optional[List[Image]] = None,
    videos: Optional[List[Video]] = None,
    markdown: bool = True,
    show_time: bool = True,
    show_step_details: bool = True,
    console: Optional[Any] = None,
    **kwargs: Any,
) -> None:
    """Print workflow execution with rich formatting (non-streaming)"""
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.status import Status
    from rich.text import Text

    from agno.utils.response import create_panel
    from agno.utils.timer import Timer

    if console is None:
        from rich.console import Console

        console = Console()

    # Show workflow info
    media_info = []
    if audio:
        media_info.append(f"Audio files: {len(audio)}")
    if images:
        media_info.append(f"Images: {len(images)}")
    if videos:
        media_info.append(f"Videos: {len(videos)}")

    workflow_info = f"""**Workflow:** {workflow.name}"""
    if workflow.description:
        workflow_info += f"""\n\n**Description:** {workflow.description}"""
    workflow_info += f"""\n\n**Steps:** {workflow._get_step_count()} steps"""
    if input:
        if isinstance(input, str):
            workflow_info += f"""\n\n**Message:** {input}"""
        else:
            # Handle structured input message
            if isinstance(input, BaseModel):
                data_display = input.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(input, (dict, list)):
                import json

                data_display = json.dumps(input, indent=2, default=str)
            else:
                data_display = str(input)
            workflow_info += f"""\n\n**Structured Input:**\n```json\n{data_display}\n```"""
    if user_id:
        workflow_info += f"""\n\n**User ID:** {user_id}"""
    if session_id:
        workflow_info += f"""\n\n**Session ID:** {session_id}"""
    workflow_info = workflow_info.strip()

    workflow_panel = create_panel(
        content=Markdown(workflow_info) if markdown else workflow_info,
        title="Workflow Information",
        border_style="cyan",
    )
    console.print(workflow_panel)  # type: ignore

    # Start timer
    response_timer = Timer()
    response_timer.start()

    with Live(console=console) as live_log:
        status = Status("Starting async workflow...\n", spinner="dots")
        live_log.update(status)

        try:
            # Execute workflow and get the response directly
            workflow_response: WorkflowRunOutput = await workflow.arun(
                input=input,
                user_id=user_id,
                session_id=session_id,
                additional_data=additional_data,
                audio=audio,
                images=images,
                videos=videos,
                **kwargs,
            )  # type: ignore

            response_timer.stop()

            if show_step_details and workflow_response.step_results:
                for i, step_output in enumerate(workflow_response.step_results):
                    print_step_output_recursive(step_output, i + 1, markdown, console)  # type: ignore

            # For callable functions, show the content directly since there are no step_results
            elif show_step_details and callable(workflow.steps) and workflow_response.content:
                step_panel = create_panel(
                    content=Markdown(workflow_response.content) if markdown else workflow_response.content,  # type: ignore
                    title="Custom Function (Completed)",
                    border_style="orange3",
                )
                console.print(step_panel)  # type: ignore

            # Show final summary
            if workflow_response.metadata:
                status = workflow_response.status.value  # type: ignore
                summary_content = ""
                summary_content += f"""\n\n**Status:** {status}"""
                summary_content += f"""\n\n**Steps Completed:** {len(workflow_response.step_results) if workflow_response.step_results else 0}"""
                summary_content = summary_content.strip()

                summary_panel = create_panel(
                    content=Markdown(summary_content) if markdown else summary_content,
                    title="Execution Summary",
                    border_style="blue",
                )
                console.print(summary_panel)  # type: ignore

            live_log.update("")

            # Final completion message
            if show_time:
                completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                console.print(completion_text)  # type: ignore

        except Exception as e:
            import traceback

            traceback.print_exc()
            response_timer.stop()
            error_panel = create_panel(
                content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
            )
            console.print(error_panel)  # type: ignore


async def aprint_response_stream(
    workflow: "Workflow",
    input: Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]],
    additional_data: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    audio: Optional[List[Audio]] = None,
    images: Optional[List[Image]] = None,
    videos: Optional[List[Video]] = None,
    stream_intermediate_steps: bool = False,
    markdown: bool = True,
    show_time: bool = True,
    show_step_details: bool = True,
    console: Optional[Any] = None,
    **kwargs: Any,
) -> None:
    """Print workflow execution with clean streaming - orange step blocks displayed once"""
    if console is None:
        from rich.console import Console

        console = Console()

    stream_intermediate_steps = True  # With streaming print response, we need to stream intermediate steps

    # Show workflow info (same as before)
    media_info = []
    if audio:
        media_info.append(f"Audio files: {len(audio)}")
    if images:
        media_info.append(f"Images: {len(images)}")
    if videos:
        media_info.append(f"Videos: {len(videos)}")

    workflow_info = f"""**Workflow:** {workflow.name}"""
    if workflow.description:
        workflow_info += f"""\n\n**Description:** {workflow.description}"""
    workflow_info += f"""\n\n**Steps:** {workflow._get_step_count()} steps"""
    if input:
        if isinstance(input, str):
            workflow_info += f"""\n\n**Message:** {input}"""
        else:
            # Handle structured input message
            if isinstance(input, BaseModel):
                data_display = input.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(input, (dict, list)):
                import json

                data_display = json.dumps(input, indent=2, default=str)
            else:
                data_display = str(input)
            workflow_info += f"""\n\n**Structured Input:**\n```json\n{data_display}\n```"""
    if user_id:
        workflow_info += f"""\n\n**User ID:** {user_id}"""
    if session_id:
        workflow_info += f"""\n\n**Session ID:** {session_id}"""
    workflow_info = workflow_info.strip()

    workflow_panel = create_panel(
        content=Markdown(workflow_info) if markdown else workflow_info,
        title="Workflow Information",
        border_style="cyan",
    )
    console.print(workflow_panel)  # type: ignore

    # Start timer
    response_timer = Timer()
    response_timer.start()

    # Streaming execution variables
    current_step_content = ""
    current_step_name = ""
    current_step_index = 0
    step_results = []
    step_started_printed = False
    is_callable_function = callable(workflow.steps)

    # Smart step hierarchy tracking
    current_primitive_context = None  # Current primitive being executed (parallel, loop, etc.)
    step_display_cache = {}  # type: ignore

    def get_step_display_number(step_index: Union[int, tuple], step_name: str = "") -> str:
        """Generate clean two-level step numbering: x.y format only"""

        # Handle tuple format for child steps
        if isinstance(step_index, tuple):
            if len(step_index) >= 2:
                parent_idx, sub_idx = step_index[0], step_index[1]

                # Extract base parent index if it's nested
                if isinstance(parent_idx, tuple):
                    base_idx = parent_idx[0] if len(parent_idx) > 0 else 0
                    while isinstance(base_idx, tuple) and len(base_idx) > 0:
                        base_idx = base_idx[0]
                else:
                    base_idx = parent_idx

                # Check context for parallel special case
                if current_primitive_context and current_primitive_context["type"] == "parallel":
                    # For parallel child steps, all get the same number based on their actual step_index
                    return f"Step {base_idx + 1}.{sub_idx + 1}"
                elif current_primitive_context and current_primitive_context["type"] == "loop":
                    iteration = current_primitive_context.get("current_iteration", 1)
                    return f"Step {base_idx + 1}.{sub_idx + 1} (Iteration {iteration})"
                else:
                    # Regular child step numbering
                    return f"Step {base_idx + 1}.{sub_idx + 1}"  # type: ignore
            else:
                # Single element tuple - treat as main step
                return f"Step {step_index[0] + 1}"

        # Handle integer step_index - main step
        if not current_primitive_context:
            # Regular main step
            return f"Step {step_index + 1}"
        else:
            # This shouldn't happen with the new logic, but fallback
            return f"Step {step_index + 1}"

    with Live(console=console, refresh_per_second=10) as live_log:
        status = Status("Starting async workflow...", spinner="dots")
        live_log.update(status)

        try:
            async for response in await workflow.arun(
                input=input,
                additional_data=additional_data,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                stream=True,
                stream_intermediate_steps=stream_intermediate_steps,
                **kwargs,
            ):  # type: ignore
                # Handle the new event types
                if isinstance(response, WorkflowStartedEvent):
                    status.update("Workflow started...")
                    if is_callable_function:
                        current_step_name = "Custom Function"
                        current_step_index = 0
                    live_log.update(status)

                elif isinstance(response, StepStartedEvent):
                    current_step_name = response.step_name or "Unknown"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Generate smart step number
                    step_display = get_step_display_number(current_step_index, current_step_name)
                    status.update(f"Starting {step_display}: {current_step_name}...")
                    live_log.update(status)

                elif isinstance(response, StepCompletedEvent):
                    step_name = response.step_name or "Unknown"
                    step_index = response.step_index or 0

                    # Generate smart step number for completion (will use cached value)
                    step_display = get_step_display_number(step_index, step_name)
                    status.update(f"Completed {step_display}: {step_name}")

                    if response.content:
                        step_results.append(
                            {
                                "step_name": step_name,
                                "step_index": step_index,
                                "content": response.content,
                                "event": response.event,
                            }
                        )

                    # Print the final step result in orange (only once)
                    if show_step_details and current_step_content and not step_started_printed:
                        live_log.update(status, refresh=True)

                        final_step_panel = create_panel(
                            content=Markdown(current_step_content) if markdown else current_step_content,
                            title=f"{step_display}: {step_name} (Completed)",
                            border_style="orange3",
                        )
                        console.print(final_step_panel)  # type: ignore
                        step_started_printed = True

                elif isinstance(response, LoopExecutionStartedEvent):
                    current_step_name = response.step_name or "Loop"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Set up loop context
                    current_primitive_context = {
                        "type": "loop",
                        "step_index": current_step_index,
                        "sub_step_counter": 0,
                        "current_iteration": 1,
                        "max_iterations": response.max_iterations,
                    }

                    # Clear cache for this primitive's sub-steps
                    step_display_cache.clear()

                    status.update(f"Starting loop: {current_step_name} (max {response.max_iterations} iterations)...")
                    live_log.update(status)

                elif isinstance(response, LoopIterationStartedEvent):
                    if current_primitive_context and current_primitive_context["type"] == "loop":
                        current_primitive_context["current_iteration"] = response.iteration
                        current_primitive_context["sub_step_counter"] = 0  # Reset for new iteration
                        # Clear cache for new iteration
                        step_display_cache.clear()

                    status.update(
                        f"Loop iteration {response.iteration}/{response.max_iterations}: {response.step_name}..."
                    )
                    live_log.update(status)

                elif isinstance(response, LoopIterationCompletedEvent):
                    status.update(
                        f"Completed iteration {response.iteration}/{response.max_iterations}: {response.step_name}"
                    )

                elif isinstance(response, LoopExecutionCompletedEvent):
                    step_name = response.step_name or "Loop"
                    step_index = response.step_index or 0

                    status.update(f"Completed loop: {step_name} ({response.total_iterations} iterations)")
                    live_log.update(status, refresh=True)

                    # Print loop summary
                    if show_step_details:
                        summary_content = "**Loop Summary:**\n\n"
                        summary_content += (
                            f"- Total iterations: {response.total_iterations}/{response.max_iterations}\n"
                        )
                        summary_content += (
                            f"- Total steps executed: {sum(len(iteration) for iteration in response.all_results)}\n"
                        )

                        loop_summary_panel = create_panel(
                            content=Markdown(summary_content) if markdown else summary_content,
                            title=f"Loop {step_name} (Completed)",
                            border_style="yellow",
                        )
                        console.print(loop_summary_panel)  # type: ignore

                    # Reset context
                    current_primitive_context = None
                    step_display_cache.clear()
                    step_started_printed = True

                elif isinstance(response, ParallelExecutionStartedEvent):
                    current_step_name = response.step_name or "Parallel Steps"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Set up parallel context
                    current_primitive_context = {
                        "type": "parallel",
                        "step_index": current_step_index,
                        "sub_step_counter": 0,
                        "total_steps": response.parallel_step_count,
                    }

                    # Clear cache for this primitive's sub-steps
                    step_display_cache.clear()

                    # Print parallel execution summary panel
                    live_log.update(status, refresh=True)
                    parallel_summary = f"**Parallel Steps:** {response.parallel_step_count}"
                    # Use get_step_display_number for consistent numbering
                    step_display = get_step_display_number(current_step_index, current_step_name)
                    parallel_panel = create_panel(
                        content=Markdown(parallel_summary) if markdown else parallel_summary,
                        title=f"{step_display}: {current_step_name}",
                        border_style="cyan",
                    )
                    console.print(parallel_panel)  # type: ignore

                    status.update(
                        f"Starting parallel execution: {current_step_name} ({response.parallel_step_count} steps)..."
                    )
                    live_log.update(status)

                elif isinstance(response, ParallelExecutionCompletedEvent):
                    step_name = response.step_name or "Parallel Steps"
                    step_index = response.step_index or 0

                    status.update(f"Completed parallel execution: {step_name}")

                    # Reset context
                    current_primitive_context = None
                    step_display_cache.clear()

                elif isinstance(response, ConditionExecutionStartedEvent):
                    current_step_name = response.step_name or "Condition"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Set up condition context
                    current_primitive_context = {
                        "type": "condition",
                        "step_index": current_step_index,
                        "sub_step_counter": 0,
                        "condition_result": response.condition_result,
                    }

                    # Clear cache for this primitive's sub-steps
                    step_display_cache.clear()

                    condition_text = "met" if response.condition_result else "not met"
                    status.update(f"Starting condition: {current_step_name} (condition {condition_text})...")
                    live_log.update(status)

                elif isinstance(response, ConditionExecutionCompletedEvent):
                    step_name = response.step_name or "Condition"
                    step_index = response.step_index or 0

                    status.update(f"Completed condition: {step_name}")

                    # Reset context
                    current_primitive_context = None
                    step_display_cache.clear()

                elif isinstance(response, RouterExecutionStartedEvent):
                    current_step_name = response.step_name or "Router"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False

                    # Set up router context
                    current_primitive_context = {
                        "type": "router",
                        "step_index": current_step_index,
                        "sub_step_counter": 0,
                        "selected_steps": response.selected_steps,
                    }

                    # Clear cache for this primitive's sub-steps
                    step_display_cache.clear()

                    selected_steps_text = ", ".join(response.selected_steps) if response.selected_steps else "none"
                    status.update(f"Starting router: {current_step_name} (selected: {selected_steps_text})...")
                    live_log.update(status)

                elif isinstance(response, RouterExecutionCompletedEvent):
                    step_name = response.step_name or "Router"
                    step_index = response.step_index or 0

                    status.update(f"Completed router: {step_name}")

                    # Print router summary
                    if show_step_details:
                        selected_steps_text = ", ".join(response.selected_steps) if response.selected_steps else "none"
                        summary_content = "**Router Summary:**\n\n"
                        summary_content += f"- Selected steps: {selected_steps_text}\n"
                        summary_content += f"- Executed steps: {response.executed_steps or 0}\n"

                        router_summary_panel = create_panel(
                            content=Markdown(summary_content) if markdown else summary_content,
                            title=f"Router {step_name} (Completed)",
                            border_style="purple",
                        )
                        console.print(router_summary_panel)  # type: ignore

                    # Reset context
                    current_primitive_context = None
                    step_display_cache.clear()
                    step_started_printed = True

                elif isinstance(response, StepsExecutionStartedEvent):
                    current_step_name = response.step_name or "Steps"
                    current_step_index = response.step_index or 0  # type: ignore
                    current_step_content = ""
                    step_started_printed = False
                    status.update(f"Starting steps: {current_step_name} ({response.steps_count} steps)...")
                    live_log.update(status)

                elif isinstance(response, StepsExecutionCompletedEvent):
                    step_name = response.step_name or "Steps"
                    step_index = response.step_index or 0

                    status.update(f"Completed steps: {step_name}")

                    # Add results from executed steps to step_results
                    if response.step_results:
                        for i, step_result in enumerate(response.step_results):
                            # Use the same numbering system as other primitives
                            step_display_number = get_step_display_number(step_index, step_result.step_name or "")
                            step_results.append(
                                {
                                    "step_name": f"{step_display_number}: {step_result.step_name}",
                                    "step_index": step_index,
                                    "content": step_result.content,
                                    "event": "StepsStepResult",
                                }
                            )

                    # Print steps summary
                    if show_step_details:
                        summary_content = "**Steps Summary:**\n\n"
                        summary_content += f"- Total steps: {response.steps_count or 0}\n"
                        summary_content += f"- Executed steps: {response.executed_steps or 0}\n"

                        steps_summary_panel = create_panel(
                            content=Markdown(summary_content) if markdown else summary_content,
                            title=f"Steps {step_name} (Completed)",
                            border_style="yellow",
                        )
                        console.print(steps_summary_panel)  # type: ignore

                    step_started_printed = True

                elif isinstance(response, WorkflowCompletedEvent):
                    status.update("Workflow completed!")

                    # For callable functions, print the final content block here since there are no step events
                    if is_callable_function and show_step_details and current_step_content and not step_started_printed:
                        final_step_panel = create_panel(
                            content=Markdown(current_step_content) if markdown else current_step_content,
                            title="Custom Function (Completed)",
                            border_style="orange3",
                        )
                        console.print(final_step_panel)  # type: ignore
                        step_started_printed = True

                    live_log.update(status, refresh=True)

                    # Show final summary
                    if response.metadata:
                        status = response.status
                        summary_content = ""
                        summary_content += f"""\n\n**Status:** {status}"""
                        summary_content += (
                            f"""\n\n**Steps Completed:** {len(response.step_results) if response.step_results else 0}"""
                        )
                        summary_content = summary_content.strip()

                        summary_panel = create_panel(
                            content=Markdown(summary_content) if markdown else summary_content,
                            title="Execution Summary",
                            border_style="blue",
                        )
                        console.print(summary_panel)  # type: ignore

                else:
                    if isinstance(response, str):
                        response_str = response
                    elif isinstance(response, StepOutputEvent):
                        # Handle StepOutputEvent objects yielded from workflow
                        response_str = response.content or ""  # type: ignore
                    else:
                        from agno.run.agent import RunContentEvent
                        from agno.run.team import RunContentEvent as TeamRunContentEvent

                        current_step_executor_type = None
                        # Handle both integer and tuple step indices for parallel execution
                        actual_step_index = current_step_index
                        if isinstance(current_step_index, tuple):
                            # For tuple indices, use the first element (parent step index)
                            actual_step_index = current_step_index[0]
                            # If it's nested tuple, keep extracting until we get an integer
                            while isinstance(actual_step_index, tuple) and len(actual_step_index) > 0:
                                actual_step_index = actual_step_index[0]

                        # Check if this is a streaming content event from agent or team
                        if isinstance(
                            response,
                            (RunContentEvent, TeamRunContentEvent, WorkflowRunOutputEvent),  # type: ignore
                        ):  # type: ignore
                            # Handle WorkflowErrorEvent specifically
                            if isinstance(response, WorkflowErrorEvent):  # type: ignore
                                response_str = response.error or "Workflow execution error"  # type: ignore
                            else:
                                # Extract the content from the streaming event
                                response_str = response.content  # type: ignore

                                # Check if this is a team's final structured output
                                is_structured_output = (
                                    isinstance(response, TeamRunContentEvent)
                                    and hasattr(response, "content_type")
                                    and response.content_type != "str"
                                    and response.content_type != ""
                                )
                        elif isinstance(response, RunContentEvent) and current_step_executor_type != "team":
                            response_str = response.content  # type: ignore
                        else:
                            continue

                    # Use the unified formatting function for consistency
                    response_str = format_step_content_for_display(response_str)  # type: ignore

                    # Filter out empty responses and add to current step content
                    if response_str and response_str.strip():
                        # If it's a structured output from a team, replace the content instead of appending
                        if "is_structured_output" in locals() and is_structured_output:
                            current_step_content = response_str
                        else:
                            current_step_content += response_str

                        # Live update the step panel with streaming content
                        if show_step_details and not step_started_printed:
                            # Generate smart step number for streaming title (will use cached value)
                            step_display = get_step_display_number(current_step_index, current_step_name)
                            title = f"{step_display}: {current_step_name} (Streaming...)"
                            if is_callable_function:
                                title = "Custom Function (Streaming...)"

                            # Show the streaming content live in orange panel
                            live_step_panel = create_panel(
                                content=Markdown(current_step_content) if markdown else current_step_content,
                                title=title,
                                border_style="orange3",
                            )

                            # Create group with status and current step content
                            group = Group(status, live_step_panel)
                            live_log.update(group)

            response_timer.stop()

            live_log.update("")

            # Final completion message
            if show_time:
                completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                console.print(completion_text)  # type: ignore

        except Exception as e:
            import traceback

            traceback.print_exc()
            response_timer.stop()
            error_panel = create_panel(
                content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
            )
            console.print(error_panel)  # type: ignore
