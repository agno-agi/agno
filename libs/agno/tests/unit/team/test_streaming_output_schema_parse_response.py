from typing import Any, AsyncIterator, Iterator

import pytest
from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.team import RunCompletedEvent, RunContentEvent
from agno.team.team import Team


class ItemsSchema(BaseModel):
    items: list[str]


class MockStreamingSchemaModel(Model):
    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.invoke_calls = 0
        self.invoke_stream_calls = 0
        self.ainvoke_calls = 0
        self.ainvoke_stream_calls = 0

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
        self.invoke_calls += 1
        return ModelResponse(content='{"items":["a","b"]}', role="assistant", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        self.ainvoke_calls += 1
        return ModelResponse(content='{"items":["a","b"]}', role="assistant", response_usage=MessageMetrics())

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        self.invoke_stream_calls += 1
        yield ModelResponse(content='{"items":["a",', role="assistant")
        yield ModelResponse(content='"b"]}', role="assistant", response_usage=MessageMetrics())

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        self.ainvoke_stream_calls += 1
        yield ModelResponse(content='{"items":["a",', role="assistant")
        yield ModelResponse(content='"b"]}', role="assistant", response_usage=MessageMetrics())
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return ModelResponse(content='{"items":["a","b"]}', role="assistant", response_usage=MessageMetrics())

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse(content=response.content, role="assistant")


def test_team_streaming_remains_enabled_with_output_schema_and_parse_response():
    model = MockStreamingSchemaModel()
    team = Team(model=model, members=[], output_schema=ItemsSchema, parse_response=True)

    content_events = 0
    completed_event = None
    for event in team.run("Return items", stream=True, stream_events=True):
        if isinstance(event, RunContentEvent) and isinstance(event.content, str):
            content_events += 1
        if isinstance(event, RunCompletedEvent):
            completed_event = event

    assert model.invoke_stream_calls > 0
    assert model.invoke_calls == 0
    assert content_events > 0
    assert completed_event is not None
    assert isinstance(completed_event.content, ItemsSchema)
    assert completed_event.content.items == ["a", "b"]


@pytest.mark.asyncio
async def test_team_async_streaming_remains_enabled_with_output_schema_and_parse_response():
    model = MockStreamingSchemaModel()
    team = Team(model=model, members=[], output_schema=ItemsSchema, parse_response=True)

    content_events = 0
    completed_event = None
    async for event in team.arun("Return items", stream=True, stream_events=True):
        if isinstance(event, RunContentEvent) and isinstance(event.content, str):
            content_events += 1
        if isinstance(event, RunCompletedEvent):
            completed_event = event

    assert model.ainvoke_stream_calls > 0
    assert model.ainvoke_calls == 0
    assert content_events > 0
    assert completed_event is not None
    assert isinstance(completed_event.content, ItemsSchema)
    assert completed_event.content.items == ["a", "b"]
