import pytest

from agno.agent import Agent
from agno.registry import Registry
from agno.tools import Toolkit
from agno.tools.function import Function


def echo(value: str) -> str:
    return value


@pytest.mark.parametrize("model", [None, "openai:test-model"])
@pytest.mark.parametrize("kind", ["callable", "function", "toolkit", "builtin"])
def test_serialization_preserves_tools_without_choosing_a_model(model, kind):
    builtin = {"type": "web_search"}
    toolkit = Toolkit(name="echo_tools", tools=[echo])
    tool = {"callable": echo, "function": Function.from_callable(echo), "toolkit": toolkit, "builtin": builtin}[kind]
    agent = Agent(model=model, tools=[tool])
    initial_model = agent.model

    config = agent.to_dict()

    assert agent.model is initial_model
    assert ("model" in config) is (model is not None)
    assert len(config["tools"]) == 1
    if kind == "builtin":
        assert config["tools"] == [builtin]
    else:
        assert config["tools"][0]["name"] == "echo"
        assert config["tools"][0]["parameters"]["properties"]["value"]["type"] == "string"
    if kind == "toolkit":
        assert config["tools"][0]["toolkit"] == "echo_tools"


def test_model_free_tools_survive_registry_round_trip():
    toolkit = Toolkit(name="echo_tools", tools=[echo])
    registry = Registry(tools=[toolkit])
    config = Agent(tools=[toolkit]).to_dict()

    restored = Agent.from_dict(config, registry=registry, strict=True)

    assert restored.model is None
    serialized_tool = restored.to_dict()["tools"][0]
    assert serialized_tool["name"] == config["tools"][0]["name"]
    assert serialized_tool["toolkit"] == "echo_tools"
    assert serialized_tool["parameters"]["properties"] == config["tools"][0]["parameters"]["properties"]
    assert restored.tools[0].entrypoint(value="hello") == "hello"


def test_empty_tools_do_not_add_a_serialized_tool_list():
    assert "tools" not in Agent().to_dict()
