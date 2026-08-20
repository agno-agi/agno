"""Serialization round-trip tests for the OpenRouter model classes.

`Model.to_dict` serializes only {id, name, provider}, and the rebuild path restores only those, so
the dynamic-routing `models` (fallback candidates) would silently drop on rehydration, leaving a
model pinned to its primary `id` alone. Both OpenRouter variants opt into a fuller round-trip via
to_dict/from_dict; credentials stay out.
"""

import pytest

from agno.models.openrouter import OpenRouter, OpenRouterResponses
from agno.models.utils import get_model_from_dict

MODELS = [
    ("OpenRouter", "OpenRouter", OpenRouter),
    ("OpenRouterResponses", "OpenRouterResponses", OpenRouterResponses),
]


@pytest.mark.parametrize("_label, name, cls", MODELS, ids=[m[0] for m in MODELS])
def test_to_dict_carries_the_fallback_models(_label, name, cls):
    """The fallback candidate list serializes, not just the primary id."""
    model = cls(api_key="test-key", models=["anthropic/claude-sonnet-4", "deepseek/deepseek-r1"])
    data = model.to_dict()

    assert data["models"] == ["anthropic/claude-sonnet-4", "deepseek/deepseek-r1"]
    assert data["name"] == name


@pytest.mark.parametrize("_label, _name, cls", MODELS, ids=[m[0] for m in MODELS])
def test_to_dict_omits_unset_models_and_the_api_key(_label, _name, cls):
    """A model without fallbacks serializes no `models`, and never the API key."""
    data = cls(api_key="super-secret").to_dict()

    assert "models" not in data
    assert "api_key" not in data


@pytest.mark.parametrize("_label, _name, cls", MODELS, ids=[m[0] for m in MODELS])
def test_fallback_models_survive_a_dict_round_trip(_label, _name, cls):
    """to_dict -> get_model_from_dict rebuilds the same class with its fallback list intact."""
    model = cls(api_key="test-key", models=["anthropic/claude-sonnet-4", "deepseek/deepseek-r1"])

    rebuilt = get_model_from_dict(model.to_dict())

    assert isinstance(rebuilt, cls)
    assert rebuilt.models == ["anthropic/claude-sonnet-4", "deepseek/deepseek-r1"]


@pytest.mark.parametrize("_label, _name, cls", MODELS, ids=[m[0] for m in MODELS])
def test_from_dict_ignores_unknown_and_sensitive_keys(_label, _name, cls):
    """from_dict passes only an allowlist to the constructor, so a stray api_key cannot slip in."""
    rebuilt = cls.from_dict({"id": "anthropic/claude-sonnet-4", "models": ["x/y"], "api_key": "leaked", "unknown": "z"})

    assert rebuilt.models == ["x/y"]
    assert rebuilt.api_key is None


def test_openrouter_chat_round_trips_tuning_config():
    """OpenRouter (chat) serializes tuning config, so from_dict must restore it, not just routing.

    OpenRouterResponses is Responses-based and serializes identity only, so this is chat-specific.
    """
    model = OpenRouter(api_key="test-key", temperature=0.5, top_p=0.9, max_tokens=321, models=["a/b"])

    rebuilt = get_model_from_dict(model.to_dict())

    assert isinstance(rebuilt, OpenRouter)
    assert rebuilt.temperature == 0.5
    assert rebuilt.top_p == 0.9
    assert rebuilt.max_tokens == 321
    assert rebuilt.models == ["a/b"]
    assert rebuilt.api_key is None
