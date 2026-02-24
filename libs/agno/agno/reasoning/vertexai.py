from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional, Tuple, Union

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput


def is_vertexai_reasoning_model(reasoning_model: Model) -> bool:
    """Check if the model is a VertexAI model with thinking support."""
    # Check if provider is VertexAI
    is_vertexai_provider = hasattr(reasoning_model, "provider") and reasoning_model.provider == "VertexAI"

    # Check if thinking parameter is set
    has_thinking = hasattr(reasoning_model, "thinking") and reasoning_model.thinking is not None

    return is_vertexai_provider and has_thinking


def get_vertexai_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_response: Optional[Union["RunOutput", "TeamRunOutput"]] = None,
) -> Optional[Message]:
    """Get reasoning from a VertexAI Claude model."""
    try:
        reasoning_agent_response = reasoning_agent.run(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    # Accumulate reasoning agent metrics into the parent run_response
    if run_response is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response, run_response, prefix="reasoning")

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


async def aget_vertexai_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_response: Optional[Union["RunOutput", "TeamRunOutput"]] = None,
) -> Optional[Message]:
    """Get reasoning from a VertexAI Claude model asynchronously."""
    try:
        reasoning_agent_response = await reasoning_agent.arun(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    # Accumulate reasoning agent metrics into the parent run_response
    if run_response is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response, run_response, prefix="reasoning")

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


def get_vertexai_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> Iterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from VertexAI Claude model.

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


async def aget_vertexai_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> AsyncIterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from VertexAI Claude model asynchronously.

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
