import json
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI

from .conftest import build_app, make_agent_mock, make_signed_request, make_slack_mock, slack_event_with_files


async def _wait_for_agent_call(agent_mock: AsyncMock, timeout: float = 5.0):
    import asyncio

    elapsed = 0.0
    while not agent_mock.arun.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1


@pytest.mark.asyncio
async def test_mixed_files_categorized_correctly():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    mock_slack.download_file_bytes = Mock(side_effect=[b"csv-data", b"img-data", b"zip-data"])

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = build_app(agent_mock)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = slack_event_with_files(
            [
                {"id": "F5", "name": "data.csv", "mimetype": "text/csv"},
                {"id": "F6", "name": "pic.jpg", "mimetype": "image/jpeg"},
                {"id": "F7", "name": "bundle.zip", "mimetype": "application/zip"},
            ]
        )
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        await _wait_for_agent_call(agent_mock)

        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        images = call_kwargs.kwargs.get("images") or call_kwargs[1].get("images")
        assert len(files) == 2
        assert files[0].mime_type == "text/csv"
        assert files[1].mime_type is None
        assert len(images) == 1


@pytest.mark.asyncio
async def test_non_whitelisted_mime_type_passes_none():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    mock_slack.download_file_bytes = Mock(return_value=b"zipdata")

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = build_app(agent_mock)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = slack_event_with_files([{"id": "F1", "name": "archive.zip", "mimetype": "application/zip"}])
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        await _wait_for_agent_call(agent_mock)

        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        assert files[0].mime_type is None
        assert files[0].content == b"zipdata"


def test_explicit_token_passed_to_slack_tools():
    agent_mock = make_agent_mock()
    with (
        patch("agno.os.interfaces.slack.router.SlackTools") as mock_cls,
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
    ):
        mock_cls.return_value = make_slack_mock()
        build_app(agent_mock, token="xoxb-explicit-token")
        mock_cls.assert_called_once_with(token="xoxb-explicit-token", ssl=None, max_file_size=1_073_741_824)


def test_explicit_signing_secret_used():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True) as mock_verify,
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = build_app(agent_mock, signing_secret="my-secret")
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {"type": "url_verification", "challenge": "test"}
        body_bytes = json.dumps(body).encode()
        ts = str(int(time.time()))
        client.post(
            "/events",
            content=body_bytes,
            headers={"Content-Type": "application/json", "X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=f"},
        )
        _, kwargs = mock_verify.call_args
        assert kwargs.get("signing_secret") == "my-secret"


def test_operation_id_unique_across_instances():
    from agno.os.interfaces.slack.router import attach_routes

    agent_a = make_agent_mock()
    agent_a.name = "Research Agent"
    agent_b = make_agent_mock()
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
        app.include_router(router_a)
        app.include_router(router_b)

        openapi = app.openapi()
        op_ids = [op.get("operationId") for path_ops in openapi["paths"].values() for op in path_ops.values()]
        assert len(op_ids) == len(set(op_ids))


def test_bot_subtype_blocked():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "channel_type": "im",
                "text": "bot loop",
                "user": "U456",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_file_share_subtype_not_blocked():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    mock_slack.download_file_bytes = Mock(return_value=b"file-data")
    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "subtype": "file_share",
                "channel_type": "im",
                "text": "check this",
                "user": "U456",
                "channel": "C123",
                "ts": str(time.time()),
                "files": [{"id": "F1", "name": "doc.txt", "mimetype": "text/plain"}],
            },
        }
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        await _wait_for_agent_call(agent_mock)
        agent_mock.arun.assert_called_once()


@pytest.mark.asyncio
async def test_thread_reply_blocked_when_mentions_only():
    import asyncio

    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=True)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "text": "reply in thread",
                "user": "U456",
                "channel": "C123",
                "ts": "1234567890.000002",
                "thread_ts": "1234567890.000001",
            },
        }
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        await asyncio.sleep(0.5)
        agent_mock.arun.assert_not_called()


def test_retry_header_skips_processing():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
    ):
        app = build_app(agent_mock)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "retry",
                "user": "U456",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        body_bytes = json.dumps(body).encode()
        ts = str(int(time.time()))
        import hashlib
        import hmac

        sig_base = f"v0:{ts}:{body_bytes.decode()}"
        sig = "v0=" + hmac.new(b"test-secret", sig_base.encode(), hashlib.sha256).hexdigest()
        resp = client.post(
            "/events",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "X-Slack-Retry-Num": "1",
                "X-Slack-Retry-Reason": "http_timeout",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        agent_mock.arun.assert_not_called()
