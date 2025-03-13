from typing import List, Set, Union

from agno.exceptions import RunCancelledException
from agno.models.message import Message
from agno.reasoning.step import ReasoningStep
from agno.run.response import RunEvent, RunResponse, RunResponseExtraData
from agno.run.team import TeamRunResponse


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


def check_if_run_cancelled(run_response: RunResponse):
    if run_response.event == RunEvent.run_cancelled:
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
