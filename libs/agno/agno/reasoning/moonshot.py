from __future__ import annotations

from os import getenv
from typing import TYPE_CHECKING, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import httpx

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics

# Fallback substrings used only when the /v1/models capability lookup fails. Kimi K3 always
# reasons, and the "thinking" variants (e.g. kimi-k2-thinking) are dedicated reasoning models.
_MOONSHOT_FALLBACK_SUBSTRINGS = (
    "k3",
    "thinking",
)


def _fetch_moonshot_models(reasoning_model: Model) -> Dict[str, bool]:
    """Fetch {model_id: supports_reasoning} from the Moonshot models catalog.

    Uses the OpenAI-compatible GET /v1/models endpoint, whose model objects carry a
    ``supports_reasoning`` boolean. Returns an empty mapping on any failure so the caller
    can fall back to substring matching.
    """
    base_url = getattr(reasoning_model, "base_url", None) or "https://api.moonshot.ai/v1"
    catalog: Dict[str, bool] = {}
    try:
        api_key = getattr(reasoning_model, "api_key", None) or getenv("MOONSHOT_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=10.0)
        response.raise_for_status()
        for entry in response.json().get("data", []):
            model_id = entry.get("id")
            if model_id:
                catalog[model_id] = bool(entry.get("supports_reasoning"))
    except Exception as e:
        log_warning(f"Could not fetch Moonshot models catalog, falling back to model id: {str(e)}")
    return catalog


def _moonshot_fallback(model_id: str) -> bool:
    model_id = model_id.lower()
    return any(substring in model_id for substring in _MOONSHOT_FALLBACK_SUBSTRINGS)


def is_moonshot_reasoning_model(reasoning_model: Model) -> bool:
    """Check if a Moonshot (Kimi) model supports reasoning.

    Uses the Moonshot API (GET /v1/models -> supports_reasoning) to detect reasoning
    support, and falls back to a substring match on the model id only if the API call fails
    or the model is not found in the catalog.
    """
    if reasoning_model.__class__.__name__ != "MoonShot":
        return False

    catalog = _fetch_moonshot_models(reasoning_model)
    supports_reasoning = catalog.get(reasoning_model.id)
    if supports_reasoning is not None:
        return supports_reasoning

    return _moonshot_fallback(reasoning_model.id)


def get_moonshot_reasoning(
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

    # Kimi returns its chain of thought in the OpenAI-compatible reasoning_content field.
    reasoning_content: str = ""
    if reasoning_agent_response.messages is not None:
        for msg in reasoning_agent_response.messages:
            if msg.reasoning_content is not None:
                reasoning_content = msg.reasoning_content
                break

    return Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )


async def aget_moonshot_reasoning(
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

    reasoning_content: str = ""
    if reasoning_agent_response.messages is not None:
        for msg in reasoning_agent_response.messages:
            if msg.reasoning_content is not None:
                reasoning_content = msg.reasoning_content
                break

    return Message(
        role="assistant", content=f"<thinking>\n{reasoning_content}\n</thinking>", reasoning_content=reasoning_content
    )


def get_moonshot_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> Iterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from a Kimi model.

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


async def aget_moonshot_reasoning_stream(
    reasoning_agent: "Agent",  # type: ignore  # noqa: F821
    messages: List[Message],
) -> AsyncIterator[Tuple[Optional[str], Optional[Message]]]:
    """
    Stream reasoning content from a Kimi model asynchronously.

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
