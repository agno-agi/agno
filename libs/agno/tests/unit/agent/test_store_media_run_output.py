"""Tests for store_media=False still returning media in RunOutput to caller.

Verifies fix for https://github.com/agno-agi/agno/issues/5101
"""

from typing import Any, AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock

import pytest

from agno.agent.agent import Agent
from agno.media import Image
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunCompletedEvent, RunOutput


class MockModelWithImage(Model):
    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None

        self._mock_response = ModelResponse(
            content="Here is your generated image",
            role="assistant",
            images=[Image(url="https://example.com/generated.png", id="img-1")],
            response_usage=MessageMetrics(),
        )

        self.response = Mock(return_value=self._mock_response)
        self.aresponse = AsyncMock(return_value=self._mock_response)

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
        return await self.aresponse(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def test_store_media_false_returns_images_to_caller():
    """Returned RunOutput should have images even with store_media=False."""
    agent = Agent(
        model=MockModelWithImage(),
        store_media=False,
    )

    result = agent.run("Generate an image")

    assert result.images is not None
    assert len(result.images) == 1
    assert result.images[0].url == "https://example.com/generated.png"


@pytest.mark.asyncio
async def test_store_media_false_returns_images_to_caller_async():
    """Async: returned RunOutput should have images even with store_media=False."""
    agent = Agent(
        model=MockModelWithImage(),
        store_media=False,
    )

    result = await agent.arun("Generate an image")

    assert result.images is not None
    assert len(result.images) == 1
    assert result.images[0].url == "https://example.com/generated.png"


def test_store_media_true_returns_images_to_caller():
    """With store_media=True (default), caller should still see images."""
    agent = Agent(
        model=MockModelWithImage(),
        store_media=True,
    )

    result = agent.run("Generate an image")

    assert result.images is not None
    assert len(result.images) == 1


def test_store_media_false_without_db():
    """store_media=False works correctly without any DB configured."""
    agent = Agent(
        model=MockModelWithImage(),
        store_media=False,
    )

    result = agent.run("Generate an image")

    assert result.images is not None
    assert len(result.images) == 1
    assert result.images[0].id == "img-1"


def test_store_media_false_streaming_with_yield_run_output():
    agent = Agent(
        model=MockModelWithImage(),
        store_media=False,
    )

    run_output = None
    for chunk in agent.run("Generate an image", stream=True, yield_run_output=True):
        if isinstance(chunk, RunOutput):
            run_output = chunk

    assert run_output is not None
    assert run_output.images is not None
    assert len(run_output.images) == 1
    assert run_output.images[0].url == "https://example.com/generated.png"


def test_store_media_false_streaming_with_stream_events():
    agent = Agent(
        model=MockModelWithImage(),
        store_media=False,
    )

    completed_event = None
    for chunk in agent.run("Generate an image", stream=True, stream_events=True):
        if isinstance(chunk, RunCompletedEvent):
            completed_event = chunk

    assert completed_event is not None
    assert completed_event.images is not None
    assert len(completed_event.images) == 1
    assert completed_event.images[0].url == "https://example.com/generated.png"


@pytest.mark.asyncio
async def test_store_media_false_async_streaming_with_yield_run_output():
    agent = Agent(
        model=MockModelWithImage(),
        store_media=False,
    )

    run_output = None
    async for chunk in agent.arun("Generate an image", stream=True, yield_run_output=True):
        if isinstance(chunk, RunOutput):
            run_output = chunk

    assert run_output is not None
    assert run_output.images is not None
    assert len(run_output.images) == 1
    assert run_output.images[0].url == "https://example.com/generated.png"


@pytest.mark.asyncio
async def test_store_media_false_async_streaming_with_stream_events():
    agent = Agent(
        model=MockModelWithImage(),
        store_media=False,
    )

    completed_event = None
    async for chunk in agent.arun("Generate an image", stream=True, stream_events=True):
        if isinstance(chunk, RunCompletedEvent):
            completed_event = chunk

    assert completed_event is not None
    assert completed_event.images is not None
    assert len(completed_event.images) == 1
    assert completed_event.images[0].url == "https://example.com/generated.png"
