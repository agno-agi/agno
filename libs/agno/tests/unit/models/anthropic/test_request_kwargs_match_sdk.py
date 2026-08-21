"""The request kwargs Claude builds must be accepted by the installed Anthropic SDK.

``_prepare_request_kwargs`` output is splatted into the SDK call, so a parameter the
SDK does not declare raises ``TypeError`` before the request leaves the process: the
run fails with no HTTP call made and no provider error to read. anthropic 1.0.0
dropped ``output_format`` from ``create()`` exactly that way.

One set of kwargs reaches four surfaces -- stable and beta, streaming and not -- and
they do not take the same parameters, so every case is bound against all the surfaces
its request can actually reach.
"""

import inspect
from typing import Any, Callable, Dict, List, Optional

import pytest
from anthropic import Anthropic
from pydantic import BaseModel

from agno.models.anthropic.claude import Claude


class _Schema(BaseModel):
    answer: str


@pytest.fixture(scope="module")
def client():
    return Anthropic(api_key="test")


def _surfaces(client: Anthropic, model: Claude, response_format: Optional[Any] = None) -> List[Callable]:
    """Both the streaming and non-streaming call the model will really make."""
    if model._has_beta_features(response_format=response_format):
        return [client.beta.messages.create, client.beta.messages.stream]
    return [client.messages.create, client.messages.stream]


def _bind(create: Callable, request_kwargs: Dict[str, Any]) -> None:
    """Fail exactly where a real call would, without sending one."""
    inspect.signature(create).bind_partial(model="claude-sonnet-4-5", messages=[], **request_kwargs)


def test_the_bind_check_can_actually_fail(client):
    """A **kwargs-accepting signature would swallow anything and make the rest vacuous."""
    every_surface = [
        client.messages.create,
        client.messages.stream,
        client.beta.messages.create,
        client.beta.messages.stream,
    ]
    for surface in every_surface:
        assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in inspect.signature(surface).parameters.values())
        with pytest.raises(TypeError):
            _bind(surface, {"not_a_real_anthropic_parameter": 1})


def test_structured_output_kwargs_are_accepted(client):
    model = Claude(id="claude-sonnet-4-5")

    kwargs = model._prepare_request_kwargs("sys", response_format=_Schema)

    assert "output_format" not in kwargs, "output_format was removed from create() in anthropic 1.0.0"
    for surface in _surfaces(client, model, _Schema):
        _bind(surface, kwargs)


def test_a_plain_request_is_accepted(client):
    model = Claude(id="claude-sonnet-4-5")

    kwargs = model._prepare_request_kwargs("sys")

    assert "output_config" not in kwargs
    for surface in _surfaces(client, model):
        _bind(surface, kwargs)


def test_structured_output_routes_to_the_surfaces_that_take_its_kwargs(client):
    """The beta header rides along with the schema, and only the beta surfaces take it."""
    model = Claude(id="claude-sonnet-4-5")

    kwargs = model._prepare_request_kwargs("sys", response_format=_Schema)

    assert "structured-outputs-2025-11-13" in kwargs["betas"]
    assert _surfaces(client, model, _Schema) == [client.beta.messages.create, client.beta.messages.stream]


def test_the_schema_is_nested_under_output_config_format():
    kwargs = Claude(id="claude-sonnet-4-5")._prepare_request_kwargs("sys", response_format=_Schema)

    fmt = kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["properties"]["answer"]["type"] == "string"


def test_a_caller_supplied_output_config_survives_and_is_not_mutated():
    supplied = {"effort": "high"}
    model = Claude(id="claude-sonnet-4-5", output_config=supplied)

    kwargs = model._prepare_request_kwargs("sys", response_format=_Schema)

    assert kwargs["output_config"]["effort"] == "high", "the caller's effort was dropped"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert supplied == {"effort": "high"}, "the model's own output_config was mutated"
    assert model.output_config == {"effort": "high"}


def test_a_second_run_does_not_accumulate_state():
    """The shallow copy means an in-place merge would leak into every later request."""
    model = Claude(id="claude-sonnet-4-5", output_config={"effort": "high"})

    model._prepare_request_kwargs("sys", response_format=_Schema)
    plain = model._prepare_request_kwargs("sys")

    assert plain["output_config"] == {"effort": "high"}
