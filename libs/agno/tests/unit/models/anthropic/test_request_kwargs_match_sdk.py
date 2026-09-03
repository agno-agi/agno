"""The request kwargs a Claude model builds must be accepted by the installed Anthropic SDK.

``_prepare_request_kwargs`` output is splatted into the SDK call, so a parameter the SDK
does not declare raises ``TypeError`` before the request leaves the process: the run fails
with no HTTP call made and no provider error to read. anthropic 1.0.0 dropped
``output_format``, ``temperature``, ``top_p`` and ``top_k`` from its request methods
exactly that way.

Two things follow, and both are what these tests pin:

* Every configuration has to be bound, not just a default model. A parameter that only
  appears once a caller sets a field is invisible to a test that builds ``Claude(id=...)``
  and nothing else -- which is how the sampling parameters went unnoticed.
* One set of kwargs reaches four surfaces -- stable and beta, streaming and not -- and they
  do not take the same parameters, so every case is bound against all the surfaces its
  request can actually reach, on the client of its own provider.
"""

import inspect
from importlib import import_module
from typing import Any, Callable, Dict, List, Optional

import pytest
from anthropic import Anthropic, AnthropicBedrock, AnthropicFoundry, AnthropicVertex
from pydantic import BaseModel

from agno.models.anthropic.claude import Claude
from agno.utils.models.claude import SAMPLING_PARAMS


class _Schema(BaseModel):
    answer: str


# Each provider's model module next to the client its requests are actually made on: the
# four clients are separate generated classes and drift apart from one another.
#
# The model classes are imported inside the tests rather than here, because importing
# agno.models.azure pulls in azure-ai-inference and so registers the installed `azure`
# namespace package. tests/unit/models/azure/ is itself collected as `azure.<module>`,
# which that import makes unresolvable for every test module collected after this one.
PROVIDERS = {
    "anthropic": ("agno.models.anthropic.claude", lambda: Anthropic(api_key="test")),
    "aws": (
        "agno.models.aws.claude",
        lambda: AnthropicBedrock(aws_region="us-east-1", aws_access_key="k", aws_secret_key="s"),
    ),
    "azure": ("agno.models.azure.claude", lambda: AnthropicFoundry(api_key="test", base_url="https://example.invalid")),
    "vertexai": ("agno.models.vertexai.claude", lambda: AnthropicVertex(region="us-east5", project_id="test")),
}


def _model_class(provider: str) -> type:
    return import_module(PROVIDERS[provider][0]).Claude


# Fields a caller can set that add or change a request parameter. `temperature` and
# `top_p` are kept apart because the API rejects the pair for a single request.
CONFIGURATIONS = {
    "default": {},
    "temperature": {"temperature": 0.2},
    "top_p": {"top_p": 0.9},
    "top_k": {"top_k": 5},
    "stop_sequences": {"stop_sequences": ["STOP"]},
    "max_tokens": {"max_tokens": 128},
    "output_config": {"output_config": {"effort": "high"}},
    "betas": {"betas": ["context-1m-2025-08-07"]},
    "request_params": {"request_params": {"metadata": {"user_id": "u1"}}},
    "everything": {
        "temperature": 0.2,
        "top_k": 5,
        "stop_sequences": ["STOP"],
        "max_tokens": 128,
        "output_config": {"effort": "high"},
        "betas": ["context-1m-2025-08-07"],
    },
}


@pytest.fixture(scope="module")
def clients():
    return {name: build() for name, (_, build) in PROVIDERS.items()}


def _surfaces(client: Any, model: Claude, response_format: Optional[Any] = None) -> List[Callable]:
    """Both the streaming and non-streaming call this model will really make.

    Older SDKs do not expose every surface on every client -- Bedrock grew
    ``beta.messages.stream`` only in 0.122.0 -- so only what is there is bound.
    """
    messages = client.beta.messages if model._has_beta_features(response_format=response_format) else client.messages
    return [surface for surface in (getattr(messages, "create", None), getattr(messages, "stream", None)) if surface]


def _bind(create: Callable, request_kwargs: Dict[str, Any]) -> None:
    """Fail exactly where a real call would, without sending one."""
    inspect.signature(create).bind_partial(model="claude-sonnet-4-5", messages=[], **request_kwargs)


