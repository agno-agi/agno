from __future__ import annotations

from typing import List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.utils.log import logger


def is_openai_reasoning_model(reasoning_model: Model) -> bool:
    return (
        (
            reasoning_model.__class__.__name__ == "OpenAIChat"
            or reasoning_model.__class__.__name__ == "OpenAIResponses"
            or reasoning_model.__class__.__name__ == "AzureOpenAI"
        )
        and (
            ("o3" in reasoning_model.id)
            or ("o1" in reasoning_model.id)
            or ("4.1" in reasoning_model.id)
            or ("4.5" in reasoning_model.id)
        )
    ) or (isinstance(reasoning_model, OpenAILike) and "deepseek-r1" in reasoning_model.id.lower())


def get_openai_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    from agno.run.response import RunResponse

    try:
        reasoning_agent_response: RunResponse = reasoning_agent.run(messages=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    reasoning_content: str = ""
    # We use the normal content as no reasoning content is returned
    if reasoning_agent_response.content is not None:
        # Extract content between <think> tags if present
        content = reasoning_agent_response.content
        if "<think>" in content and "</think>" in content:
            start_idx = content.find("<think>") + len("<think>")
            end_idx = content.find("</think>")
            reasoning_content = content[start_idx:end_idx].strip()
        else:
            reasoning_content = content

    return Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )


async def aget_openai_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    from agno.run.response import RunResponse

    # Update system message role to "system"
    for message in messages:
        if message.role == "developer":
            message.role = "system"

    try:
        reasoning_agent_response: RunResponse = await reasoning_agent.arun(messages=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    reasoning_content: str = ""
    if reasoning_agent_response.content is not None:
        # Extract content between <think> tags if present
        content = reasoning_agent_response.content
        if "<think>" in content and "</think>" in content:
            start_idx = content.find("<think>") + len("<think>")
            end_idx = content.find("</think>")
            reasoning_content = content[start_idx:end_idx].strip()
        else:
            reasoning_content = content

    return Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )
