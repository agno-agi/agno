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
    slack_sdk_web = types.ModuleType("slack_sdk.web")
    slack_sdk_web_async = types.ModuleType("slack_sdk.web.async_client")

    class SlackApiError(Exception):
        def __init__(self, message="error", response=None):
            super().__init__(message)
            self.response = response

    class WebClient:
        def __init__(self, token=None):
            self.token = token

    class AsyncWebClient:
        def __init__(self, token=None):
            self.token = token

    slack_sdk.WebClient = WebClient
    slack_sdk_errors.SlackApiError = SlackApiError
    slack_sdk_web_async.AsyncWebClient = AsyncWebClient
    sys.modules.setdefault("slack_sdk", slack_sdk)
    sys.modules.setdefault("slack_sdk.errors", slack_sdk_errors)
    sys.modules.setdefault("slack_sdk.web", slack_sdk_web)
    sys.modules.setdefault("slack_sdk.web.async_client", slack_sdk_web_async)


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


def _build_app(agent_mock: Mock, **kwargs) -> FastAPI:
    from agno.os.interfaces.slack.router import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(router, agent=agent_mock, **kwargs)
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


def test_explicit_token_passed_to_slack_tools():
    """When token is provided, SlackTools receives it instead of reading env."""
    agent_mock = _make_agent_mock()

    with (
        patch("agno.os.interfaces.slack.router.SlackTools") as mock_cls,
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
    ):
        mock_cls.return_value = _make_slack_mock()
        _build_app(agent_mock, token="xoxb-explicit-token")
        mock_cls.assert_called_once_with(token="xoxb-explicit-token", ssl=None)


def test_no_token_passes_none_to_slack_tools():
    """When no token is given, SlackTools receives None (falls back to env internally)."""
    agent_mock = _make_agent_mock()

    with (
        patch("agno.os.interfaces.slack.router.SlackTools") as mock_cls,
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch.dict("os.environ", {"SLACK_TOKEN": "env-token"}),
    ):
        mock_cls.return_value = _make_slack_mock()
        _build_app(agent_mock)
        mock_cls.assert_called_once_with(token=None, ssl=None)


def test_explicit_signing_secret_used_in_verification():
    """When signing_secret is provided, verify_slack_signature receives it."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()
    instance_secret = "my-instance-secret"

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True) as mock_verify,
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = _build_app(agent_mock, signing_secret=instance_secret)
        client = TestClient(app)
        body = {"type": "url_verification", "challenge": "test-challenge"}
        body_bytes = json.dumps(body).encode()
        timestamp = str(int(time.time()))
        client.post(
            "/events",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": "v0=fake",
            },
        )
        mock_verify.assert_called_once()
        _, kwargs = mock_verify.call_args
        assert kwargs.get("signing_secret") == instance_secret


def test_no_signing_secret_passes_none():
    """When no signing_secret is given, verify_slack_signature gets None (env fallback)."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True) as mock_verify,
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = {"type": "url_verification", "challenge": "test-challenge"}
        body_bytes = json.dumps(body).encode()
        timestamp = str(int(time.time()))
        client.post(
            "/events",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": "v0=fake",
            },
        )
        mock_verify.assert_called_once()
        _, kwargs = mock_verify.call_args
        assert kwargs.get("signing_secret") is None


