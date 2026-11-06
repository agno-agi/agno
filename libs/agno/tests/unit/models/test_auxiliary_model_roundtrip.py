"""Agent and Team reconstruction must preserve every configured model stage."""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.registry import Registry
from agno.team import Team


@pytest.fixture(params=[Agent, Team], ids=["agent", "team"])
def component_class(request):
    return request.param


def _component(component_class, **kwargs):
    if component_class is Team:
        kwargs["members"] = []
    return component_class(id="pipeline", **kwargs)


@pytest.mark.parametrize("strict", [False, True])
def test_auxiliary_models_roundtrip(component_class, strict):
    original = _component(
        component_class,
        model=OpenAIResponses(id="main-model"),
        reasoning_model=OpenAIResponses(id="reasoning-model"),
        parser_model=OpenAIChat(id="parser-model"),
        output_model=OpenAIResponses(id="output-model"),
        parser_model_prompt="Parse the response.",
        output_model_prompt="Format the response.",
    )
    config = original.to_dict()

    rebuilt = component_class.from_dict(config, strict=strict)

    for field in ("model", "reasoning_model", "parser_model", "output_model"):
        model = getattr(rebuilt, field)
        assert type(model) is type(getattr(original, field))
        assert model.to_dict() == config[field]
    for field in ("parser_model", "output_model", "parser_model_prompt", "output_model_prompt"):
        assert rebuilt.to_dict()[field] == config[field]


@pytest.mark.parametrize("field", ["parser_model", "output_model"])
def test_auxiliary_model_reuses_registered_connection(component_class, field):
    model = OpenAIResponses(id="custom-model", base_url="https://example.test/v1", api_key="test-only")
    registry = Registry(models=[model])
    config = _component(component_class, **{field: model}).to_dict()

    rebuilt = component_class.from_dict(config, registry=registry, strict=True)

    assert getattr(rebuilt, field) is model
    assert "api_key" not in config[field]
    assert "base_url" not in config[field]


@pytest.mark.parametrize("field", ["parser_model", "output_model"])
def test_auxiliary_model_string(component_class, field):
    rebuilt = component_class.from_dict({"id": "pipeline", field: "openai:auxiliary-model"})

    model = getattr(rebuilt, field)
    assert isinstance(model, OpenAIResponses)
    assert model.id == "auxiliary-model"


@pytest.mark.parametrize("config", [{}, {"parser_model": None, "output_model": None}], ids=["absent", "null"])
def test_unconfigured_auxiliary_models_stay_unset(component_class, config):
    rebuilt = component_class.from_dict({"id": "pipeline", **config})

    assert rebuilt.parser_model is None
    assert rebuilt.output_model is None


@pytest.mark.parametrize("field", ["parser_model", "output_model"])
def test_invalid_auxiliary_model_is_not_silently_dropped(component_class, field):
    with pytest.raises(ValueError, match="is not supported"):
        component_class.from_dict({"id": "pipeline", field: "unknown-provider:auxiliary-model"})
