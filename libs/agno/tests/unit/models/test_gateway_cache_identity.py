import pytest

from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.openrouter import OpenRouter, OpenRouterResponses
from agno.models.ramp import RampRouter

MESSAGES = [Message(role="user", content="hi")]

GATEWAYS = [
    (RampRouter, "gpt-5.6-luna", ["openai:gpt-5-nano"], ["anthropic:claude-haiku-4-5"]),
    (OpenRouter, "openai/gpt-4o", ["anthropic/claude-sonnet-4"], ["deepseek/deepseek-r1"]),
    (OpenRouterResponses, "openai/gpt-4o", ["anthropic/claude-sonnet-4"], ["deepseek/deepseek-r1"]),
]
GATEWAY_IDS = [g[0].__name__ for g in GATEWAYS]


def _key(model):
    return model._get_model_cache_key(MESSAGES, stream=False)


@pytest.mark.parametrize("cls, model_id, models_a, models_b", GATEWAYS, ids=GATEWAY_IDS)
def test_differing_candidate_lists_do_not_share_a_cache_entry(cls, model_id, models_a, models_b):
    """Two routers over different candidates must not collide, or one serves the other's response."""
    a = cls(api_key="test-key", id=model_id, models=models_a)
    b = cls(api_key="test-key", id=model_id, models=models_b)

    assert _key(a) != _key(b)


@pytest.mark.parametrize("cls, model_id, models_a, _models_b", GATEWAYS, ids=GATEWAY_IDS)
def test_identical_candidate_lists_still_share_a_cache_entry(cls, model_id, models_a, _models_b):
    """The fix must not defeat caching for genuinely identical configurations."""
    a = cls(api_key="test-key", id=model_id, models=models_a)
    b = cls(api_key="test-key", id=model_id, models=models_a)

    assert _key(a) == _key(b)


@pytest.mark.parametrize("cls, model_id, _models_a, _models_b", GATEWAYS, ids=GATEWAY_IDS)
def test_unset_candidates_leave_the_key_unchanged(cls, model_id, _models_a, _models_b):
    """Without a candidate list a gateway keys exactly as any other model, so caches stay valid."""
    gateway = cls(api_key="test-key", id=model_id)
    plain = OpenAIChat(id=model_id, api_key="test-key")

    assert _key(gateway) == _key(plain)