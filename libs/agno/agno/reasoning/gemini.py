from __future__ import annotations

import re
from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional, Tuple

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics


def _gemini_fallback(reasoning_model: Model) -> bool:
    """Substring + thinking-parameter check for Gemini thinking support."""
    if getattr(reasoning_model, "thinking_budget", None) == 0:
        return False
    if getattr(reasoning_model, "include_thoughts", None) is False:
        return False
    if str(getattr(reasoning_model, "thinking_level", "") or "").lower() in ("none", "disable"):
        return False

    # - Gemini 2.5+ models support thinking
    # - Gemini 3+ models support thinking (including DeepThink and latest aliases)
    model_id = reasoning_model.id.lower()
    has_thinking_support = bool(
        re.search(
            r"(?:^|/|[a-z]{2,}\.)gemini-(?:2\.5|[3-9]|\d{2,}|(?:flash|flash-lite|pro)-latest)|2\.5|3\.0|3\.5|deepthink|gemini-3",
            model_id,
        )
    )

    # Also check if thinking parameters are set
    # Note: thinking_budget=0 explicitly disables thinking mode per Google's API docs
    has_thinking_budget = (
        bool(getattr(reasoning_model, "thinking_budget", None)) and getattr(reasoning_model, "thinking_budget", 0) > 0
    )
    has_thinking_level = bool(getattr(reasoning_model, "thinking_level", None))
    has_include_thoughts = bool(getattr(reasoning_model, "include_thoughts", None))

    return has_thinking_support or has_thinking_budget or has_thinking_level or has_include_thoughts


def is_gemini_reasoning_model(reasoning_model: Model) -> bool:
    """Check if the model is a Gemini model with thinking support.

    Checks local model family heuristics and explicit thinking configuration first, and queries
    the Gemini API (models.get -> thinking) only when local heuristics cannot determine support.
    """
    if reasoning_model.__class__.__name__ != "Gemini":
        return False

    if getattr(reasoning_model, "thinking_budget", None) == 0:
        return False
    if getattr(reasoning_model, "include_thoughts", None) is False:
        return False
    if str(getattr(reasoning_model, "thinking_level", "") or "").lower() in ("none", "disable"):
        return False

    if _gemini_fallback(reasoning_model):
        return True

    model_id = reasoning_model.id
    if re.search(r"(?:^|/|[a-z]{2,}\.)gemini-(?:1(?:\.\d+)?|2\.0)(?:-|$)", model_id.lower()):
        return False

    try:
        client = reasoning_model.get_client()  # type: ignore[attr-defined]
        name = model_id if model_id.startswith("models/") else f"models/{model_id}"
        model_info = client.models.get(model=name)
        thinking = getattr(model_info, "thinking", None)
        if thinking is not None:
            return bool(thinking)
    except Exception as e:
        log_warning(f"Could not determine Gemini thinking capability via API, falling back to model id: {str(e)}")

    return False


def get_gemini_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
    """Get reasoning from a Gemini model."""
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
    if reasoning_agent_response.messages is not None:
        for msg in reasoning_agent_response.messages:
            if msg.reasoning_content is not None:
                reasoning_content = msg.reasoning_content
                break

    return Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )


async def aget_gemini_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
    """Get reasoning from a Gemini model asynchronously."""
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
    if reasoning_agent_response.messages is not None:
        for msg in reasoning_agent_response.messages:
            if msg.reasoning_content is not None:
                reasoning_content = msg.reasoning_content
                break

    return Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )


def get_gemini_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> Iterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from Gemini model.

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
        )
        yield (None, final_message)


async def aget_gemini_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> AsyncIterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from Gemini model asynchronously.

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
        )
        yield (None, final_message)
