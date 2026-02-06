import hashlib
import hmac
import json
import sys
import time
import types
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


def _install_fake_slack_sdk():
    slack_sdk = types.ModuleType("slack_sdk")
    slack_sdk_errors = types.ModuleType("slack_sdk.errors")

    class SlackApiError(Exception):
        def __init__(self, message="error", response=None):
            super().__init__(message)
            self.response = response

    class WebClient:
        def __init__(self, token=None):
            self.token = token

    slack_sdk.WebClient = WebClient
    slack_sdk_errors.SlackApiError = SlackApiError
    sys.modules.setdefault("slack_sdk", slack_sdk)
    sys.modules.setdefault("slack_sdk.errors", slack_sdk_errors)


_install_fake_slack_sdk()

SIGNING_SECRET = "test-secret"


def _make_signed_request(client: TestClient, body: dict):
    body_bytes = json.dumps(body).encode()
    timestamp = str(int(time.time()))
    sig_base = f"v0:{timestamp}:{body_bytes.decode()}"
    signature = "v0=" + hmac.new(SIGNING_SECRET.encode(), sig_base.encode(), hashlib.sha256).hexdigest()
    return client.post(
        "/events",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        },
    )


def _build_app(agent_mock: Mock) -> FastAPI:
    from agno.os.interfaces.slack.router import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(router, agent=agent_mock)
    app.include_router(router)
    return app


def _slack_event_with_files(files: list, event_type: str = "message") -> dict:
    return {
        "type": "event_callback",
        "event": {
            "type": event_type,
            "channel_type": "im",
            "text": "check this file",
            "user": "U123",
            "channel": "C123",
            "ts": str(time.time()),
            "files": files,
        },
    }


def _make_agent_mock():
    agent_mock = AsyncMock()
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK", content="done", reasoning_content=None, images=None, files=None, videos=None, audio=None
        )
    )
    return agent_mock


def _make_slack_mock(**kwargs):
    mock_slack = Mock()
    mock_slack.send_message = Mock()
    mock_slack.upload_file = Mock()
    for k, v in kwargs.items():
        setattr(mock_slack, k, v)
    return mock_slack


@pytest.mark.asyncio
async def test_non_whitelisted_mime_type_creates_file_with_none():
    """Files with non-whitelisted MIME types should still be created (with mime_type=None)."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()
    mock_slack.download_file_bytes.return_value = b"zipdata"

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _slack_event_with_files(
            [
                {"id": "F1", "name": "archive.zip", "mimetype": "application/zip"},
            ]
        )
        response = _make_signed_request(client, body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        assert files is not None, "Files should not be None — file was silently dropped"
        assert len(files) == 1
        assert files[0].mime_type is None
        assert files[0].filename == "archive.zip"
        assert files[0].content == b"zipdata"


@pytest.mark.asyncio
async def test_whitelisted_mime_type_preserved():
    """Files with whitelisted MIME types should keep their mime_type."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()
    mock_slack.download_file_bytes.return_value = b"hello world"

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _slack_event_with_files(
            [
                {"id": "F2", "name": "notes.txt", "mimetype": "text/plain"},
            ]
        )
        response = _make_signed_request(client, body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        assert files is not None
        assert len(files) == 1
        assert files[0].mime_type == "text/plain"
        assert files[0].filename == "notes.txt"


@pytest.mark.asyncio
async def test_image_files_routed_to_images_list():
    """Image files should go to the images list, not files."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()
    mock_slack.download_file_bytes.return_value = b"\x89PNG"

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _slack_event_with_files(
            [
                {"id": "F3", "name": "photo.png", "mimetype": "image/png"},
            ]
        )
        response = _make_signed_request(client, body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        images = call_kwargs.kwargs.get("images") or call_kwargs[1].get("images")
        assert files is None
        assert images is not None
        assert len(images) == 1
        assert images[0].content == b"\x89PNG"


@pytest.mark.asyncio
async def test_octet_stream_default_not_dropped():
    """application/octet-stream (Slack's default) should not cause file to be dropped."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()
    mock_slack.download_file_bytes.return_value = b"binarydata"

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _slack_event_with_files(
            [
                {"id": "F4", "name": "data.bin", "mimetype": "application/octet-stream"},
            ]
        )
        response = _make_signed_request(client, body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        assert files is not None, "application/octet-stream file was silently dropped"
        assert len(files) == 1
        assert files[0].mime_type is None
        assert files[0].content == b"binarydata"


@pytest.mark.asyncio
async def test_mixed_files_and_images():
    """Multiple files of different types should be categorized correctly."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()
    mock_slack.download_file_bytes.side_effect = [b"csv-data", b"img-data", b"zip-data"]

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _slack_event_with_files(
            [
                {"id": "F5", "name": "data.csv", "mimetype": "text/csv"},
                {"id": "F6", "name": "pic.jpg", "mimetype": "image/jpeg"},
                {"id": "F7", "name": "bundle.zip", "mimetype": "application/zip"},
            ]
        )
        response = _make_signed_request(client, body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        images = call_kwargs.kwargs.get("images") or call_kwargs[1].get("images")

        assert files is not None
        assert len(files) == 2
        assert files[0].filename == "data.csv"
        assert files[0].mime_type == "text/csv"
        assert files[1].filename == "bundle.zip"
        assert files[1].mime_type is None

        assert images is not None
        assert len(images) == 1


@pytest.mark.asyncio
async def test_no_files_in_event():
    """Events without files should pass files=None to agent."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "hello",
                "user": "U123",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        response = _make_signed_request(client, body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        images = call_kwargs.kwargs.get("images") or call_kwargs[1].get("images")
        assert files is None
        assert images is None


async def _wait_for_agent_call(agent_mock: AsyncMock, timeout: float = 5.0):
    import asyncio

    elapsed = 0.0
    while not agent_mock.arun.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1
