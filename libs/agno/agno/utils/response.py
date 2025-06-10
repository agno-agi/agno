from typing import List, Set, Union

from agno.exceptions import RunCancelledException
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.base import RunResponseExtraData
from agno.run.response import RunResponse, RunResponseEvent, RunResponsePausedEvent
from agno.run.team import TeamRunResponse, TeamRunResponseEvent


def create_panel(content, title, border_style="blue"):
    from rich.box import HEAVY
    from rich.panel import Panel

    return Panel(
        content, title=title, title_align="left", border_style=border_style, box=HEAVY, expand=True, padding=(1, 1)
    )


def escape_markdown_tags(content: str, tags: Set[str]) -> str:
    """Escape special tags in markdown content."""
    escaped_content = content
    for tag in tags:
        # Escape opening tag
        escaped_content = escaped_content.replace(f"<{tag}>", f"&lt;{tag}&gt;")
        # Escape closing tag
        escaped_content = escaped_content.replace(f"</{tag}>", f"&lt;/{tag}&gt;")
    return escaped_content


def check_if_run_cancelled(run_response: Union[RunResponse, RunResponseEvent, TeamRunResponse, TeamRunResponseEvent]):
    if run_response.is_cancelled:
        raise RunCancelledException()


def update_run_response_with_reasoning(
    run_response: Union[RunResponse, TeamRunResponse],
    reasoning_steps: List[ReasoningStep],
    reasoning_agent_messages: List[Message],
) -> None:
    if run_response.extra_data is None:
        run_response.extra_data = RunResponseExtraData()

    # Update reasoning_steps
    if run_response.extra_data.reasoning_steps is None:
        run_response.extra_data.reasoning_steps = reasoning_steps
    else:
        run_response.extra_data.reasoning_steps.extend(reasoning_steps)

    # Update reasoning_messages
    if run_response.extra_data.reasoning_messages is None:
        run_response.extra_data.reasoning_messages = reasoning_agent_messages
    else:
        run_response.extra_data.reasoning_messages.extend(reasoning_agent_messages)


def format_tool_calls(tool_calls: List[ToolExecution]) -> List[str]:
    """Format tool calls for display in a readable format.

    Args:
        tool_calls: List of tool call dictionaries containing tool_name and tool_args

    Returns:
        List[str]: List of formatted tool call strings
    """
    formatted_tool_calls = []
    for tool_call in tool_calls:
        if tool_call.tool_name and tool_call.tool_args:
            tool_name = tool_call.tool_name
            args_str = ""
            if tool_call.tool_args is not None:
                args_str = ", ".join(f"{k}={v}" for k, v in tool_call.tool_args.items())
            formatted_tool_calls.append(f"{tool_name}({args_str})")
    return formatted_tool_calls


def create_paused_run_response_panel(run_response: Union[RunResponsePausedEvent, RunResponse]):
    from rich.text import Text

    tool_calls_content = Text("Run is paused. ")
    if run_response.tools is not None:
        if any(tc.requires_confirmation for tc in run_response.tools):
            tool_calls_content.append("The following tool calls require confirmation:\n")
        for tool_call in run_response.tools:
            if tool_call.requires_confirmation:
                args_str = ""
                for arg, value in tool_call.tool_args.items() if tool_call.tool_args else {}:
                    args_str += f"{arg}={value}, "
                args_str = args_str.rstrip(", ")
                tool_calls_content.append(f"• {tool_call.tool_name}({args_str})\n")
        if any(tc.requires_user_input for tc in run_response.tools):
            tool_calls_content.append("The following tool calls require user input:\n")
        for tool_call in run_response.tools:
            if tool_call.requires_user_input:
                args_str = ""
                for arg, value in tool_call.tool_args.items() if tool_call.tool_args else {}:
                    args_str += f"{arg}={value}, "
                args_str = args_str.rstrip(", ")
                tool_calls_content.append(f"• {tool_call.tool_name}({args_str})\n")
        if any(tc.external_execution_required for tc in run_response.tools):
            tool_calls_content.append("The following tool calls require external execution:\n")
        for tool_call in run_response.tools:
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
