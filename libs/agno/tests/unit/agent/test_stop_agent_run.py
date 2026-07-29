from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent.agent import Agent
from agno.exceptions import StopAgentRun
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunContentEvent

AGENT_MESSAGE = "Value 200 exceeds the threshold. Stopping tool execution."
TOOL_ERROR = "Value 200 exceeds the threshold."


class ToolCallModel(Model):
    """Offline model that always requests the tool which stops the run."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self._response = ModelResponse(
            content="",
            role="assistant",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "check_threshold", "arguments": '{"value": 200}'},
                }
            ],
            response_usage=MessageMetrics(),
        )

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._response

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._response


def check_threshold(value: int) -> str:
    raise StopAgentRun(TOOL_ERROR, agent_message=AGENT_MESSAGE)


def make_agent() -> Agent:
    return Agent(model=ToolCallModel(), tools=[check_threshold])


def test_stop_agent_run_agent_message_is_returned():
    response = make_agent().run("Check 200")

    assert response.content == AGENT_MESSAGE

    assert response.messages is not None
    tool_messages = [message for message in response.messages if message.role == "tool"]
    assistant_messages = [message for message in response.messages if message.role == "assistant"]

    assert tool_messages[-1].content == TOOL_ERROR
    assert tool_messages[-1].stop_after_tool_call is True
    assert assistant_messages[-1].content == AGENT_MESSAGE
    assert assistant_messages[-1].stop_after_tool_call is True


@pytest.mark.asyncio
async def test_stop_agent_run_agent_message_is_returned_async():
    response = await make_agent().arun("Check 200")

    assert response.content == AGENT_MESSAGE


def test_stop_agent_run_agent_message_is_streamed():
    events = list(make_agent().run("Check 200", stream=True))

    content = [event.content for event in events if isinstance(event, RunContentEvent) and event.content]
    assert content == [AGENT_MESSAGE]


@pytest.mark.asyncio
async def test_stop_agent_run_agent_message_is_streamed_async():
    events = [event async for event in make_agent().arun("Check 200", stream=True)]

    content = [event.content for event in events if isinstance(event, RunContentEvent) and event.content]
    assert content == [AGENT_MESSAGE]