def test_operation_id_uses_entity_name():
    """Operation ID should use entity name for uniqueness across instances."""
    from agno.os.interfaces.slack.router import attach_routes

    agent_a = _make_agent_mock()
    agent_a.name = "Research Agent"
    agent_b = _make_agent_mock()
    agent_b.name = "Analyst Agent"

    with (
        patch("agno.os.interfaces.slack.router.SlackTools"),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = FastAPI()
        router_a = APIRouter(prefix="/research")
        attach_routes(router_a, agent=agent_a)
        router_b = APIRouter(prefix="/analyst")
        attach_routes(router_b, agent=agent_b)
        # Both should mount without OpenAPI collision
        app.include_router(router_a)
        app.include_router(router_b)

        openapi = app.openapi()
        op_ids = [op.get("operationId") for path_ops in openapi["paths"].values() for op in path_ops.values()]
        assert "slack_events_research_agent" in op_ids
        assert "slack_events_analyst_agent" in op_ids
        assert len(op_ids) == len(set(op_ids)), "operation IDs must be unique"


def test_verify_slack_signature_uses_explicit_secret():
    """verify_slack_signature should use the explicit secret over the global."""
    from agno.os.interfaces.slack.security import verify_slack_signature

    body = b'{"test": true}'
    timestamp = str(int(time.time()))
    secret = "explicit-secret"

    sig_base = f"v0:{timestamp}:{body.decode()}"
    expected_sig = "v0=" + hmac.new(secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()

    assert verify_slack_signature(body, timestamp, expected_sig, signing_secret=secret)


def test_verify_slack_signature_env_fallback():
    """verify_slack_signature falls back to env when no explicit secret provided."""
    from agno.os.interfaces.slack import security as sec_mod

    body = b'{"test": true}'
    timestamp = str(int(time.time()))
    env_secret = "env-secret-value"

    sig_base = f"v0:{timestamp}:{body.decode()}"
    expected_sig = "v0=" + hmac.new(env_secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()

    original = sec_mod.SLACK_SIGNING_SECRET
    try:
        sec_mod.SLACK_SIGNING_SECRET = env_secret
        assert sec_mod.verify_slack_signature(body, timestamp, expected_sig)
    finally:
        sec_mod.SLACK_SIGNING_SECRET = original


async def _wait_for_agent_call(agent_mock: AsyncMock, timeout: float = 5.0):
    import asyncio

    elapsed = 0.0
    while not agent_mock.arun.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1


async def _wait_for_mock_call(mock_method, timeout: float = 5.0):
    import asyncio

    elapsed = 0.0
    while not mock_method.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1


@pytest.mark.asyncio
async def test_should_respond_app_mention():
    """app_mention events always trigger a response regardless of reply_to_mentions_only."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = _build_app(agent_mock, reply_to_mentions_only=True)
        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "<@U123> hello",
                "user": "U456",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        response = _make_signed_request(client, body)
        assert response.status_code == 200
        await _wait_for_agent_call(agent_mock)
        agent_mock.arun.assert_called_once()


@pytest.mark.asyncio
async def test_should_respond_dm():
    """DM messages always trigger a response regardless of reply_to_mentions_only."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = _build_app(agent_mock, reply_to_mentions_only=True)
        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "hello",
                "user": "U456",
                "channel": "D123",
                "ts": str(time.time()),
            },
        }
        response = _make_signed_request(client, body)
        assert response.status_code == 200
        await _wait_for_agent_call(agent_mock)
        agent_mock.arun.assert_called_once()


@pytest.mark.asyncio
async def test_channel_message_blocked_when_mentions_only():
    """Channel messages are blocked when reply_to_mentions_only=True."""
    import asyncio

    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = _build_app(agent_mock, reply_to_mentions_only=True)
        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "text": "hello",
                "user": "U456",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        response = _make_signed_request(client, body)
        assert response.status_code == 200
        await asyncio.sleep(0.5)
        agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_thread_reply_blocked_when_mentions_only():
    """Thread replies in channels are blocked when reply_to_mentions_only=True (Bug #4 fix)."""
    import asyncio

    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = _build_app(agent_mock, reply_to_mentions_only=True)
        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "text": "hello in thread",
                "user": "U456",
                "channel": "C123",
                "ts": "1234567890.000002",
                "thread_ts": "1234567890.000001",
            },
        }
        response = _make_signed_request(client, body)
        assert response.status_code == 200
        await asyncio.sleep(0.5)
        agent_mock.arun.assert_not_called()


def test_bot_subtype_blocked():
    """Events with bot_message subtype are blocked."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = _build_app(agent_mock, reply_to_mentions_only=False)
        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "channel_type": "im",
                "text": "bot says hi",
                "user": "U456",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        response = _make_signed_request(client, body)
        assert response.status_code == 200
        agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_file_share_subtype_not_blocked():
    """Events with file_share subtype should NOT be blocked (Bug #3 fix)."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()
    mock_slack.download_file_bytes = Mock(return_value=b"file-data")

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = _build_app(agent_mock, reply_to_mentions_only=False)
        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "subtype": "file_share",
                "channel_type": "im",
                "text": "check this file",
                "user": "U456",
                "channel": "C123",
                "ts": str(time.time()),
                "files": [{"id": "F1", "name": "doc.txt", "mimetype": "text/plain"}],
            },
        }
        response = _make_signed_request(client, body)
        assert response.status_code == 200
        await _wait_for_agent_call(agent_mock)
        agent_mock.arun.assert_called_once()


