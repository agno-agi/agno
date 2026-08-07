from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional, Tuple

import httpx

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics


# Fallback substrings used only when the /api/show capability lookup fails (e.g. server unreachable).
_OLLAMA_FALLBACK_SUBSTRINGS = (
    "qwq",
    "deepseek-r1",
    "qwen3",
    "gpt-oss",
    "magistral",
    "openthinker",
    "phi4-reasoning",
    "minimax-m",
)


def _ollama_fallback(model_id: str) -> bool:
    return any(substring in model_id for substring in _OLLAMA_FALLBACK_SUBSTRINGS)


def _fetch_ollama_capabilities(reasoning_model: Model) -> Optional[List[str]]:
    """Fetch a model's capabilities from the raw Ollama /api/show endpoint.

    The endpoint is queried directly (rather than via client.show()) because older versions of the
    ollama python package drop the `capabilities` field when parsing the response. Returns None on
    any failure so the caller can fall back to substring matching.
    """
    host = getattr(reasoning_model, "host", None)
    api_key = getattr(reasoning_model, "api_key", None)
    if not host:
        # Mirror Ollama client defaults: cloud endpoint when an API key is set, else local.
        host = "https://ollama.com" if api_key else "http://localhost:11434"

    try:
        headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        response = httpx.post(
            f"{host.rstrip('/')}/api/show",
            json={"model": reasoning_model.id},
            headers=headers,
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json().get("capabilities")
    except Exception as e:
        log_warning(f"Could not determine Ollama thinking capability via API, falling back to model id: {str(e)}")
        return None


def is_ollama_reasoning_model(reasoning_model: Model) -> bool:
    """Check if an Ollama model supports thinking.

    Uses the Ollama API (POST /api/show -> capabilities) to detect thinking support, and falls
    back to a substring match on the model id only if the API call fails.
    """
    if reasoning_model.__class__.__name__ != "Ollama":
        return False

    capabilities = _fetch_ollama_capabilities(reasoning_model)
    if capabilities is not None:
        return "thinking" in capabilities

    return _ollama_fallback(reasoning_model.id)


def get_ollama_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
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


async def aget_ollama_reasoning(
    reasoning_agent: "Agent",  # type: ignore[name-defined]  # noqa: F821
    messages: List[Message],
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[Message]:
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