@pytest.mark.parametrize("provider", list(PROVIDERS))
def test_the_bind_check_can_actually_fail(clients, provider):
    """A **kwargs-accepting signature would swallow anything and make the rest vacuous."""
    client = clients[provider]
    every_surface = [
        getattr(messages, name, None)
        for messages in (client.messages, client.beta.messages)
        for name in ("create", "stream")
    ]
    for surface in [surface for surface in every_surface if surface]:
        assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in inspect.signature(surface).parameters.values())
        with pytest.raises(TypeError):
            _bind(surface, {"not_a_real_anthropic_parameter": 1})


@pytest.mark.parametrize("provider", list(PROVIDERS))
@pytest.mark.parametrize("configuration", list(CONFIGURATIONS))
@pytest.mark.parametrize("response_format", [None, _Schema], ids=["plain", "structured_output"])
def test_every_configuration_is_accepted(clients, provider, configuration, response_format):
    model = _model_class(provider)(**CONFIGURATIONS[configuration])

    kwargs = model._prepare_request_kwargs("sys", response_format=response_format)

    for surface in _surfaces(clients[provider], model, response_format):
        _bind(surface, kwargs)


@pytest.mark.parametrize("provider", list(PROVIDERS))
def test_sampling_params_travel_in_extra_body(provider):
    """The SDK stopped declaring them in 1.0.0; the API still reads them from the body."""
    model = _model_class(provider)(temperature=0.2, top_k=5)

    kwargs = model._prepare_request_kwargs("sys")

    assert not any(name in kwargs for name in SAMPLING_PARAMS)
    assert kwargs["extra_body"] == {"temperature": 0.2, "top_k": 5}


def test_a_sampling_param_set_through_request_params_is_routed_too():
    """request_params is a raw passthrough, so the same parameter can arrive that way."""
    model = Claude(id="claude-sonnet-4-5", request_params={"top_p": 0.9})

    kwargs = model._prepare_request_kwargs("sys")

    assert "top_p" not in kwargs
    assert kwargs["extra_body"] == {"top_p": 0.9}


def test_an_explicit_extra_body_outranks_the_model_fields():
    supplied = {"extra_body": {"temperature": 0.9}}
    model = Claude(id="claude-sonnet-4-5", temperature=0.2, request_params=supplied)

    kwargs = model._prepare_request_kwargs("sys")

    assert kwargs["extra_body"] == {"temperature": 0.9}
    assert supplied == {"extra_body": {"temperature": 0.9}}, "the caller's request_params was mutated"


def test_a_second_run_does_not_accumulate_sampling_state():
    model = Claude(id="claude-sonnet-4-5", temperature=0.2)

    first = model._prepare_request_kwargs("sys")
    second = model._prepare_request_kwargs("sys")

    assert first["extra_body"] == second["extra_body"] == {"temperature": 0.2}
    assert model.temperature == 0.2, "the model's own field was consumed"


def test_structured_output_routes_to_the_surfaces_that_take_its_kwargs(clients):
    """The beta header rides along with the schema, and only the beta surfaces take it."""
    client = clients["anthropic"]
    model = Claude(id="claude-sonnet-4-5")

    kwargs = model._prepare_request_kwargs("sys", response_format=_Schema)

    assert "structured-outputs-2025-11-13" in kwargs["betas"]
    assert _surfaces(client, model, _Schema) == [client.beta.messages.create, client.beta.messages.stream]


def test_the_schema_is_nested_under_output_config_format():
    kwargs = Claude(id="claude-sonnet-4-5")._prepare_request_kwargs("sys", response_format=_Schema)

    assert "output_format" not in kwargs, "output_format was removed from create() in anthropic 1.0.0"
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


def test_a_second_run_does_not_accumulate_output_config():
    """get_request_params returns a shallow copy, so an in-place merge would leak."""
    model = Claude(id="claude-sonnet-4-5", output_config={"effort": "high"})

    model._prepare_request_kwargs("sys", response_format=_Schema)
    plain = model._prepare_request_kwargs("sys")

    assert plain["output_config"] == {"effort": "high"}
