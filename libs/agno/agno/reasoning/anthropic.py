from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional, Tuple

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics


def _thinking_configured(reasoning_model: Model) -> bool:
    """Whether the caller explicitly enabled thinking on this model."""
    return hasattr(reasoning_model, "thinking") and reasoning_model.thinking is not None


def _api_thinking_supported(reasoning_model: Model) -> Optional[bool]:
    """Whether the Anthropic API reports thinking support for this model.

    Returns None when the capability cannot be determined (API failure, or an older SDK/response
    that omits the field), so callers can fall back to the configured value.
    """
    try:
        client = reasoning_model.get_client()  # type: ignore[attr-defined]
        model_info = client.models.retrieve(reasoning_model.id)
        # `capabilities` is returned as an extra (untyped) field, so it arrives as a nested dict.
        capabilities = getattr(model_info, "capabilities", None)
        if capabilities is not None:
            thinking = (
                capabilities.get("thinking")
                if isinstance(capabilities, dict)
                else getattr(capabilities, "thinking", None)
            )
            if thinking is not None:
                supported = (
                    thinking.get("supported") if isinstance(thinking, dict) else getattr(thinking, "supported", None)
                )
                if supported is not None:
                    return bool(supported)
    except Exception as e:
        log_warning(f"Could not determine Anthropic thinking capability via API, falling back to config: {str(e)}")
    return None


def is_anthropic_reasoning_model(reasoning_model: Model) -> bool:
    """Check if the model is an Anthropic Claude model with thinking support.

    Thinking must be explicitly enabled on the model: the reasoning agent runs the model as
    configured and never turns thinking on by itself, so a model without it would stream back an
    empty thinking block. The Anthropic API (models.retrieve -> capabilities.thinking.supported)
    is then used to rule out models that cannot think despite being configured for it; when that
    lookup is unavailable the configured value stands on its own.
    """
    if reasoning_model.__class__.__name__ != "Claude":
        return False

    # Only the Anthropic-hosted Claude (not VertexAI/Bedrock) exposes this capability endpoint.
    is_anthropic_provider = hasattr(reasoning_model, "provider") and reasoning_model.provider == "Anthropic"
    if not is_anthropic_provider:
        return False

    if not _thinking_configured(reasoning_model):
        return False

    supported = _api_thinking_supported(reasoning_model)
    return True if supported is None else supported


def get_anthropic_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
    """Get reasoning from an Anthropic Claude model."""
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


def get_anthropic_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> Iterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from Anthropic Claude model.

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
        log_warning(f"Reasoning error: {str(e)}")
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


async def aget_anthropic_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
    """Get reasoning from an Anthropic Claude model asynchronously."""
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


async def aget_anthropic_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> AsyncIterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from Anthropic Claude model asynchronously.

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
        log_warning(f"Reasoning error: {str(e)}")
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
