"""Round-trip tests for gateway/router models.

These classes carry a routing candidate list (``models``) that decides what actually runs, so
their config must survive ``Model.to_dict() -> get_model_from_dict()`` instead of silently
falling back to the default ``id``.
"""

import pytest

from agno.models.openrouter import OpenRouter, OpenRouterResponses
from agno.models.ramp import RampRouter
from agno.models.utils import get_model_from_dict


@pytest.mark.parametrize("model_class", [RampRouter, OpenRouter, OpenRouterResponses])
def test_gateway_models_field_round_trips(model_class):
    model = model_class(models=["openai:gpt-5-nano", "anthropic:claude-sonnet-4"], api_key="sk-secret")
    data = model.to_dict()

    assert "api_key" not in data

    rebuilt = get_model_from_dict(data)
    assert type(rebuilt) is type(model)
    assert rebuilt.models == ["openai:gpt-5-nano", "anthropic:claude-sonnet-4"]


def test_ramp_router_routing_config_round_trips():
    model = RampRouter(
        models=["openai:gpt-5-nano"],
        allow_flex_tier=False,
        provider_timeout=30.0,
        timeout_before_headers=5.0,
        api_key="sk-secret",
    )
    data = model.to_dict()

    assert "api_key" not in data

    rebuilt = get_model_from_dict(data)
    assert isinstance(rebuilt, RampRouter)
    assert rebuilt.models == ["openai:gpt-5-nano"]
    assert rebuilt.allow_flex_tier is False
    assert rebuilt.provider_timeout == 30.0
    assert rebuilt.timeout_before_headers == 5.0


def test_gateway_unset_routing_fields_stay_unserialized():
    """Fields left at None are omitted from the dict and stay None after rebuilding."""
    data = RampRouter().to_dict()
    for field_name in ("models", "allow_flex_tier", "provider_timeout", "timeout_before_headers"):
        assert field_name not in data

    rebuilt = get_model_from_dict(data)
    assert isinstance(rebuilt, RampRouter)
    assert rebuilt.models is None


def test_credentials_in_dict_are_never_restored():
    """Even a dict that (wrongly) contains a credential must not rehydrate it."""
    data = RampRouter(models=["openai:gpt-5-nano"]).to_dict()
    data["api_key"] = "sk-should-never-survive"

    rebuilt = get_model_from_dict(data)
    assert rebuilt.api_key is None
    assert rebuilt.models == ["openai:gpt-5-nano"]


def test_undeclared_constructor_fields_are_not_restored():
    """Reconstruction is allowlist-only: constructor fields outside _extra_serialized_fields
    must not rehydrate from a dict, even though the constructor would accept them. A dict from
    outside the process could otherwise redirect requests (base_url) or inject credentials
    (client_params, default_headers)."""
    default_base_url = RampRouter().base_url
    data = RampRouter(models=["openai:gpt-5-nano"]).to_dict()
    data["base_url"] = "https://attacker.example.com/v1"
    data["client_params"] = {"api_key": "sk-injected"}
    data["default_headers"] = {"Authorization": "Bearer stolen"}

    rebuilt = get_model_from_dict(data)
    assert rebuilt.base_url == default_base_url
    assert rebuilt.client_params is None
    assert rebuilt.default_headers is None
    assert rebuilt.models == ["openai:gpt-5-nano"]
