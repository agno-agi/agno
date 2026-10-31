"""Tests for how ``OpenAIResponses`` builds the ``reasoning`` request parameter.

``_set_reasoning_request_param`` derives the ``effort`` and ``summary`` request fields from the
model's ``reasoning_effort``/``reasoning_summary`` attributes. Writing those into
``self.reasoning`` itself would turn one request's derived parameters into permanent model state:
the dict a caller passed in is mutated, two models built from the same config dict leak into each
other, and a later ``reasoning_effort = None`` cannot undo the value the first request left behind.
The parameter must be a copy.

The provider-specific overrides of this method (``xai``, ``openrouter``, ``ramp``) already copy
before writing, so these tests pin the base class to the rule its own subclasses follow.
"""

from agno.models.azure.openai_responses import AzureOpenAIResponses
from agno.models.openai.responses import OpenAIResponses


def test_reasoning_config_is_not_mutated_by_a_request():
    config = {"effort": "low"}
    model = OpenAIResponses(id="gpt-5-mini", reasoning=config, reasoning_effort="high", reasoning_summary="detailed")

    params = model.get_request_params(messages=[])

    assert params["reasoning"] == {"effort": "high", "summary": "detailed"}
    assert config == {"effort": "low"}, "the caller's dict was written through"
    assert model.reasoning == {"effort": "low"}
    assert params["reasoning"] is not model.reasoning


def test_two_models_sharing_one_reasoning_dict_do_not_leak():
    config = {"effort": "low"}
    first = OpenAIResponses(id="gpt-5-mini", reasoning=config, reasoning_effort="high", reasoning_summary="detailed")
    first.get_request_params(messages=[])

    second = OpenAIResponses(id="gpt-5-mini", reasoning=config)

    assert second.get_request_params(messages=[])["reasoning"] == {"effort": "low"}


def test_clearing_reasoning_effort_falls_back_to_the_configured_value():
    model = OpenAIResponses(id="gpt-5-mini", reasoning={"effort": "medium"}, reasoning_effort="high")
    model.get_request_params(messages=[])

    model.reasoning_effort = None

    assert model.get_request_params(messages=[])["reasoning"] == {"effort": "medium"}


def test_azure_openai_responses_does_not_mutate_its_reasoning_config():
    """The same helper serves every subclass that does not override it."""
    config = {"effort": "low"}
    model = AzureOpenAIResponses(
        id="reasoning-deployment",
        api_key="test-key",
        api_version="2025-03-01-preview",
        azure_endpoint="https://example.invalid",
        reasoning=config,
        reasoning_effort="high",
    )

    params = model.get_request_params(messages=[])

    assert params["reasoning"] == {"effort": "high"}
    assert config == {"effort": "low"}
    assert model.reasoning == {"effort": "low"}


def test_unset_reasoning_still_sends_an_empty_block():
    """Unset reasoning keeps sending ``reasoning: {}``, as the base class has always done.

    ``xai``, ``openrouter`` and ``ramp`` override the method to suppress the block; the base
    class and its other subclasses must keep emitting it.
    """
    model = OpenAIResponses(id="gpt-5-mini")

    params = model.get_request_params(messages=[])

    assert params["reasoning"] == {}
    assert model.reasoning is None


def test_empty_reasoning_dict_accepts_the_derived_effort():
    model = OpenAIResponses(id="gpt-5-mini", reasoning={}, reasoning_effort="high")

    params = model.get_request_params(messages=[])

    assert params["reasoning"] == {"effort": "high"}
    assert model.reasoning == {}
