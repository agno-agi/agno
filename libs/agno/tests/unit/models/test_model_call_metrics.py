"""Unit tests for the metrics a model call records: time to first token, the usage of each call, and the duration of a
streamed call."""

from typing import Any, AsyncIterator, Iterator, List, Optional

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse


class ScriptedModel(Model):
    """Minimal offline model: answers each call with the next of the given responses."""

    def __init__(self, responses: List[ModelResponse]):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._responses = responses

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
        return self._responses.pop(0)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._responses.pop(0)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._responses.pop(0)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._responses.pop(0)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def wait() -> str:
    """Wait a moment."""
    return "done"


def _tool_call(usage: Optional[MessageMetrics] = None) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "wait", "arguments": "{}"}}],
        response_usage=usage,
    )


def test_call_without_usage_adds_no_tokens():
    """A call that reports no usage adds nothing, never the usage of the call before it again."""
    usage = MessageMetrics(input_tokens=6, output_tokens=4, total_tokens=10)
    agent = Agent(
        model=ScriptedModel([_tool_call(usage), ModelResponse(role="assistant", content="ok")]),
        tools=[wait],
        telemetry=False,
    )

    run_output = agent.run("hi")

    assert run_output.metrics.total_tokens == 10


def test_streamed_call_records_its_duration():
    """The stream's end stops the timer of the call, so its message holds how long the request took."""
    agent = Agent(model=ScriptedModel([ModelResponse(role="assistant", content="ok")]), telemetry=False)

    run_output = list(agent.run("hi", stream=True, yield_run_output=True))[-1]

    assistant_message = [message for message in run_output.messages if message.role == "assistant"][-1]
    assert assistant_message.metrics.duration is not None
