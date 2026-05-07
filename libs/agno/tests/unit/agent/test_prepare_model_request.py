from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import PreparedAgentModelRequest
from agno.tools import tool
from agno.tools.function import Function


class InspectOnlyModel(Model):
    def __init__(self):
        super().__init__(id="inspect-model", name="inspect-model", provider="test")
        self.invoke_calls = 0
        self.ainvoke_calls = 0

    def get_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def parse_args(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.invoke_calls += 1
        raise AssertionError("prepare_model_request must not invoke the model")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.ainvoke_calls += 1
        raise AssertionError("aprepare_model_request must not invoke the model")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        self.invoke_calls += 1
        raise AssertionError("prepare_model_request must not invoke the model")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        self.ainvoke_calls += 1
        raise AssertionError("aprepare_model_request must not invoke the model")
        yield ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse()


def test_prepare_model_request_returns_agent_messages_tools_and_context():
    @tool(instructions="Use echo for exact repeats.")
    def echo(text: str) -> str:
        return text

    model = InspectOnlyModel()
    agent = Agent(
        name="Inspector",
        model=model,
        instructions="Be precise.",
        tools=[echo],
    )

    prepared = agent.prepare_model_request(
        "hello",
        session_id="session-1",
        user_id="user-1",
        run_id="run-1",
        metadata={"source": "test"},
    )

    assert isinstance(prepared, PreparedAgentModelRequest)
    assert prepared.run_response.run_id == "run-1"
    assert prepared.run_response.session_id == "session-1"
    assert prepared.run_context.user_id == "user-1"
    assert prepared.run_context.metadata == {"source": "test"}
    assert prepared.session.session_id == "session-1"
    assert prepared.user_message is not None
    assert prepared.user_message.content == "hello"
    assert prepared.system_message is not None
    assert "Be precise." in str(prepared.system_message.content)
    assert prepared.messages == prepared.run_messages.messages
    assert [tool.name for tool in prepared.tools if isinstance(tool, Function)] == ["echo"]
    assert prepared.tool_instructions == ["Use echo for exact repeats."]
    assert model.invoke_calls == 0
    assert model.ainvoke_calls == 0


@pytest.mark.asyncio
async def test_aprepare_model_request_supports_async_tools_without_model_invocation():
    @tool(instructions="Use async echo for exact repeats.")
    async def async_echo(text: str) -> str:
        return text

    model = InspectOnlyModel()
    agent = Agent(name="Async Inspector", model=model, tools=[async_echo])

    prepared = await agent.aprepare_model_request(
        "hello async",
        session_id="session-async",
        user_id="user-async",
        run_id="run-async",
    )

    assert prepared.run_response.run_id == "run-async"
    assert prepared.user_message is not None
    assert prepared.user_message.content == "hello async"
    assert [tool.name for tool in prepared.tools if isinstance(tool, Function)] == ["async_echo"]
    assert prepared.tool_instructions == ["Use async echo for exact repeats."]
    assert model.invoke_calls == 0
    assert model.ainvoke_calls == 0
