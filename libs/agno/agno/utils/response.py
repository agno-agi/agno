from typing import List, Set, Union

from agno.exceptions import RunCancelledException
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunOutput, RunOutputEvent, RunPausedEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent


def create_panel(content, title, border_style="blue"):
    from rich.box import HEAVY
    from rich.panel import Panel

    return Panel(
        content, title=title, title_align="left", border_style=border_style, box=HEAVY, expand=True, padding=(1, 1)
    )


def build_reasoning_step_panel(
    step_idx: int, step: ReasoningStep, show_full_reasoning: bool = False, color: str = "green"
):
    from rich.text import Text

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
    return create_panel(content=step_content, title=f"Reasoning step {step_idx}", border_style=color)


def escape_markdown_tags(content: str, tags: Set[str]) -> str:
    """Escape special tags in markdown content."""
    escaped_content = content
    for tag in tags:
        # Escape opening tag
        escaped_content = escaped_content.replace(f"<{tag}>", f"&lt;{tag}&gt;")
        # Escape closing tag
        escaped_content = escaped_content.replace(f"</{tag}>", f"&lt;/{tag}&gt;")
    return escaped_content


def check_if_run_cancelled(run_output: Union[RunOutput, RunOutputEvent, TeamRunOutput, TeamRunOutputEvent]):
    if run_output.is_cancelled:
        raise RunCancelledException()


def format_tool_calls(tool_calls: List[ToolExecution]) -> List[str]:
    """Format tool calls for display in a readable format.

    Args:
        tool_calls: List of tool call dictionaries containing tool_name and tool_args

    Returns:
        List[str]: List of formatted tool call strings
    """
    formatted_tool_calls = []

    for tool_call in tool_calls:
        if tool_call.tool_name is not None:
            tool_name = tool_call.tool_name
            args_str = ""
            if tool_call.tool_args is not None and tool_call.tool_args:  # Check if args exist and are non-empty
                args_str = ", ".join(f"{k}={v}" for k, v in tool_call.tool_args.items())
            formatted_tool_calls.append(f"{tool_name}({args_str})")

    return formatted_tool_calls


def create_paused_run_output_panel(run_output: Union[RunPausedEvent, RunOutput]):
    from rich.text import Text

    # Filter out silent tools - they don't produce verbose output
    non_silent_tools = [tc for tc in (run_output.tools or []) if not tc.external_execution_silent]

    # If all tools are silent, return None to indicate no panel should be shown
    if not non_silent_tools:
        return None

    tool_calls_content = Text("Run is paused. ")
    if any(tc.requires_confirmation for tc in non_silent_tools):
        tool_calls_content.append("The following tool calls require confirmation:\n")
    for tool_call in non_silent_tools:
        if tool_call.requires_confirmation:
            args_str = ""
            for arg, value in tool_call.tool_args.items() if tool_call.tool_args else {}:
                args_str += f"{arg}={value}, "
            args_str = args_str.rstrip(", ")
            tool_calls_content.append(f"• {tool_call.tool_name}({args_str})\n")
    if any(tc.requires_user_input for tc in non_silent_tools):
        tool_calls_content.append("The following tool calls require user input:\n")
    for tool_call in non_silent_tools:
        if tool_call.requires_user_input:
            args_str = ""
            for arg, value in tool_call.tool_args.items() if tool_call.tool_args else {}:
                args_str += f"{arg}={value}, "
            args_str = args_str.rstrip(", ")
            tool_calls_content.append(f"• {tool_call.tool_name}({args_str})\n")
    if any(tc.external_execution_required for tc in non_silent_tools):
        tool_calls_content.append("The following tool calls require external execution:\n")
    for tool_call in non_silent_tools:
        if tool_call.external_execution_required:
            args_str = ""
            for arg, value in tool_call.tool_args.items() if tool_call.tool_args else {}:
                args_str += f"{arg}={value}, "
            args_str = args_str.rstrip(", ")
            tool_calls_content.append(f"• {tool_call.tool_name}({args_str})\n")

    # Create panel for response
    response_panel = create_panel(
        content=tool_calls_content,
        title="Run Paused",
        border_style="blue",
    )
    return response_panel


def get_paused_content(run_output: RunOutput) -> str:
    paused_content = ""
    for tool in run_output.tools or []:
        # Skip silent tools - they don't produce verbose paused messages
        if tool.external_execution_silent:
            continue

        # Initialize flags for each tool
        confirmation_required = False
        user_input_required = False
        external_execution_required = False

        if tool.requires_confirmation is not None and tool.requires_confirmation is True and not tool.confirmed:
            confirmation_required = True
        if tool.requires_user_input is not None and tool.requires_user_input is True:
            user_input_required = True
        if tool.external_execution_required is not None and tool.external_execution_required is True:
            external_execution_required = True

        if confirmation_required and user_input_required and external_execution_required:
            paused_content = "I have tools to execute, but I need confirmation, user input, or external execution."
        elif confirmation_required and user_input_required:
            paused_content = "I have tools to execute, but I need confirmation or user input."
        elif confirmation_required and external_execution_required:
            paused_content = "I have tools to execute, but I need confirmation or external execution."
        elif user_input_required and external_execution_required:
            paused_content = "I have tools to execute, but I need user input or external execution."
        elif confirmation_required:
            paused_content = "I have tools to execute, but I need confirmation."
        elif user_input_required:
            paused_content = "I have tools to execute, but I need user input."
        elif external_execution_required:
            paused_content = "I have tools to execute, but it needs external execution."
    return paused_content
