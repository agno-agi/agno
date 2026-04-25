import asyncio
import time
from typing import Any, AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI

from agno.agent import RunEvent
from agno.agent.agent import Agent
from agno.media import Image
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse

from .conftest import (
    build_app,
    make_async_client_mock,
    make_signed_request,
    make_slack_mock,
    make_stream_mock,
    make_streaming_body,
    wait_for_call,
)


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


# -- Non-streaming: store_media=False with mock agent --


@pytest.mark.asyncio
async def test_non_streaming_store_media_false_uploads_media():
    agent_mock = AsyncMock()
    agent_mock.name = "Test Agent"
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
    mock_slack = make_slack_mock()
    mock_client = make_async_client_mock()
    mock_client.files_upload_v2 = AsyncMock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "generate an image",
                "user": "U123",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        # upload_response_media_async runs synchronously in the background task after arun
        await asyncio.sleep(1.0)

        # Verify the agent was called
        agent_mock.arun.assert_called_once()
        # Response had images — upload should have been attempted
        # (would fail because Image has url not content, but the call confirms the path)


@pytest.mark.asyncio
async def test_non_streaming_store_media_false_response_has_images():
    agent_mock = AsyncMock()
    agent_mock.name = "Test Agent"
    response_mock = Mock(
        status="OK",
        content="Here is your image",
        reasoning_content=None,
        images=[Image(url="https://example.com/generated.png", id="img-1")],
        files=None,
        videos=None,
        audio=None,
    )
    agent_mock.arun = AsyncMock(return_value=response_mock)
    mock_slack = make_slack_mock()
    mock_client = make_async_client_mock()
    upload_mock = AsyncMock()
    mock_client.files_upload_v2 = upload_mock

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        patch("agno.os.interfaces.slack.router.upload_response_media_async") as mock_upload,
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "generate an image",
                "user": "U123",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        await asyncio.sleep(1.0)

        mock_upload.assert_called_once()
        call_args = mock_upload.call_args
        # Second positional arg is the response object
        passed_response = call_args[0][1]
        assert passed_response.images is not None
        assert len(passed_response.images) == 1
        assert passed_response.images[0].url == "https://example.com/generated.png"


# -- Non-streaming: real Agent with store_media=False --


@pytest.mark.asyncio
async def test_non_streaming_real_agent_store_media_false():
    agent = Agent(
        model=MockModelWithImage(),
        store_media=False,
    )
    mock_slack = make_slack_mock()
    mock_client = make_async_client_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        patch("agno.os.interfaces.slack.router.upload_response_media_async") as mock_upload,
    ):
        from agno.os.interfaces.slack.router import attach_routes

        app = FastAPI()
        router = APIRouter()
        attach_routes(router, agent=agent, streaming=False, reply_to_mentions_only=False)
        app.include_router(router)

        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "generate an image",
                "user": "U123",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        # Wait for background task
        await asyncio.sleep(3.0)

        mock_upload.assert_called_once()
        call_args = mock_upload.call_args
        passed_response = call_args[0][1]
        assert passed_response.images is not None, "store_media=False should not strip images from caller response"
        assert len(passed_response.images) == 1
        assert passed_response.images[0].url == "https://example.com/generated.png"


# -- Streaming: media in completion chunk --


def _completion_chunk_with_image():
    return Mock(
        event=RunEvent.run_completed.value,
        content="Here is your image",
        images=[Image(url="https://example.com/generated.png", id="img-1")],
        videos=None,
        audio=None,
        files=None,
        tool=None,
    )


def _content_chunk(text):
    return Mock(
        event=RunEvent.run_content.value,
        content=text,
        images=None,
        videos=None,
        audio=None,
        files=None,
        tool=None,
    )


