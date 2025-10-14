from __future__ import annotations

from typing import List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import logger


def is_vertexai_reasoning_model(reasoning_model: Model) -> bool:
    """Check if the model is a VertexAI model with thinking support."""
    # Check if provider is VertexAI
    is_vertexai_provider = hasattr(reasoning_model, "provider") and reasoning_model.provider == "VertexAI"

    # Check if thinking parameter is set
    has_thinking = hasattr(reasoning_model, "thinking") and reasoning_model.thinking is not None

    return is_vertexai_provider and has_thinking


def get_vertexai_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    """Get reasoning from a VertexAI Claude model."""
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


async def aget_vertexai_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    """Get reasoning from a VertexAI Claude model asynchronously."""
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
