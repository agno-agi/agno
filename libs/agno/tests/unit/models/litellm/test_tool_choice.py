"""Tests for tool_choice forwarding in LiteLLM."""

from unittest.mock import MagicMock

from agno.models.litellm import LiteLLM


def test_get_request_params_honors_tool_choice():
    model = LiteLLM(id="openai/gpt-4o-mini", api_key="k")
    tools = [{"type": "function", "function": {"name": "f"}}]

    assert model.get_request_params(tools=tools)["tool_choice"] == "auto"
    assert model.get_request_params(tools=tools, tool_choice="none")["tool_choice"] == "none"
    assert model.get_request_params(tools=tools, tool_choice={"type": "function", "function": {"name": "f"}})[
        "tool_choice"
    ] == {"type": "function", "function": {"name": "f"}}


def test_invoke_forwards_tool_choice():
    model = LiteLLM(id="openai/gpt-4o-mini", api_key="k")
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="ok", reasoning_content=None, tool_calls=None))]
    resp.usage = None
    model.client = MagicMock()
    model.client.completion.return_value = resp

    from agno.agent import Agent

    def get_weather(city: str) -> str:
        return "sunny"

    Agent(model=model, tools=[get_weather], tool_choice="none").run("hi")
    assert model.client.completion.call_args.kwargs["tool_choice"] == "none"