def test_signing_secret_empty_string_not_fallback():
    """signing_secret='' should NOT fall back to env SLACK_SIGNING_SECRET (Bug #7 fix)."""
    from agno.os.interfaces.slack import security as sec_mod

    body = b'{"test": true}'
    timestamp = str(int(time.time()))

    original = sec_mod.SLACK_SIGNING_SECRET
    try:
        sec_mod.SLACK_SIGNING_SECRET = "env-secret"
        with pytest.raises(Exception):
            sec_mod.verify_slack_signature(body, timestamp, "v0=fake", signing_secret="")
    finally:
        sec_mod.SLACK_SIGNING_SECRET = original


def test_retry_header_skips_processing():
    """X-Slack-Retry-Num header should cause early return without processing."""
    agent_mock = _make_agent_mock()
    mock_slack = _make_slack_mock()

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "retry message",
                "user": "U456",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        body_bytes = json.dumps(body).encode()
        timestamp = str(int(time.time()))
        sig_base = f"v0:{timestamp}:{body_bytes.decode()}"
        signature = "v0=" + hmac.new(SIGNING_SECRET.encode(), sig_base.encode(), hashlib.sha256).hexdigest()
        response = client.post(
            "/events",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
                "X-Slack-Retry-Num": "1",
                "X-Slack-Retry-Reason": "http_timeout",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_streaming_dispatches_stream_handler():
    """streaming=True should route events through the streaming handler."""
    agent_mock = AsyncMock()

    async def _arun_stream(*args, **kwargs):
        return
        yield  # noqa: RET504 — makes this an async generator

    agent_mock.arun = _arun_stream
    agent_mock.name = "Test Agent"

    mock_slack = _make_slack_mock()
    mock_slack.token = "xoxb-test"

    mock_stream = AsyncMock()
    mock_stream.append = AsyncMock()
    mock_stream.stop = AsyncMock()

    mock_async_client = AsyncMock()
    mock_async_client.assistant_threads_setStatus = AsyncMock()
    mock_async_client.chat_stream = Mock(return_value=mock_stream)

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_async_client),
    ):
        app = _build_app(agent_mock, streaming=True, reply_to_mentions_only=False)
        client = TestClient(app)
        thread_ts = str(time.time())
        body = {
            "type": "event_callback",
            "team_id": "T123",
            "authorizations": [{"user_id": "B123"}],
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "hello stream",
                "user": "U456",
                "channel": "C123",
                "ts": str(float(thread_ts) + 1),
                "thread_ts": thread_ts,
            },
        }
        response = _make_signed_request(client, body)
        assert response.status_code == 200
        import asyncio

        await asyncio.sleep(0.5)
        status_calls = mock_async_client.assistant_threads_setStatus.call_args_list
        assert len(status_calls) >= 1
        assert status_calls[0].kwargs.get("status") == "Thinking..."


@pytest.mark.asyncio
async def test_recipient_user_id_is_human_user():
    """recipient_user_id should be the human user, not the bot (Bug #5 fix).

    chat_stream() is called with recipient IDs. We verify the kwargs
    contain the human user ID from event["user"], not the bot ID.
    """
    import asyncio

    agent_mock = AsyncMock()

    async def _arun_stream(*args, **kwargs):
        from agno.agent import RunEvent

        yield Mock(event=RunEvent.run_content.value, content="Hello!", tool=None)

    agent_mock.arun = _arun_stream
    agent_mock.name = "Test Agent"

    mock_slack = _make_slack_mock()
    mock_slack.token = "xoxb-test"

    mock_stream = AsyncMock()
    mock_stream.append = AsyncMock()
    mock_stream.stop = AsyncMock()

    mock_async_client = AsyncMock()
    mock_async_client.assistant_threads_setStatus = AsyncMock()
    mock_async_client.assistant_threads_setTitle = AsyncMock()
    mock_async_client.chat_stream = AsyncMock(return_value=mock_stream)

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_async_client),
    ):
        app = _build_app(agent_mock, streaming=True, reply_to_mentions_only=False)
        client = TestClient(app)
        thread_ts = str(time.time())
        body = {
            "type": "event_callback",
            "team_id": "T123",
            "authorizations": [{"user_id": "B_BOT_ID"}],
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "hello",
                "user": "U_HUMAN_ID",
                "channel": "C123",
                "ts": str(float(thread_ts) + 1),
                "thread_ts": thread_ts,
            },
        }
        response = _make_signed_request(client, body)
        assert response.status_code == 200

        for _ in range(40):
            if mock_stream.stop.called:
                break
            await asyncio.sleep(0.1)

        mock_async_client.chat_stream.assert_called_once()
        call_kwargs = mock_async_client.chat_stream.call_args.kwargs
        assert call_kwargs.get("recipient_team_id") == "T123"
        assert call_kwargs.get("recipient_user_id") == "U_HUMAN_ID"


