from __future__ import annotations

from typing import AsyncIterator, Iterator, List, Optional, Tuple

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import logger


def is_anthropic_reasoning_model(reasoning_model: Model) -> bool:
    """Check if the model is an Anthropic Claude model with thinking support."""
    is_claude = reasoning_model.__class__.__name__ == "Claude"
    if not is_claude:
        return False

    # Check if provider is Anthropic (not VertexAI)
    is_anthropic_provider = hasattr(reasoning_model, "provider") and reasoning_model.provider == "Anthropic"

    # Check if thinking parameter is set
    has_thinking = hasattr(reasoning_model, "thinking") and reasoning_model.thinking is not None

    return is_claude and is_anthropic_provider and has_thinking


def get_anthropic_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    """Get reasoning from an Anthropic Claude model."""
    from agno.run.agent import RunOutput

    try:
        reasoning_agent_response: RunOutput = reasoning_agent.run(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    reasoning_content: str = ""
    redacted_reasoning_content: Optional[str] = None

    if reasoning_agent_response.messages is not None:
        for msg in reasoning_agent_response.messages:
            if msg.reasoning_content is not None:
                reasoning_content = msg.reasoning_content
            if hasattr(msg, "redacted_reasoning_content") and msg.redacted_reasoning_content is not None:
                redacted_reasoning_content = msg.redacted_reasoning_content
                break

    return Message(
        role="assistant",
        content=f"<thinking>\n{reasoning_content}\n</thinking>",
        reasoning_content=reasoning_content,
        redacted_reasoning_content=redacted_reasoning_content,
    )


def get_anthropic_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> Iterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from Anthropic Claude model.

    Yields:
        Tuple of (reasoning_content_delta, final_message)
        - During streaming: (reasoning_content_delta, None)
        - At the end: (None, final_message)
    """
    from agno.run.agent import RunEvent

    reasoning_content: str = ""
    redacted_reasoning_content: Optional[str] = None

    try:
        for event in reasoning_agent.run(input=messages, stream=True, stream_events=True):
            if hasattr(event, "event"):
                if event.event == RunEvent.run_content:
                    # Stream reasoning content as it arrives
                    if hasattr(event, "reasoning_content") and event.reasoning_content:
                        reasoning_content += event.reasoning_content
                        yield (event.reasoning_content, None)
                elif event.event == RunEvent.run_completed:
                    pass
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return

    # Yield final message
    if reasoning_content:
        final_message = Message(
            role="assistant",
            content=f"<thinking>\n{reasoning_content}\n</thinking>",
            reasoning_content=reasoning_content,
            redacted_reasoning_content=redacted_reasoning_content,
        )
        yield (None, final_message)


async def aget_anthropic_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    """Get reasoning from an Anthropic Claude model asynchronously."""
    from agno.run.agent import RunOutput

    try:
        reasoning_agent_response: RunOutput = await reasoning_agent.arun(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    reasoning_content: str = ""
    redacted_reasoning_content: Optional[str] = None

    if reasoning_agent_response.messages is not None:
        for msg in reasoning_agent_response.messages:
            if msg.reasoning_content is not None:
                reasoning_content = msg.reasoning_content
            if hasattr(msg, "redacted_reasoning_content") and msg.redacted_reasoning_content is not None:
                redacted_reasoning_content = msg.redacted_reasoning_content
                break

    return Message(
        role="assistant",
        content=f"<thinking>\n{reasoning_content}\n</thinking>",
        reasoning_content=reasoning_content,
        redacted_reasoning_content=redacted_reasoning_content,
    )


async def aget_anthropic_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> AsyncIterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from Anthropic Claude model asynchronously.

    Yields:
        Tuple of (reasoning_content_delta, final_message)
        - During streaming: (reasoning_content_delta, None)
        - At the end: (None, final_message)
    """
    from agno.run.agent import RunEvent

    reasoning_content: str = ""
    redacted_reasoning_content: Optional[str] = None

    try:
        async for event in reasoning_agent.arun(input=messages, stream=True, stream_events=True):
            if hasattr(event, "event"):
                if event.event == RunEvent.run_content:
                    # Stream reasoning content as it arrives
                    if hasattr(event, "reasoning_content") and event.reasoning_content:
                        reasoning_content += event.reasoning_content
                        yield (event.reasoning_content, None)
                elif event.event == RunEvent.run_completed:
                    pass
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return

    # Yield final message
    if reasoning_content:
        final_message = Message(
            role="assistant",
            content=f"<thinking>\n{reasoning_content}\n</thinking>",
            reasoning_content=reasoning_content,
            redacted_reasoning_content=redacted_reasoning_content,
        )
        yield (None, final_message)
