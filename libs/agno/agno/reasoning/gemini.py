from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional, Tuple, Union

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput


def is_gemini_reasoning_model(reasoning_model: Model) -> bool:
    """Check if the model is a Gemini model with thinking support."""
    is_gemini_class = reasoning_model.__class__.__name__ == "Gemini"
    if not is_gemini_class:
        return False

    # Check if it's a Gemini model with thinking support
    # - Gemini 2.5+ models support thinking
    # - Gemini 3+ models support thinking (including DeepThink variants)
    model_id = reasoning_model.id.lower()
    has_thinking_support = (
        "2.5" in model_id or "3.0" in model_id or "3.5" in model_id or "deepthink" in model_id or "gemini-3" in model_id
    )

    # Also check if thinking parameters are set
    # Note: thinking_budget=0 explicitly disables thinking mode per Google's API docs
    has_thinking_budget = (
        hasattr(reasoning_model, "thinking_budget")
        and reasoning_model.thinking_budget is not None
        and reasoning_model.thinking_budget > 0
    )
    has_include_thoughts = hasattr(reasoning_model, "include_thoughts") and reasoning_model.include_thoughts is not None

    return is_gemini_class and (has_thinking_support or has_thinking_budget or has_include_thoughts)


def get_gemini_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_response: Optional[Union["RunOutput", "TeamRunOutput"]] = None,
) -> Optional[Message]:
    """Get reasoning from a Gemini model."""
    try:
        reasoning_agent_response = reasoning_agent.run(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    # Accumulate reasoning agent metrics into the parent run_response
    if run_response is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response, run_response, prefix="reasoning")

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
    run_response: Optional[Union["RunOutput", "TeamRunOutput"]] = None,
) -> Optional[Message]:
    """Get reasoning from a Gemini model asynchronously."""
    try:
        reasoning_agent_response = await reasoning_agent.arun(input=messages)
    except Exception as e:
        logger.warning(f"Reasoning error: {e}")
        return None

    # Accumulate reasoning agent metrics into the parent run_response
    if run_response is not None:
        from agno.metrics import accumulate_eval_metrics

        accumulate_eval_metrics(reasoning_agent_response, run_response, prefix="reasoning")

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
