from typing import TYPE_CHECKING, List, Optional, Tuple, Union

from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.reasoning.step import ReasoningStep

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.team.team import TeamRunOutput


def extract_thinking_content(content: str) -> Tuple[Optional[str], str]:
    """Extract thinking content from response text between <think> tags."""
    if not content or "</think>" not in content:
        return None, content

    # Find the end of thinking content
    end_idx = content.find("</think>")

    # Look for opening <think> tag, if not found, assume thinking starts at beginning
    start_idx = content.find("<think>")
    if start_idx == -1:
        reasoning_content = content[:end_idx].strip()
    else:
        start_idx = start_idx + len("<think>")
        reasoning_content = content[start_idx:end_idx].strip()

    output_content = content[end_idx + len("</think>") :].strip()

    return reasoning_content, output_content


def append_to_reasoning_content(run_response: Union["RunOutput", "TeamRunOutput"], content: str) -> None:
    """Helper to append content to the reasoning_content field."""
    if not hasattr(run_response, "reasoning_content") or not run_response.reasoning_content:  # type: ignore
        run_response.reasoning_content = content  # type: ignore
    else:
        run_response.reasoning_content += content  # type: ignore


def add_reasoning_step_to_metadata(
    run_response: Union["RunOutput", "TeamRunOutput"], reasoning_step: ReasoningStep
) -> None:
    if run_response.reasoning_steps is None:
        run_response.reasoning_steps = []

    run_response.reasoning_steps.append(reasoning_step)


def add_reasoning_metrics_to_metadata(
    run_response: Union["RunOutput", "TeamRunOutput"], reasoning_time_taken: float
) -> None:
    try:
        # Initialize reasoning_messages if it doesn't exist
        if run_response.reasoning_messages is None:
            run_response.reasoning_messages = []

        metrics_message = Message(
            role="assistant",
            content=run_response.reasoning_content,
            metrics=Metrics(duration=reasoning_time_taken),
        )

        # Add the metrics message to the reasoning_messages
        run_response.reasoning_messages.append(metrics_message)

    except Exception as e:
        # Log the error but don't crash
        from agno.utils.log import log_error

        log_error(f"Failed to add reasoning metrics to metadata: {str(e)}")


def update_run_output_with_reasoning(
    run_response: Union["RunOutput", "TeamRunOutput"],
    reasoning_steps: List[ReasoningStep],
    reasoning_agent_messages: List[Message],
) -> None:
    # Update reasoning_steps
    if run_response.reasoning_steps is None:
        run_response.reasoning_steps = reasoning_steps
    else:
        run_response.reasoning_steps.extend(reasoning_steps)

    # Update reasoning_messages
    if run_response.reasoning_messages is None:
        run_response.reasoning_messages = reasoning_agent_messages
    else:
        run_response.reasoning_messages.extend(reasoning_agent_messages)

    # Create and store reasoning_content
    reasoning_content = ""
    for step in reasoning_steps:
        if step.title:
            reasoning_content += f"## {step.title}\n"
        if step.reasoning:
            reasoning_content += f"{step.reasoning}\n"
        if step.action:
            reasoning_content += f"Action: {step.action}\n"
        if step.result:
            reasoning_content += f"Result: {step.result}\n"
        reasoning_content += "\n"

    run_response.reasoning_content = reasoning_content
