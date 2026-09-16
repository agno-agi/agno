"""Tests for the OpenAI request parameter types.

The installed OpenAI SDK is the reference for which values exist. A test here fails when the SDK
names a value `agno.models.openai.types` does not, which means the completions and the comments in
that module are behind the API. The aliases accept any string, so a value missing from them never
blocks a caller.
"""

from typing import Any, Literal, Set, get_args, get_origin

from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses
from agno.models.openai.types import ReasoningEffort, ReasoningSummary, ServiceTier, Verbosity


def named_values(alias: Any) -> Set[str]:
    """Return the values named by the Literal inside a type alias."""
    for arg in get_args(alias):
        if get_origin(arg) is Literal:
            return set(get_args(arg))
    raise AssertionError(f"{alias} names no Literal values")


def test_named_values_reads_the_literal_out_of_an_alias():
    assert named_values(ReasoningSummary) == {"auto", "concise", "detailed"}


def test_aliases_accept_values_they_do_not_name():
    for alias in (ReasoningEffort, ReasoningSummary, ServiceTier, Verbosity):
        assert str in get_args(alias), f"{alias} rejects values it does not name"


def test_reasoning_effort_names_every_sdk_value():
    from openai.types.shared.reasoning_effort import ReasoningEffort as SDKReasoningEffort

    assert named_values(SDKReasoningEffort) <= named_values(ReasoningEffort)


def test_reasoning_summary_names_every_sdk_value():
    from openai.types.shared.reasoning import Reasoning

    assert named_values(Reasoning.model_fields["summary"].annotation) <= named_values(ReasoningSummary)


def test_verbosity_names_every_sdk_value():
    from openai.types.responses.response_text_config import ResponseTextConfig

    assert named_values(ResponseTextConfig.model_fields["verbosity"].annotation) <= named_values(Verbosity)


def test_service_tier_names_every_sdk_value():
    from openai.types.chat.chat_completion import ChatCompletion
    from openai.types.responses.response import Response

    assert named_values(Response.model_fields["service_tier"].annotation) <= named_values(ServiceTier)
    assert named_values(ChatCompletion.model_fields["service_tier"].annotation) <= named_values(ServiceTier)


def test_responses_sends_an_effort_the_aliases_do_not_name():
    model = OpenAIResponses(id="gpt-5.6", api_key="test-key", reasoning_effort="ultra", reasoning_summary="brief")

    params = model.get_request_params()

    assert params["reasoning"] == {"effort": "ultra", "summary": "brief"}


def test_responses_sends_a_service_tier_and_verbosity_the_aliases_do_not_name():
    model = OpenAIResponses(id="gpt-5.6", api_key="test-key", service_tier="hyperfast", verbosity="terse")

    params = model.get_request_params()

    assert params["service_tier"] == "hyperfast"
    assert params["text"]["verbosity"] == "terse"


def test_chat_sends_values_the_aliases_do_not_name():
    model = OpenAIChat(id="gpt-5.6", api_key="test-key", reasoning_effort="ultra", service_tier="hyperfast")

    params = model.get_request_params()

    assert params["reasoning_effort"] == "ultra"
    assert params["service_tier"] == "hyperfast"
