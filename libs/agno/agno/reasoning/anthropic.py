from __future__ import annotations

from typing import List, Optional

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
