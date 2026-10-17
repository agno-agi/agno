"""Regression tests for routed-provider ``max_tokens`` request defaults.

Routed providers must not impose Agno's historical 1024-token limit when callers
leave ``max_tokens`` unset. Explicit limits must still be forwarded unchanged.
"""

from typing import Type

import pytest

from agno.models.openai.like import OpenAILike
from agno.models.openrouter import OpenRouter
from agno.models.perplexity import Perplexity
from agno.models.requesty import Requesty

ROUTED_PROVIDER_TYPES: tuple[Type[OpenAILike], ...] = (OpenRouter, Perplexity, Requesty)


@pytest.mark.parametrize("model_type", ROUTED_PROVIDER_TYPES)
def test_routed_provider_omits_default_max_tokens(model_type: Type[OpenAILike]):
    """An unset limit lets the selected upstream model determine its output cap."""
    model = model_type(api_key="test-key")

    request_params = model.get_request_params()

    assert "max_tokens" not in request_params


@pytest.mark.parametrize("model_type", ROUTED_PROVIDER_TYPES)
def test_routed_provider_forwards_explicit_max_tokens(model_type: Type[OpenAILike]):
    """A caller-provided output limit remains part of the provider request."""
    model = model_type(api_key="test-key", max_tokens=4096)

    request_params = model.get_request_params()

    assert request_params["max_tokens"] == 4096
