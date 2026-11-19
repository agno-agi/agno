import json
from typing import Any, AsyncIterator, Iterator

import pytest
from pydantic import BaseModel

from agno.agent import _response
from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.tools.decorator import tool


class StructuredResponse(BaseModel):
    message: str


class ToolCallingModel(Model):
    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self._mock_response = ModelResponse(
            role="assistant",
            response_usage=MessageMetrics(),
            tool_calls=[
                {
                    "id": "call-load-config",
                    "type": "function",
                    "function": {
                        "name": "load_config",
                        "arguments": json.dumps({"name": "config"}),
                    },
                }
            ],
        )

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


@tool(stop_after_tool_call=True)
def load_config(name: str) -> str:
    return f"Loaded: {name}"


def test_run_skips_output_schema_conversion_after_stop_after_tool_call(monkeypatch: pytest.MonkeyPatch):
    called = False

    def fail_if_parsed(*args, **kwargs):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(_response, "parse_response_model_str", fail_if_parsed)

    agent = Agent(model=ToolCallingModel(), tools=[load_config], output_schema=StructuredResponse)

    response = agent.run("load the config")

    assert called is False
    assert response.content == "Loaded: config"
    assert response.tools is not None
    assert response.tools[0].stop_after_tool_call is True


@pytest.mark.asyncio
async def test_arun_skips_output_schema_conversion_after_stop_after_tool_call(monkeypatch: pytest.MonkeyPatch):
    called = False

    def fail_if_parsed(*args, **kwargs):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(_response, "parse_response_model_str", fail_if_parsed)

    agent = Agent(model=ToolCallingModel(), tools=[load_config], output_schema=StructuredResponse)

    response = await agent.arun("load the config")

    assert called is False
    assert response.content == "Loaded: config"
    assert response.tools is not None
    assert response.tools[0].stop_after_tool_call is True
