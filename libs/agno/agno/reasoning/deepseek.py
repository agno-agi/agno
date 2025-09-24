from __future__ import annotations

from typing import List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import logger


def is_deepseek_reasoning_model(reasoning_model: Model) -> bool:
    return reasoning_model.__class__.__name__ == "DeepSeek" and reasoning_model.id.lower() == "deepseek-reasoner"


def get_deepseek_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    from agno.run.agent import RunOutput

    # Update system message role to "system"
    for message in messages:
        if message.role == "developer":
            message.role = "system"

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


async def aget_deepseek_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    from agno.run.agent import RunOutput

    # Update system message role to "system"
    for message in messages:
        if message.role == "developer":
            message.role = "system"

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
