from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import ReasoningContentDeltaEvent, RunContentEvent


class StreamingReasoningModel(Model):
    def __init__(self):
        super().__init__(id="openai-compatible-reasoner", name="openai-compatible-reasoner", provider="test")
        self.instructions = None

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
        return ModelResponse(content="Hello", role="assistant", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield ModelResponse(reasoning_content="The user", role="assistant")
        yield ModelResponse(reasoning_content=" said", role="assistant")
        yield ModelResponse(content="Hello", role="assistant", response_usage=MessageMetrics())

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for event in self.invoke_stream(*args, **kwargs):
            yield event

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self.invoke()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse()


def test_streamed_model_reasoning_content_emits_reasoning_delta_events():
    agent = Agent(model=StreamingReasoningModel())

    events = list(agent.run("Say hello", stream=True, stream_events=True))

    reasoning_deltas = [event for event in events if isinstance(event, ReasoningContentDeltaEvent)]
    assert [event.reasoning_content for event in reasoning_deltas] == ["The user", " said"]

    reasoning_run_content = [
        event for event in events if isinstance(event, RunContentEvent) and event.reasoning_content
    ]
    assert reasoning_run_content == []

    content_events = [event for event in events if isinstance(event, RunContentEvent) and event.content]
    assert [event.content for event in content_events] == ["Hello"]


@pytest.mark.asyncio
async def test_async_streamed_model_reasoning_content_emits_reasoning_delta_events():
    agent = Agent(model=StreamingReasoningModel())

    events = []
    async for event in agent.arun("Say hello", stream=True, stream_events=True):
        events.append(event)

    reasoning_deltas = [event for event in events if isinstance(event, ReasoningContentDeltaEvent)]
    assert [event.reasoning_content for event in reasoning_deltas] == ["The user", " said"]

    reasoning_run_content = [
        event for event in events if isinstance(event, RunContentEvent) and event.reasoning_content
    ]
    assert reasoning_run_content == []

    content_events = [event for event in events if isinstance(event, RunContentEvent) and event.content]
    assert [event.content for event in content_events] == ["Hello"]
