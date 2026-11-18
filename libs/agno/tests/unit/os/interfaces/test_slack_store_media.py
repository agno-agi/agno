from typing import Any, AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.agent import RunEvent
from agno.agent.agent import Agent
from agno.media import Image
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os.interfaces.slack.executor import run_event

from .conftest import make_client, make_ctx, make_message_event_context

_UPLOAD = "agno.os.interfaces.slack.executor.upload_response_media_async"


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


# -- Non-streaming --


@pytest.mark.asyncio
@pytest.mark.parametrize("store_media", [False, True])
async def test_non_streaming_uploads_response_media(store_media):
    agent_mock = AsyncMock()
    agent_mock.id = "agent-1"
    agent_mock.name = "Test Agent"
    agent_mock._uses_native_hitl = False
    agent_mock.sandbox = None
    agent_mock.store_media = store_media
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK",
            content="Here is your image",
            reasoning_content=None,
            images=[Image(url="https://example.com/generated.png", id="img-1")],
            files=None,
            videos=None,
            audio=None,
        )
    )
    ctx = make_ctx(agent=agent_mock, streaming=False)
    with patch(_UPLOAD) as mock_upload:
        await run_event(make_message_event_context(ctx, text="generate an image"), make_client(), ctx)
    mock_upload.assert_called_once()
    passed_response = mock_upload.call_args[0][1]
    assert len(passed_response.images) == 1


@pytest.mark.asyncio
async def test_non_streaming_real_agent_store_media_false():
    agent = Agent(model=MockModelWithImage(), store_media=False)
    ctx = make_ctx(agent=agent, streaming=False)
    with patch(_UPLOAD) as mock_upload:
        await run_event(make_message_event_context(ctx, text="generate an image"), make_client(), ctx)
    mock_upload.assert_called_once()
    passed_response = mock_upload.call_args[0][1]
    assert passed_response.images is not None, "store_media=False should not strip images from caller response"
    assert len(passed_response.images) == 1
    assert passed_response.images[0].url == "https://example.com/generated.png"


# -- Streaming --


def _streaming_agent(chunks):
    async def _arun_stream(*args, **kwargs):
        for chunk in chunks:
            yield chunk

    agent = AsyncMock()
    agent.id = "agent-1"
    agent.name = "Test Agent"
    agent._uses_native_hitl = False
    agent.sandbox = None
    agent.arun = _arun_stream
    return agent


def _chunk(event: str, text: str, images=None):
    return Mock(event=event, content=text, images=images, videos=None, audio=None, files=None, tool=None)


@pytest.mark.asyncio
async def test_streaming_collects_media_from_completion():
    agent = _streaming_agent(
        [
            _chunk(RunEvent.run_content.value, "Here is "),
            _chunk(RunEvent.run_content.value, "your image"),
            _chunk(
                RunEvent.run_completed.value,
                "Here is your image",
                [Image(url="https://example.com/generated.png", id="img-1")],
            ),
        ]
    )
    ctx = make_ctx(agent=agent, streaming=True)
    with patch(_UPLOAD) as mock_upload:
        await run_event(make_message_event_context(ctx, text="generate an image"), make_client(), ctx)
    mock_upload.assert_called_once()
    state = mock_upload.call_args[0][1]
    assert len(state.images) == 1
    assert state.images[0].url == "https://example.com/generated.png"


@pytest.mark.asyncio
async def test_streaming_content_chunks_with_images_collected():
    agent = _streaming_agent(
        [
            _chunk(RunEvent.run_content.value, "Image 1", [Image(url="https://example.com/img1.png", id="img-1")]),
            _chunk(RunEvent.run_content.value, "Image 2", [Image(url="https://example.com/img2.png", id="img-2")]),
        ]
    )
    ctx = make_ctx(agent=agent, streaming=True)
    with patch(_UPLOAD) as mock_upload:
        await run_event(make_message_event_context(ctx, text="generate an image"), make_client(), ctx)
    mock_upload.assert_called_once()
    assert len(mock_upload.call_args[0][1].images) == 2


@pytest.mark.asyncio
async def test_streaming_real_agent_store_media_false():
    agent = Agent(model=MockModelWithImage(), store_media=False)
    ctx = make_ctx(agent=agent, streaming=True)
    with patch(_UPLOAD) as mock_upload:
        await run_event(make_message_event_context(ctx, text="generate an image"), make_client(), ctx)
    mock_upload.assert_called_once()
    state = mock_upload.call_args[0][1]
    # Real agent with store_media=False should still emit images in streaming chunks
    assert len(state.images) >= 1, "store_media=False should not prevent media in streaming chunks"
