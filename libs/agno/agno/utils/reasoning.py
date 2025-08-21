from typing import TYPE_CHECKING, List, Union

from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.reasoning.step import ReasoningStep
from agno.run.base import RunOutputMetaData

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.team.team import TeamRunOutput


def append_to_reasoning_content(run_response: Union["RunOutput", "TeamRunOutput"], content: str) -> None:
    """Helper to append content to the reasoning_content field."""
    if not hasattr(run_response, "reasoning_content") or not run_response.reasoning_content:  # type: ignore
        run_response.reasoning_content = content  # type: ignore
    else:
        run_response.reasoning_content += content  # type: ignore


def add_reasoning_step_to_metadata(
    run_response: Union["RunOutput", "TeamRunOutput"], reasoning_step: ReasoningStep
) -> None:
    if run_response.metadata is None:
        from agno.run.agent import RunOutputMetaData

        run_response.metadata = RunOutputMetaData()

    if run_response.metadata.reasoning_steps is None:
        run_response.metadata.reasoning_steps = []

    run_response.metadata.reasoning_steps.append(reasoning_step)


def add_reasoning_metrics_to_metadata(
    run_response: Union["RunOutput", "TeamRunOutput"], reasoning_time_taken: float
) -> None:
    try:
        if run_response.metadata is None:
            from agno.run.agent import RunOutputMetaData

            run_response.metadata = RunOutputMetaData()

            # Initialize reasoning_messages if it doesn't exist
            if run_response.metadata.reasoning_messages is None:
                run_response.metadata.reasoning_messages = []

            metrics_message = Message(
                role="assistant",
                content=run_response.reasoning_content,
                metrics=Metrics(duration=reasoning_time_taken),
            )

            # Add the metrics message to the reasoning_messages
            run_response.metadata.reasoning_messages.append(metrics_message)

    except Exception as e:
        # Log the error but don't crash
        from agno.utils.log import log_error

        log_error(f"Failed to add reasoning metrics to metadata: {str(e)}")


def update_run_output_with_reasoning(
    run_response: Union["RunOutput", "TeamRunOutput"],
    reasoning_steps: List[ReasoningStep],
    reasoning_agent_messages: List[Message],
) -> None:
    if run_response.metadata is None:
        run_response.metadata = RunOutputMetaData()

    metadata = run_response.metadata

    # Update reasoning_steps
    if metadata.reasoning_steps is None:
        metadata.reasoning_steps = reasoning_steps
    else:
        metadata.reasoning_steps.extend(reasoning_steps)

    # Update reasoning_messages
    if metadata.reasoning_messages is None:
        metadata.reasoning_messages = reasoning_agent_messages
    else:
        metadata.reasoning_messages.extend(reasoning_agent_messages)

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

    # Add to existing reasoning_content or set it
    if not run_response.reasoning_content:
        run_response.reasoning_content = reasoning_content
    else:
        run_response.reasoning_content += reasoning_content
