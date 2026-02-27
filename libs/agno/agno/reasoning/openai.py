from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional, Tuple

from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.metrics import RunMetrics


# Reasoning models commonly served via OpenAI-compatible APIs (vLLM, TGI, etc.)
_OPENAI_LIKE_REASONING_PATTERNS = (
    "deepseek-r1",
    "qwq",
    "qwen3",
    "openthinker",
)


def is_openai_reasoning_model(reasoning_model: Model) -> bool:
    class_name = reasoning_model.__class__.__name__

    # Case 1: Native OpenAI reasoning models (o1, o3, o4, GPT-4.1/4.5/5.x)
    if class_name in ("OpenAIChat", "OpenAIResponses", "AzureOpenAI") and (
        ("o4" in reasoning_model.id)
        or ("o3" in reasoning_model.id)
        or ("o1" in reasoning_model.id)
        or ("4.1" in reasoning_model.id)
        or ("4.5" in reasoning_model.id)
        or ("5.1" in reasoning_model.id)
        or ("5.2" in reasoning_model.id)
    ):
        return True

    # VLLM subclasses OpenAILike but has its own dedicated handler in reasoning/vllm.py
    if class_name == "VLLM":
        return False

    # Case 2: Self-hosted reasoning models via OpenAI-compatible APIs
    # Covers two scenarios from issue #6254:
    #   - OpenAILike(base_url="http://localhost:8000/v1", id="Qwen3-30B-A3B")
    #   - OpenAIChat(base_url="http://localhost:8000/v1", id="Qwen3-30B-A3B")
    # OpenAIChat without base_url connects to api.openai.com which doesn't serve these models
    is_openai_like = isinstance(reasoning_model, OpenAILike)
    is_self_hosted_openai = class_name == "OpenAIChat" and getattr(reasoning_model, "base_url", None) is not None

    if is_openai_like or is_self_hosted_openai:
        if getattr(reasoning_model, "enable_thinking", None) is True:
            return True
        model_id = reasoning_model.id.lower()
        if any(pattern in model_id for pattern in _OPENAI_LIKE_REASONING_PATTERNS):
            return True

    return False


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
        logger.warning(f"Reasoning error: {e}")
        return None

    # Accumulate reasoning agent metrics into the parent run_metrics
    if run_metrics is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response.metrics, run_metrics, prefix="reasoning")

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
        logger.warning(f"Reasoning error: {e}")
        return None

    # Accumulate reasoning agent metrics into the parent run_metrics
    if run_metrics is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response.metrics, run_metrics, prefix="reasoning")

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
