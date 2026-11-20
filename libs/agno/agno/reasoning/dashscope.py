from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional, Tuple

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics


def is_dashscope_reasoning_model(reasoning_model: Model) -> bool:
    """
    Check if a model is a DashScope reasoning model.

    A model is considered a reasoning model if:
    - It's a DashScope instance AND
    - The model ID contains 'qwen' (QwQ reasoning models) OR
    - The model has enable_thinking=True
    """
    is_dashscope = reasoning_model.__class__.__name__ == "DashScope"

    if not is_dashscope:
        return False

    # Check if model ID indicates a reasoning model
    model_id_lower = reasoning_model.id.lower()
    has_reasoning_id = "qwen" in model_id_lower

    # Check if enable_thinking is set
    has_thinking_enabled = getattr(reasoning_model, "enable_thinking", False)

    return has_reasoning_id or has_thinking_enabled


def get_dashscope_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
    """
    Get reasoning content from DashScope model synchronously.

    For DashScope reasoning models, we use the main content output as reasoning content.
    The model may also return native reasoning_content if enable_thinking is enabled.
    """
    try:
        reasoning_agent_response = reasoning_agent.run(input=messages)
    except Exception as e:
        log_warning(f"Reasoning error: {str(e)}")
        return None

    # Accumulate reasoning agent metrics into the parent run_metrics
    if run_metrics is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response.metrics, run_metrics, prefix="reasoning")

    reasoning_content: str = ""

    # Check for native reasoning_content attribute first
    if hasattr(reasoning_agent_response, "reasoning_content") and reasoning_agent_response.reasoning_content:
        reasoning_content = reasoning_agent_response.reasoning_content
    # Fall back to main content
    elif reasoning_agent_response.content is not None:
        # Extract content between <think> tags if present (DashScope format)
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


async def aget_dashscope_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
    """
    Get reasoning content from DashScope model asynchronously.

    For DashScope reasoning models, we use the main content output as reasoning content.
    The model may also return native reasoning_content if enable_thinking is enabled.
    """
    try:
        reasoning_agent_response = await reasoning_agent.arun(input=messages)
    except Exception as e:
        log_warning(f"Reasoning error: {str(e)}")
        return None

    # Accumulate reasoning agent metrics into the parent run_metrics
    if run_metrics is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response.metrics, run_metrics, prefix="reasoning")

    reasoning_content: str = ""

    # Check for native reasoning_content attribute first
    if hasattr(reasoning_agent_response, "reasoning_content") and reasoning_agent_response.reasoning_content:
        reasoning_content = reasoning_agent_response.reasoning_content
    # Fall back to main content
    elif reasoning_agent_response.content is not None:
        # Extract content between <think> tags if present (DashScope format)
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


def get_dashscope_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> Iterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from DashScope model.

    For DashScope reasoning models (qwq, qvq, or models with enable_thinking),
    we use the main content output as reasoning content.

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
                    # Check for reasoning_content at completion
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


async def aget_dashscope_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> AsyncIterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from DashScope model asynchronously.

    For DashScope reasoning models (qwq, qvq, or models with enable_thinking),
    we use the main content output as reasoning content.

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
                    # Check for reasoning_content at completion
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
