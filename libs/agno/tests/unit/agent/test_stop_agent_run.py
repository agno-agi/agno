from typing import Any, AsyncIterator, Callable, Iterator, Optional

import pytest

from agno.agent.agent import Agent
from agno.exceptions import RetryAgentRun, StopAgentRun
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunContentEvent

AGENT_MESSAGE = "Value 200 exceeds the threshold. Stopping tool execution."
RETRY_GUIDANCE = "Try the tool call again with corrected input."
SECOND_TURN = "The retry completed successfully."
TOOL_ERROR = "Value 200 exceeds the threshold."


class ToolCallModel(Model):
    """Offline model that requests a configured tool, then optionally returns text."""

    def __init__(
        self,
        tool_name: str = "check_threshold",
        arguments: str = '{"value": 200}',
        second_turn_content: Optional[str] = None,
    ) -> None:
        super().__init__(id="test-model", name="test-model", provider="test")
        self.call_count = 0
        self._tool_response = ModelResponse(
            content="",
            role="assistant",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": arguments},
                }
            ],
            response_usage=MessageMetrics(),
        )
        self._second_turn_content = second_turn_content

    def _next_response(self) -> ModelResponse:
        self.call_count += 1
        if self.call_count > 1 and self._second_turn_content is not None:
            return ModelResponse(
                content=self._second_turn_content,
                role="assistant",
                response_usage=MessageMetrics(),
            )
        return self._tool_response

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._next_response()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._next_response()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next_response()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next_response()

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._tool_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._tool_response


def check_threshold(value: int) -> str:
    raise StopAgentRun(TOOL_ERROR, agent_message=AGENT_MESSAGE)


def stop_without_message() -> str:
    raise StopAgentRun("Stopping without a caller-facing message.")


def stop_with_user_message_only() -> str:
    raise StopAgentRun("Stopping with model input only.", user_message="USER-MESSAGE")


def retry_with_message() -> str:
    raise RetryAgentRun("Retrying the tool call.", agent_message=RETRY_GUIDANCE)


def make_agent(tool: Callable[..., str] = check_threshold, model: Optional[ToolCallModel] = None) -> Agent:
    return Agent(model=model or ToolCallModel(), tools=[tool])


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


def test_stop_agent_run_without_agent_message_adds_no_content():
    model = ToolCallModel(tool_name="stop_without_message", arguments="{}")

    response = make_agent(stop_without_message, model).run("Stop")

    assert not response.content
    assert model.call_count == 1


def test_stop_agent_run_user_message_is_not_run_content():
    model = ToolCallModel(tool_name="stop_with_user_message_only", arguments="{}")

    response = make_agent(stop_with_user_message_only, model).run("Stop")

    assert not response.content
    assert model.call_count == 1


def test_retry_agent_run_agent_message_stays_internal():
    model = ToolCallModel(
        tool_name="retry_with_message",
        arguments="{}",
        second_turn_content=SECOND_TURN,
    )

    response = make_agent(retry_with_message, model).run("Retry")

    assert response.content == SECOND_TURN
    assert RETRY_GUIDANCE not in str(response.content)
    assert model.call_count == 2
