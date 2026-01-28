from __future__ import annotations

from typing import AsyncIterator, Iterator, List, Optional, Tuple

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import logger


def is_ollama_reasoning_model(reasoning_model: Model) -> bool:
    return reasoning_model.__class__.__name__ == "Ollama" and (
        "qwq" in reasoning_model.id
        or "deepseek-r1" in reasoning_model.id
        or "qwen2.5-coder" in reasoning_model.id
        or "openthinker" in reasoning_model.id
    )


def get_ollama_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    from agno.run.agent import RunOutput

    try:
        reasoning_agent_response: RunOutput = reasoning_agent.run(input=messages)
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


async def aget_ollama_reasoning(reasoning_agent: "Agent", messages: List[Message]) -> Optional[Message]:  # type: ignore  # noqa: F821
    from agno.run.agent import RunOutput

    try:
        reasoning_agent_response: RunOutput = await reasoning_agent.arun(input=messages)
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


def get_ollama_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> Iterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from Ollama model.

    For reasoning models on Ollama (qwq, deepseek-r1, etc.), we use the main content output as reasoning content.

    Yields:
        Tuple of (reasoning_content_delta, final_message)
        - During streaming: (reasoning_content_delta, None)
        - At the end: (None, final_message)
    """
    from agno.run.agent import RunEvent

    reasoning_content: str = ""

    try:
        for event in reasoning_agent.run(input=messages, stream=True, stream_events=True):
            if hasattr(event, "event"):
                if event.event == RunEvent.run_content:
                    # Check for reasoning_content attribute first (native reasoning)
                    if hasattr(event, "reasoning_content") and event.reasoning_content:
                        reasoning_content += event.reasoning_content
                        yield (event.reasoning_content, None)
                    # Use the main content as reasoning content
                    elif hasattr(event, "content") and event.content:
                        reasoning_content += event.content
                        yield (event.content, None)
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
        )
        yield (None, final_message)


async def aget_ollama_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> AsyncIterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from Ollama model asynchronously.

    For reasoning models on Ollama (qwq, deepseek-r1, etc.), we use the main content output as reasoning content.

    Yields:
        Tuple of (reasoning_content_delta, final_message)
        - During streaming: (reasoning_content_delta, None)
        - At the end: (None, final_message)
    """
    from agno.run.agent import RunEvent

    reasoning_content: str = ""

    try:
        async for event in reasoning_agent.arun(input=messages, stream=True, stream_events=True):
            if hasattr(event, "event"):
                if event.event == RunEvent.run_content:
                    # Check for reasoning_content attribute first (native reasoning)
                    if hasattr(event, "reasoning_content") and event.reasoning_content:
                        reasoning_content += event.reasoning_content
                        yield (event.reasoning_content, None)
                    # Use the main content as reasoning content
                    elif hasattr(event, "content") and event.content:
                        reasoning_content += event.content
                        yield (event.content, None)
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
        )
        yield (None, final_message)