@pytest.mark.asyncio
async def test_team_events_handled_same_as_agent():
    """Agent and team event strings produce the same behavior via _normalize_event."""
    from agno.agent import RunEvent
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState
    from agno.run.team import TeamRunEvent

    # Agent content event
    state_a = StreamState()
    stream_a = AsyncMock()
    stream_a.append = AsyncMock()
    await _process_event(
        RunEvent.run_content.value, Mock(event=RunEvent.run_content.value, content="hello"), state_a, stream_a
    )
    assert state_a.text_buffer == "hello"

    # Team content event — same behavior
    state_t = StreamState()
    stream_t = AsyncMock()
    stream_t.append = AsyncMock()
    await _process_event(
        TeamRunEvent.run_content.value, Mock(event=TeamRunEvent.run_content.value, content="hello"), state_t, stream_t
    )
    assert state_t.text_buffer == "hello"


@pytest.mark.asyncio
async def test_workflow_suppresses_nested_agent_events():
    """In workflow mode, nested agent events (tools, reasoning, content, lifecycle) are suppressed."""
    from agno.agent import RunEvent
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState
    from agno.run.team import TeamRunEvent

    suppressed_events = [
        RunEvent.run_content.value,
        TeamRunEvent.run_content.value,
        RunEvent.reasoning_started.value,
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
        RunEvent.memory_update_started.value,
        RunEvent.run_completed.value,
        RunEvent.run_error.value,
        RunEvent.run_cancelled.value,
    ]
    for ev in suppressed_events:
        state = StreamState(entity_type="workflow")
        stream = AsyncMock()
        stream.append = AsyncMock()
        chunk = Mock(event=ev, content="should be suppressed", tool=None)
        result = await _process_event(ev, chunk, state, stream)
        assert result is False, f"{ev} should not break in workflow mode"
        assert state.text_buffer == "", f"{ev} should not buffer content in workflow mode"
        stream.append.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_structural_events_not_suppressed():
    """Workflow structural events (steps, loops, parallel) still work in workflow mode."""
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState
    from agno.run.workflow import WorkflowRunEvent

    state = StreamState(entity_type="workflow")
    stream = AsyncMock()
    stream.append = AsyncMock()

    chunk = Mock(step_name="research", step_id="s1")
    await _process_event(WorkflowRunEvent.step_started.value, chunk, state, stream)
    assert "wf_step_s1" in state.task_cards
    assert state.task_cards["wf_step_s1"].status == "in_progress"


@pytest.mark.asyncio
async def test_workflow_content_suppressed_in_workflow_mode():
    """Content events are suppressed in workflow mode — no text buffered."""
    from agno.agent import RunEvent
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState

    state = StreamState(entity_type="workflow")
    stream = AsyncMock()
    stream.append = AsyncMock()

    chunk = Mock(event=RunEvent.run_content.value, content="intermediate text")
    result = await _process_event(RunEvent.run_content.value, chunk, state, stream)
    assert result is False
    assert state.text_buffer == ""


@pytest.mark.asyncio
async def test_workflow_step_output_captures():
    """StepOutput in workflow mode captures content for final response."""
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState
    from agno.run.workflow import WorkflowRunEvent

    state = StreamState(entity_type="workflow")
    stream = AsyncMock()
    stream.append = AsyncMock()

    # First step output
    chunk1 = Mock(event=WorkflowRunEvent.step_output.value, content="step 1 output")
    await _process_event(WorkflowRunEvent.step_output.value, chunk1, state, stream)
    assert state.workflow_final_content == "step 1 output"

    # Second step output overwrites (last wins)
    chunk2 = Mock(event=WorkflowRunEvent.step_output.value, content="step 2 output")
    await _process_event(WorkflowRunEvent.step_output.value, chunk2, state, stream)
    assert state.workflow_final_content == "step 2 output"
    assert state.text_buffer == ""