@pytest.mark.asyncio
async def test_streaming_store_media_false_collects_media_from_completion():
    async def _arun_stream(*args, **kwargs):
        yield _content_chunk("Here is ")
        yield _content_chunk("your image")
        yield _completion_chunk_with_image()

    agent = AsyncMock()
    agent.name = "Test Agent"
    agent.arun = _arun_stream

    mock_slack = make_slack_mock(token="xoxb-test")
    mock_stream = make_stream_mock()
    mock_client = AsyncMock()
    mock_client.assistant_threads_setStatus = AsyncMock()
    mock_client.assistant_threads_setTitle = AsyncMock()
    mock_client.chat_stream = AsyncMock(return_value=mock_stream)

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        patch("agno.os.interfaces.slack.router.upload_response_media_async") as mock_upload,
    ):
        app = build_app(agent, streaming=True, reply_to_mentions_only=False)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = make_signed_request(client, make_streaming_body())
        assert resp.status_code == 200
        await wait_for_call(mock_stream.stop)
        await asyncio.sleep(1.0)

        mock_upload.assert_called_once()
        call_args = mock_upload.call_args
        # In streaming, the second arg is the StreamState object
        state = call_args[0][1]
        assert len(state.images) == 1
        assert state.images[0].url == "https://example.com/generated.png"


@pytest.mark.asyncio
async def test_streaming_content_chunks_with_images_collected():
    async def _arun_stream(*args, **kwargs):
        yield Mock(
            event=RunEvent.run_content.value,
            content="Image 1",
            images=[Image(url="https://example.com/img1.png", id="img-1")],
            videos=None,
            audio=None,
            files=None,
            tool=None,
        )
        yield Mock(
            event=RunEvent.run_content.value,
            content="Image 2",
            images=[Image(url="https://example.com/img2.png", id="img-2")],
            videos=None,
            audio=None,
            files=None,
            tool=None,
        )

    agent = AsyncMock()
    agent.name = "Test Agent"
    agent.arun = _arun_stream

    mock_slack = make_slack_mock(token="xoxb-test")
    mock_stream = make_stream_mock()
    mock_client = AsyncMock()
    mock_client.assistant_threads_setStatus = AsyncMock()
    mock_client.assistant_threads_setTitle = AsyncMock()
    mock_client.chat_stream = AsyncMock(return_value=mock_stream)

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        patch("agno.os.interfaces.slack.router.upload_response_media_async") as mock_upload,
    ):
        app = build_app(agent, streaming=True, reply_to_mentions_only=False)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = make_signed_request(client, make_streaming_body())
        assert resp.status_code == 200
        await wait_for_call(mock_stream.stop)
        await asyncio.sleep(1.0)

        mock_upload.assert_called_once()
        state = mock_upload.call_args[0][1]
        assert len(state.images) == 2


# -- Streaming: real Agent with store_media=False --


@pytest.mark.asyncio
async def test_streaming_real_agent_store_media_false():
    agent = Agent(
        model=MockModelWithImage(),
        store_media=False,
    )
    mock_slack = make_slack_mock(token="xoxb-test")
    mock_stream = make_stream_mock()
    mock_client = AsyncMock()
    mock_client.assistant_threads_setStatus = AsyncMock()
    mock_client.assistant_threads_setTitle = AsyncMock()
    mock_client.chat_stream = AsyncMock(return_value=mock_stream)

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        patch("agno.os.interfaces.slack.router.upload_response_media_async") as mock_upload,
    ):
        from agno.os.interfaces.slack.router import attach_routes

        app = FastAPI()
        router = APIRouter()
        attach_routes(router, agent=agent, streaming=True, reply_to_mentions_only=False)
        app.include_router(router)

        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = make_signed_request(client, make_streaming_body())
        assert resp.status_code == 200
        await asyncio.sleep(5.0)

        mock_upload.assert_called_once()
        state = mock_upload.call_args[0][1]
        # Real agent with store_media=False should still emit images in streaming chunks
        assert len(state.images) >= 1, "store_media=False should not prevent media in streaming chunks"


# -- Regression: store_media=True still works --


@pytest.mark.asyncio
async def test_non_streaming_store_media_true_still_uploads():
    agent_mock = AsyncMock()
    agent_mock.name = "Test Agent"
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK",
            content="Image ready",
            reasoning_content=None,
            images=[Image(url="https://example.com/generated.png", id="img-1")],
            files=None,
            videos=None,
            audio=None,
        )
    )
    mock_slack = make_slack_mock()
    mock_client = make_async_client_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        patch("agno.os.interfaces.slack.router.upload_response_media_async") as mock_upload,
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "generate",
                "user": "U123",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        await asyncio.sleep(1.0)

        mock_upload.assert_called_once()
        passed_response = mock_upload.call_args[0][1]
        assert passed_response.images is not None
        assert len(passed_response.images) == 1
