from __future__ import annotations

from typing import Dict, List

import httpx

from agno.models.base import Model
from agno.utils.log import log_warning

# Fallback substrings used only when the /api/v1/models capability lookup fails. OpenRouter ids are
# namespaced (e.g. "openai/o3", "deepseek/deepseek-v4"), so we match ignoring the provider prefix.
_OPENROUTER_FALLBACK_SUBSTRINGS = (
    "o3",
    "o4",
    "gpt-5",
    "deepseek-r1",
    "deepseek-reasoner",
    "deepseek-v4",
    "gemini-2.5",
    "gemini-3",
    "qwen3",
    "gpt-oss",
    "grok-4",
    "minimax-m",
    "magistral",
)


def _fetch_openrouter_models(reasoning_model: Model) -> Dict[str, List[str]]:
    """Fetch {model_id: supported_parameters} from the OpenRouter models catalog.

    The /models endpoint is public, so no API key is required. Returns an empty mapping on any
    failure so the caller can fall back to substring matching.
    """
    base_url = getattr(reasoning_model, "base_url", None) or "https://openrouter.ai/api/v1"
    catalog: Dict[str, List[str]] = {}
    try:
        api_key = getattr(reasoning_model, "api_key", None)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=10.0)
        response.raise_for_status()
        for entry in response.json().get("data", []):
            model_id = entry.get("id")
            if model_id:
                catalog[model_id] = entry.get("supported_parameters") or []
    except Exception as e:
        log_warning(f"Could not fetch OpenRouter models catalog, falling back to model id: {str(e)}")
    return catalog


def _openrouter_fallback(model_id: str) -> bool:
    model_id = model_id.lower()
    return any(substring in model_id for substring in _OPENROUTER_FALLBACK_SUBSTRINGS)


def is_openrouter_reasoning_model(reasoning_model: Model) -> bool:
    """Check if an OpenRouter model supports reasoning.

    Uses the OpenRouter API (GET /api/v1/models -> supported_parameters) to detect reasoning
    support, and falls back to a substring match on the model id only if the API call fails or the
    model is not found in the catalog.
    """
    if reasoning_model.__class__.__name__ != "OpenRouter":
        return False

    catalog = _fetch_openrouter_models(reasoning_model)
    supported_parameters = catalog.get(reasoning_model.id)
    if supported_parameters is not None:
        return "reasoning" in supported_parameters

    return _openrouter_fallback(reasoning_model.id)