@pytest.mark.asyncio
async def test_step_output_buffers_text_in_agent_mode():
    """StepOutput in non-workflow mode buffers content as regular text."""
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState
    from agno.run.workflow import WorkflowRunEvent

    state = StreamState(entity_type="agent")
    stream = AsyncMock()
    stream.append = AsyncMock()

    chunk = Mock(event=WorkflowRunEvent.step_output.value, content="step text")
    await _process_event(WorkflowRunEvent.step_output.value, chunk, state, stream)
    assert state.text_buffer == "step text"
    assert state.workflow_final_content == ""


@pytest.mark.asyncio
async def test_workflow_completed_emits_final_content():
    """WorkflowCompleted puts content into text_buffer."""
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState
    from agno.run.workflow import WorkflowRunEvent

    state = StreamState(entity_name="News Reporter")
    stream = AsyncMock()
    stream.append = AsyncMock()

    chunk = Mock(
        event=WorkflowRunEvent.workflow_completed.value,
        content="Final article text",
        run_id="abc123",
        workflow_name="News Reporter",
    )
    result = await _process_event(WorkflowRunEvent.workflow_completed.value, chunk, state, stream)
    assert result is False
    assert "Final article text" in state.text_buffer


@pytest.mark.asyncio
async def test_workflow_completed_fallback_to_captured():
    """WorkflowCompleted falls back to workflow_final_content when chunk.content is None."""
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState
    from agno.run.workflow import WorkflowRunEvent

    state = StreamState()
    state.workflow_final_content = "captured from step output"
    stream = AsyncMock()
    stream.append = AsyncMock()

    chunk = Mock(
        event=WorkflowRunEvent.workflow_completed.value,
        content=None,
        run_id="abc123",
        workflow_name="Test",
    )
    await _process_event(WorkflowRunEvent.workflow_completed.value, chunk, state, stream)
    assert "captured from step output" in state.text_buffer


@pytest.mark.asyncio
async def test_workflow_suppression_does_not_touch_cards():
    """Suppressed events in workflow mode do not complete or modify existing task cards."""
    from agno.agent import RunEvent
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState

    state = StreamState(entity_type="workflow")
    state.track_task("wf_step_1", "Research")
    stream = AsyncMock()
    stream.append = AsyncMock()

    # A suppressed RunCompleted event should not touch the card
    chunk = Mock(event=RunEvent.run_completed.value, content=None, tool=None)
    result = await _process_event(RunEvent.run_completed.value, chunk, state, stream)
    assert result is False
    assert state.task_cards["wf_step_1"].status == "in_progress"
    stream.append.assert_not_called()


@pytest.mark.asyncio
async def test_structural_events_emit_cards():
    """Structural workflow events (parallel, condition, router, steps) create and complete task cards."""
    from agno.os.interfaces.slack.router import _process_event
    from agno.os.interfaces.slack.state import StreamState
    from agno.run.workflow import WorkflowRunEvent

    handler_pairs = [
        (
            WorkflowRunEvent.parallel_execution_started,
            WorkflowRunEvent.parallel_execution_completed,
            "wf_parallel_",
            "p1",
        ),
        (
            WorkflowRunEvent.condition_execution_started,
            WorkflowRunEvent.condition_execution_completed,
            "wf_cond_",
            "c1",
        ),
        (WorkflowRunEvent.router_execution_started, WorkflowRunEvent.router_execution_completed, "wf_router_", "r1"),
        (WorkflowRunEvent.steps_execution_started, WorkflowRunEvent.steps_execution_completed, "wf_steps_", "s1"),
    ]
    for started_event, completed_event, key_prefix, sid in handler_pairs:
        state = StreamState()
        stream = AsyncMock()
        stream.append = AsyncMock()
        expected_key = f"{key_prefix}{sid}"

        chunk_start = Mock(step_name="test_step", step_id=sid)
        await _process_event(started_event.value, chunk_start, state, stream)
        assert expected_key in state.task_cards, f"{started_event.value} did not track card"
        assert state.task_cards[expected_key].status == "in_progress"

        chunk_end = Mock(step_name="test_step", step_id=sid)
        await _process_event(completed_event.value, chunk_end, state, stream)
        assert state.task_cards[expected_key].status == "complete", f"{completed_event.value} did not complete card"
