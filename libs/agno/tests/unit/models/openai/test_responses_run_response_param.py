"""Every Responses-family provider must accept the run_response kwarg.

OpenAIResponses.invoke threads run_response into get_request_params on all four
legs, and self is whatever subclass the user built. A subclass that OVERRIDES
get_request_params without the parameter raises TypeError on every run - it does
not "inherit it inert", because it does not inherit it at all.
"""

import importlib
import pkgutil
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


def _import_every_model_module() -> None:
    """__subclasses__() only sees classes that have been IMPORTED.

    Listing providers by hand is what let two of these through already: a
    subclass nobody remembered to add to the list is exactly the one that
    breaks. Walk the package instead, so a provider added tomorrow is covered
    without anyone editing this file. Providers whose optional dependency is
    missing raise on import and are skipped - they cannot be running either.
    """
    import agno.models

    for module in pkgutil.walk_packages(agno.models.__path__, prefix="agno.models."):
        try:
            importlib.import_module(module.name)
        except Exception:  # noqa: BLE001 - a provider we cannot import cannot run
            continue


def _descendants(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _descendants(sub)


def test_no_responses_subclass_narrows_the_signature():
    """Any override must keep run_response, or the base's invoke legs break it."""
    _import_every_model_module()

    offenders = []
    for subclass in [OpenAIResponses, *_descendants(OpenAIResponses)]:
        own = subclass.__dict__.get("get_request_params")
        if own is not None and "run_response" not in signature(own).parameters:
            offenders.append(subclass.__name__)

    assert offenders == []
