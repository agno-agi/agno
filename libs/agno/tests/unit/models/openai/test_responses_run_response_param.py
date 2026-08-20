"""Every Responses-family provider must accept the run_response kwarg.

OpenAIResponses.invoke threads run_response into get_request_params on all four
legs, and self is whatever subclass the user built. A subclass that OVERRIDES
get_request_params without the parameter raises TypeError on every run - it does
not "inherit it inert", because it does not inherit it at all.
"""

from inspect import signature

import pytest

from agno.models.openai.open_responses import OpenResponses
from agno.models.openai.responses import OpenAIResponses
from agno.models.openrouter.responses import OpenRouterResponses
from agno.models.xai.responses import xAIResponses

# Providers whose optional dependency is not installed in the dev venv are
# covered by the subclass sweep below rather than instantiated here.
RESPONSES_PROVIDERS = [OpenAIResponses, OpenResponses, OpenRouterResponses, xAIResponses]


@pytest.mark.parametrize("provider", RESPONSES_PROVIDERS, ids=lambda p: p.__name__)
def test_get_request_params_accepts_run_response(provider):
    model = provider(api_key="test-key")

    params = model.get_request_params(run_response=None)

    assert isinstance(params, dict)


def test_no_responses_subclass_narrows_the_signature():
    """Any override must keep run_response, or the base's invoke legs break it."""
    offenders = []
    for subclass in [OpenAIResponses, *_descendants(OpenAIResponses)]:
        own = subclass.__dict__.get("get_request_params")
        if own is not None and "run_response" not in signature(own).parameters:
            offenders.append(subclass.__name__)

    assert offenders == []


def _descendants(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _descendants(sub)
