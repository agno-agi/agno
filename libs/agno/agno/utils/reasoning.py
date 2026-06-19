import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple, Union

from agno.metrics import MessageMetrics
from agno.models.message import Message
from agno.reasoning.step import ReasoningStep

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.team.team import TeamRunOutput


@dataclass
class ThinkTagStreamState:
    """State for streaming <think> tag parsing."""

    in_think_block: bool = False
    tag_type: Optional[str] = None  # "think" or "thinking"
    tag_buffer: str = ""  # Buffer for partial tag detection
    accumulated_reasoning: str = ""
    accumulated_content: str = ""


@dataclass
class ThinkTagStreamResult:
    """Result of processing a streaming chunk for <think> tags."""

    reasoning_content: Optional[str] = None  # Reasoning to emit this chunk
    clean_content: Optional[str] = None  # Clean content to emit this chunk
    entered_think: bool = False  # True if we just entered a <think> block
    exited_think: bool = False  # True if we just exited a </think> block


def process_think_tag_chunk(chunk: str, state: ThinkTagStreamState) -> ThinkTagStreamResult:
    """Process a streaming chunk, parsing <think>/<thinking> tags in-flight.

    This enables real-time separation of reasoning and content during streaming,
    rather than waiting for the complete response.
    """
    result = ThinkTagStreamResult()

    # Add chunk to buffer for tag detection
    state.tag_buffer += chunk
    buffer = state.tag_buffer

    while buffer:
        if state.in_think_block:
            # Look for closing tag
            close_tag = f"</{state.tag_type}>"
            close_idx = buffer.find(close_tag)

            if close_idx != -1:
                # Found closing tag - emit reasoning up to it
                reasoning_chunk = buffer[:close_idx]
                if reasoning_chunk:
                    result.reasoning_content = (result.reasoning_content or "") + reasoning_chunk
                    state.accumulated_reasoning += reasoning_chunk

                # Exit think block
                state.in_think_block = False
                result.exited_think = True
                buffer = buffer[close_idx + len(close_tag) :]
                state.tag_type = None
            elif len(buffer) >= 12:
                # No closing tag yet but buffer is long enough to safely emit
                # Keep last 11 chars (len("</thinking>") - 1) in buffer for partial tag detection
                safe_len = len(buffer) - 11
                if safe_len > 0:
                    reasoning_chunk = buffer[:safe_len]
                    result.reasoning_content = (result.reasoning_content or "") + reasoning_chunk
                    state.accumulated_reasoning += reasoning_chunk
                    buffer = buffer[safe_len:]
                break
            else:
                # Buffer too short, wait for more data
                break
        else:
            # Look for opening tag
            think_idx = buffer.find("<think>")
            thinking_idx = buffer.find("<thinking>")

            # Find earliest opening tag
            open_idx = -1
            tag_len = 0
            if think_idx != -1 and (thinking_idx == -1 or think_idx < thinking_idx):
                open_idx = think_idx
                tag_len = 7  # len("<think>")
                state.tag_type = "think"
            elif thinking_idx != -1:
                open_idx = thinking_idx
                tag_len = 10  # len("<thinking>")
                state.tag_type = "thinking"

            if open_idx != -1:
                # Found opening tag - emit content before it
                content_chunk = buffer[:open_idx]
                if content_chunk:
                    result.clean_content = (result.clean_content or "") + content_chunk
                    state.accumulated_content += content_chunk

                # Enter think block
                state.in_think_block = True
                result.entered_think = True
                buffer = buffer[open_idx + tag_len :]
            elif len(buffer) >= 11:
                # No opening tag yet but buffer is long enough to safely emit
                # Keep last 10 chars (len("<thinking>") - 1) in buffer for partial tag detection
                safe_len = len(buffer) - 10
                if safe_len > 0:
                    content_chunk = buffer[:safe_len]
                    result.clean_content = (result.clean_content or "") + content_chunk
                    state.accumulated_content += content_chunk
                    buffer = buffer[safe_len:]
                break
            else:
                # Buffer too short, wait for more data
                break

    state.tag_buffer = buffer
    return result


def flush_think_tag_state(state: ThinkTagStreamState) -> ThinkTagStreamResult:
    """Flush any remaining buffered content at end of stream."""
    result = ThinkTagStreamResult()

    if state.tag_buffer:
        if state.in_think_block:
            result.reasoning_content = state.tag_buffer
            state.accumulated_reasoning += state.tag_buffer
        else:
            result.clean_content = state.tag_buffer
            state.accumulated_content += state.tag_buffer
        state.tag_buffer = ""

    return result


def extract_thinking_content(content: str) -> Tuple[Optional[str], str]:
    """Extract thinking content from response text between <think> or <thinking> tags.

    Handles multiple blocks that accumulate across tool-call iterations.
    """
    if not content:
        return None, content

    # Determine which tag format is present
    if "</think>" in content:
        pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
    elif "</thinking>" in content:
        pattern = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)
    else:
        return None, content

    # Extract all thinking blocks
    matches = pattern.findall(content)
    if not matches:
        return None, content

    reasoning_content = "\n".join(m.strip() for m in matches if m.strip())
    output_content = pattern.sub("", content).strip()

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
            metrics=MessageMetrics(duration=reasoning_time_taken),
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
