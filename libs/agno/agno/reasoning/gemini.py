from __future__ import annotations

from typing import List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import logger


def is_gemini_reasoning_model(reasoning_model: Model) -> bool:
    """Check if the model is a Gemini model with thinking support."""
    is_gemini_class = reasoning_model.__class__.__name__ == "Gemini"
    if not is_gemini_class:
        return False

    # Check if it's a Gemini 2.5+ model (supports thinking)
    model_id = reasoning_model.id.lower()
    has_thinking_support = "2.5" in model_id

    # Also check if thinking parameters are set
    # Note: thinking_budget=0 explicitly disables thinking mode per Google's API docs
    has_thinking_budget = (
        hasattr(reasoning_model, "thinking_budget")
        and reasoning_model.thinking_budget is not None
        and reasoning_model.thinking_budget > 0
    )
    has_include_thoughts = hasattr(reasoning_model, "include_thoughts") and reasoning_model.include_thoughts is not None

    return is_gemini_class and (has_thinking_support or has_thinking_budget or has_include_thoughts)


def get_gemini_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    """Get reasoning from a Gemini model."""
    from agno.run.agent import RunOutput

    try:
        reasoning_agent_response: RunOutput = reasoning_agent.run(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    reasoning_content: str = ""
    if reasoning_agent_response.messages is not None:
        for msg in reasoning_agent_response.messages:
            if msg.reasoning_content is not None:
                reasoning_content = msg.reasoning_content
                break

    return Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )


async def aget_gemini_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    """Get reasoning from a Gemini model asynchronously."""
    from agno.run.agent import RunOutput

    try:
        reasoning_agent_response: RunOutput = await reasoning_agent.arun(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    reasoning_content: str = ""
    if reasoning_agent_response.messages is not None:
        for msg in reasoning_agent_response.messages:
            if msg.reasoning_content is not None:
                reasoning_content = msg.reasoning_content
                break

    return Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )
