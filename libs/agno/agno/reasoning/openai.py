from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional, Tuple

from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics


def is_openai_reasoning_model(reasoning_model: Model) -> bool:
    model_id_lower = reasoning_model.id.lower()

    # Native OpenAI reasoning models (o1, o3, o4, 5.1, 5.2)
    is_native_openai = (
        reasoning_model.__class__.__name__ == "OpenAIChat"
        or reasoning_model.__class__.__name__ == "OpenAIResponses"
        or reasoning_model.__class__.__name__ == "AzureOpenAI"
    ) and (
        ("o4" in reasoning_model.id)
        or ("o3" in reasoning_model.id)
        or ("o1" in reasoning_model.id)
        or ("5.1" in reasoning_model.id)
        or ("5.2" in reasoning_model.id)
    )

    # OpenAILike providers (Together, Fireworks, OpenRouter, DeepInfra, VLLM, etc.)
    # Also covers self-hosted OpenAI-compatible servers (OpenAIChat with custom base_url)
    is_openai_compatible = isinstance(reasoning_model, OpenAILike) or (
        reasoning_model.__class__.__name__ == "OpenAIChat" and getattr(reasoning_model, "base_url", None) is not None
    )
    is_openai_like_reasoning = is_openai_compatible and (
        getattr(reasoning_model, "enable_thinking", None) is True
        or "qwq" in model_id_lower
        or "qwen3" in model_id_lower
        or "deepseek-r1" in model_id_lower
        or "openthinker" in model_id_lower
        or "minimax-m2" in model_id_lower
        or "minimax-m3" in model_id_lower
    )

    return is_native_openai or is_openai_like_reasoning


def get_openai_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
    # Update system message role to "system"
    for message in messages:
        if message.role == "developer":
            message.role = "system"

    try:
        reasoning_agent_response = reasoning_agent.run(input=messages)
    except Exception as e:
        log_warning(f"Reasoning error: {str(e)}")
        return None

    # Accumulate reasoning agent metrics into the parent run_metrics
    if run_metrics is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response.metrics, run_metrics, prefix="reasoning")

    # 1. Prefer already-extracted reasoning_content (OpenAIChat parses <think> tags)
    reasoning_content = getattr(reasoning_agent_response, "reasoning_content", None) or ""

    # 2. Fall back to parsing content if reasoning_content is empty
    if not reasoning_content and reasoning_agent_response.content is not None:
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


async def aget_openai_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
    # Update system message role to "system"
    for message in messages:
        if message.role == "developer":
            message.role = "system"

    try:
        reasoning_agent_response = await reasoning_agent.arun(input=messages)
    except Exception as e:
        log_warning(f"Reasoning error: {str(e)}")
        return None

    # Accumulate reasoning agent metrics into the parent run_metrics
    if run_metrics is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response.metrics, run_metrics, prefix="reasoning")

    # 1. Prefer already-extracted reasoning_content (OpenAIChat parses <think> tags)
    reasoning_content = getattr(reasoning_agent_response, "reasoning_content", None) or ""

    # 2. Fall back to parsing content if reasoning_content is empty
    if not reasoning_content and reasoning_agent_response.content is not None:
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


def get_openai_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> Iterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from OpenAI model.

    For OpenAI reasoning models, we use the main content output as reasoning content.

    Yields:
        Tuple of (reasoning_content_delta, final_message)
        - During streaming: (reasoning_content_delta, None)
        - At the end: (None, final_message)
    """
    from agno.run.agent import RunEvent

    # Update system message role to "system"
    for message in messages:
        if message.role == "developer":
            message.role = "system"

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
                    # Check for reasoning_content at completion (OpenAIResponses with reasoning_summary)
                    if hasattr(event, "reasoning_content") and event.reasoning_content:
                        # If we haven't accumulated any reasoning content yet, use this
                        if not reasoning_content:
                            reasoning_content = event.reasoning_content
                            yield (event.reasoning_content, None)
    except Exception as e:
        log_warning(f"Reasoning error: {str(e)}")
        return

    # Yield final message
    if reasoning_content:
        final_message = Message(
            role="assistant",
            content=f"<thinking>\n{reasoning_content}\n</thinking>",
            reasoning_content=reasoning_content,
        )
        yield (None, final_message)


async def aget_openai_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> AsyncIterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from OpenAI model asynchronously.

    For OpenAI reasoning models, we use the main content output as reasoning content.

    Yields:
        Tuple of (reasoning_content_delta, final_message)
        - During streaming: (reasoning_content_delta, None)
        - At the end: (None, final_message)
    """
    from agno.run.agent import RunEvent

    # Update system message role to "system"
    for message in messages:
        if message.role == "developer":
            message.role = "system"

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
                    # Check for reasoning_content at completion (OpenAIResponses with reasoning_summary)
                    if hasattr(event, "reasoning_content") and event.reasoning_content:
                        # If we haven't accumulated any reasoning content yet, use this
                        if not reasoning_content:
                            reasoning_content = event.reasoning_content
                            yield (event.reasoning_content, None)
    except Exception as e:
        log_warning(f"Reasoning error: {str(e)}")
        return

    # Yield final message
    if reasoning_content:
        final_message = Message(
            role="assistant",
            content=f"<thinking>\n{reasoning_content}\n</thinking>",
            reasoning_content=reasoning_content,
        )
        yield (None, final_message)
