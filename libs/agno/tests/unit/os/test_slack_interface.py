import asyncio
import hashlib
import hmac
import json
import sys
import time
import types
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _install_fake_slack_sdk():
    # Stub slack_sdk so tests run without the dependency
    slack_sdk = types.ModuleType("slack_sdk")
    slack_sdk_errors = types.ModuleType("slack_sdk.errors")

    class SlackApiError(Exception):
        def __init__(self, message="Slack API error", response=None):
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


from agno.os.interfaces.slack import security as slack_security  # noqa: E402
from agno.os.interfaces.slack.router import attach_routes  # noqa: E402


def _compute_slack_signature(body: bytes, timestamp: str, signing_secret: str) -> str:
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    return (
        "v0="
        + hmac.new(
            signing_secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )


def test_verify_slack_signature_valid(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(slack_security, "SLACK_SIGNING_SECRET", secret)

    body = b'{"type":"url_verification","challenge":"abc"}'
    timestamp = str(int(time.time()))
    sig = _compute_slack_signature(body=body, timestamp=timestamp, signing_secret=secret)

    assert slack_security.verify_slack_signature(body=body, timestamp=timestamp, slack_signature=sig) is True


def test_verify_slack_signature_invalid(monkeypatch):
    monkeypatch.setattr(slack_security, "SLACK_SIGNING_SECRET", "test-secret")
    body = b'{"type":"url_verification","challenge":"abc"}'
    timestamp = str(int(time.time()))
    assert slack_security.verify_slack_signature(body=body, timestamp=timestamp, slack_signature="v0=bad") is False


def test_verify_slack_signature_stale_timestamp(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(slack_security, "SLACK_SIGNING_SECRET", secret)

    body = b'{"type":"url_verification","challenge":"abc"}'
    old_timestamp = str(int(time.time()) - 600)  # 10 minutes ago
    sig = _compute_slack_signature(body=body, timestamp=old_timestamp, signing_secret=secret)
    assert slack_security.verify_slack_signature(body=body, timestamp=old_timestamp, slack_signature=sig) is False


def test_verify_slack_signature_missing_secret(monkeypatch):
    monkeypatch.setattr(slack_security, "SLACK_SIGNING_SECRET", None)
    with pytest.raises(HTTPException) as e:
        slack_security.verify_slack_signature(body=b"{}", timestamp=str(int(time.time())), slack_signature="v0=bad")
    assert e.value.status_code == 500
    assert "SLACK_SIGNING_SECRET" in e.value.detail


@dataclass
class _FakeFile:
    content: bytes
    filename: str


@dataclass
class _FakeImage:
    content: bytes
    filename: str


@dataclass
class _FakeRunResponse:
    status: str
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    files: Optional[List[_FakeFile]] = None
    images: Optional[List[_FakeImage]] = None
    videos: Optional[List[Any]] = None
    audio: Optional[List[Any]] = None


class _FakeAgent:
    def __init__(self, response: _FakeRunResponse):
        self._response = response
        self.calls: List[Tuple[str, Optional[str], Optional[str]]] = []
        self.received_files: List[Any] = []
        self.received_images: List[Any] = []

    async def arun(
        self,
        message: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        files: Optional[List[Any]] = None,
        images: Optional[List[Any]] = None,
    ):
        self.calls.append((message, user_id, session_id))
        if files:
            self.received_files.extend(files)
        if images:
            self.received_images.extend(images)
        return self._response


def _make_app(
    *,
    agent: Optional[_FakeAgent] = None,
    reply_to_mentions_only: bool = True,
):
    app = FastAPI()
    from fastapi import APIRouter

    router = APIRouter(prefix="/slack", tags=["Slack"])
    router = attach_routes(router=router, agent=agent, reply_to_mentions_only=reply_to_mentions_only)
    app.include_router(router)
    return app


def test_slack_url_verification_happy_path(monkeypatch):
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: True)
    app = _make_app(agent=_FakeAgent(_FakeRunResponse(status="SUCCESS", content="ok")))
    client = TestClient(app)

    response = client.post(
        "/slack/events",
        json={"type": "url_verification", "challenge": "abc"},
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=ok"},
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "abc"}


def test_slack_missing_headers_returns_400():
    app = _make_app(agent=_FakeAgent(_FakeRunResponse(status="SUCCESS", content="ok")))
    client = TestClient(app)
    response = client.post("/slack/events", json={"type": "url_verification", "challenge": "abc"})
    assert response.status_code == 400
    assert "Missing Slack headers" in response.text


def test_slack_invalid_signature_returns_403(monkeypatch):
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: False)
    app = _make_app(agent=_FakeAgent(_FakeRunResponse(status="SUCCESS", content="ok")))
    client = TestClient(app)
    response = client.post(
        "/slack/events",
        json={"type": "url_verification", "challenge": "abc"},
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=bad"},
    )
    assert response.status_code == 403
    assert "Invalid signature" in response.text


def test_slack_bot_event_is_ignored(monkeypatch):
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: True)

    tasks: List[Tuple[Any, tuple, dict]] = []

    def _capture_task(self, func, *args, **kwargs):
        tasks.append((func, args, kwargs))

    monkeypatch.setattr("agno.os.interfaces.slack.router.BackgroundTasks.add_task", _capture_task)

    app = _make_app(agent=_FakeAgent(_FakeRunResponse(status="SUCCESS", content="ok")))
    client = TestClient(app)
    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event": {"type": "message", "channel_type": "im", "text": "hi", "bot_id": "B123", "ts": "1.0"},
        },
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=ok"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert tasks == []


def test_slack_dm_message_triggers_reply(monkeypatch):
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: True)

    tasks: List[Tuple[Any, tuple, dict]] = []
    sent: List[Dict[str, Any]] = []

    def _capture_task(self, func, *args, **kwargs):
        tasks.append((func, args, kwargs))

    class _FakeSlackTools:
        def __init__(self):
            pass

        def send_message(self, channel: str, text: str, thread_ts: str = None) -> str:
            sent.append({"channel": channel, "text": text, "thread_ts": thread_ts})
            return json.dumps({"ok": True})

        def download_file_bytes(self, file_id: str) -> bytes:
            return b"test file content"

    monkeypatch.setattr("agno.os.interfaces.slack.router.BackgroundTasks.add_task", _capture_task)
    monkeypatch.setattr("agno.os.interfaces.slack.router.SlackTools", _FakeSlackTools)

    agent = _FakeAgent(_FakeRunResponse(status="SUCCESS", content="hello there"))
    app = _make_app(agent=agent, reply_to_mentions_only=True)
    client = TestClient(app)

    ts = str(time.time())
    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "Hello agent",
                "user": "U123",
                "channel": "C123",
                "ts": ts,
            },
        },
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=ok"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    assert len(tasks) == 1
    func, args, kwargs = tasks[0]
    asyncio.run(func(*args, **kwargs))

    assert agent.calls and agent.calls[0][0] == "Hello agent"
    assert len(sent) == 1
    assert sent[0]["channel"] == "C123"
    assert sent[0]["thread_ts"] == ts
    assert "hello there" in sent[0]["text"]


def test_slack_non_dm_message_ignored_when_reply_to_mentions_only(monkeypatch):
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: True)

    tasks: List[Tuple[Any, tuple, dict]] = []
    sent: List[Dict[str, Any]] = []

    def _capture_task(self, func, *args, **kwargs):
        tasks.append((func, args, kwargs))

    class _FakeSlackTools:
        def __init__(self):
            pass

        def send_message(self, channel: str, text: str, thread_ts: str = None) -> str:
            sent.append({"channel": channel, "text": text, "thread_ts": thread_ts})
            return json.dumps({"ok": True})

        def download_file_bytes(self, file_id: str) -> bytes:
            return b"test file content"

    monkeypatch.setattr("agno.os.interfaces.slack.router.BackgroundTasks.add_task", _capture_task)
    monkeypatch.setattr("agno.os.interfaces.slack.router.SlackTools", _FakeSlackTools)

    agent = _FakeAgent(_FakeRunResponse(status="SUCCESS", content="should not reply"))
    app = _make_app(agent=agent, reply_to_mentions_only=True)
    client = TestClient(app)

    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "text": "Hello agent",
                "user": "U123",
                "channel": "C123",
                "ts": "1.0",
            },
        },
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=ok"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    assert len(tasks) == 1
    func, args, kwargs = tasks[0]
    asyncio.run(func(*args, **kwargs))

    assert sent == []


def test_slack_app_mention_triggers_reply(monkeypatch):
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: True)

    tasks: List[Tuple[Any, tuple, dict]] = []
    sent: List[Dict[str, Any]] = []

    def _capture_task(self, func, *args, **kwargs):
        tasks.append((func, args, kwargs))

    class _FakeSlackTools:
        def __init__(self):
            pass

        def send_message(self, channel: str, text: str, thread_ts: str = None) -> str:
            sent.append({"channel": channel, "text": text, "thread_ts": thread_ts})
            return json.dumps({"ok": True})

        def download_file_bytes(self, file_id: str) -> bytes:
            return b"test file content"

    monkeypatch.setattr("agno.os.interfaces.slack.router.BackgroundTasks.add_task", _capture_task)
    monkeypatch.setattr("agno.os.interfaces.slack.router.SlackTools", _FakeSlackTools)

    agent = _FakeAgent(_FakeRunResponse(status="SUCCESS", content="42", reasoning_content="Because math"))
    app = _make_app(agent=agent, reply_to_mentions_only=True)
    client = TestClient(app)

    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "<@BOTID> What is 2 + 2?",
                "user": "U123",
                "channel": "C123",
                "ts": "1.0",
            },
        },
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=ok"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    assert len(tasks) == 1
    func, args, kwargs = tasks[0]
    asyncio.run(func(*args, **kwargs))

    assert len(sent) == 2
    assert "Reasoning" in sent[0]["text"]
    assert "Because math" in sent[0]["text"]
    assert sent[1]["text"] == "42"


def test_slack_auto_uploads_files_from_response(monkeypatch):
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: True)

    tasks: List[Tuple[Any, tuple, dict]] = []
    sent: List[Dict[str, Any]] = []
    uploads: List[Dict[str, Any]] = []

    def _capture_task(self, func, *args, **kwargs):
        tasks.append((func, args, kwargs))

    class _FakeSlackTools:
        def __init__(self):
            pass

        def send_message(self, channel: str, text: str, thread_ts: str = None) -> str:
            sent.append({"channel": channel, "text": text, "thread_ts": thread_ts})
            return json.dumps({"ok": True})

        def upload_file(self, channel: str, content, filename: str, thread_ts: str = None, **kwargs) -> str:
            uploads.append({"channel": channel, "content": content, "filename": filename, "thread_ts": thread_ts})
            return json.dumps({"ok": True})

        def download_file_bytes(self, file_id: str) -> bytes:
            return b"test file content"

    monkeypatch.setattr("agno.os.interfaces.slack.router.BackgroundTasks.add_task", _capture_task)
    monkeypatch.setattr("agno.os.interfaces.slack.router.SlackTools", _FakeSlackTools)

    test_file = _FakeFile(content=b"name,email\nAlice,alice@example.com", filename="users.csv")
    agent = _FakeAgent(_FakeRunResponse(status="SUCCESS", content="Here is your CSV", files=[test_file]))
    app = _make_app(agent=agent, reply_to_mentions_only=True)
    client = TestClient(app)

    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "<@BOTID> Generate a CSV",
                "user": "U123",
                "channel": "C123",
                "ts": "1.0",
            },
        },
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=ok"},
    )
    assert response.status_code == 200

    func, args, kwargs = tasks[0]
    asyncio.run(func(*args, **kwargs))

    assert len(sent) == 1
    assert "Here is your CSV" in sent[0]["text"]
    assert len(uploads) == 1
    assert uploads[0]["filename"] == "users.csv"
    assert uploads[0]["content"] == b"name,email\nAlice,alice@example.com"
    assert uploads[0]["channel"] == "C123"
    assert uploads[0]["thread_ts"] == "1.0"


def test_slack_auto_uploads_images_from_response(monkeypatch):
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: True)

    tasks: List[Tuple[Any, tuple, dict]] = []
    sent: List[Dict[str, Any]] = []
    uploads: List[Dict[str, Any]] = []

    def _capture_task(self, func, *args, **kwargs):
        tasks.append((func, args, kwargs))

    class _FakeSlackTools:
        def __init__(self):
            pass

        def send_message(self, channel: str, text: str, thread_ts: str = None) -> str:
            sent.append({"channel": channel, "text": text, "thread_ts": thread_ts})
            return json.dumps({"ok": True})

        def upload_file(self, channel: str, content, filename: str, thread_ts: str = None, **kwargs) -> str:
            uploads.append({"channel": channel, "content": content, "filename": filename, "thread_ts": thread_ts})
            return json.dumps({"ok": True})

        def download_file_bytes(self, file_id: str) -> bytes:
            return b"test file content"

    monkeypatch.setattr("agno.os.interfaces.slack.router.BackgroundTasks.add_task", _capture_task)
    monkeypatch.setattr("agno.os.interfaces.slack.router.SlackTools", _FakeSlackTools)

    test_image = _FakeImage(content=b"\x89PNG\r\n\x1a\n...", filename="chart.png")
    agent = _FakeAgent(_FakeRunResponse(status="SUCCESS", content="Here is the chart", images=[test_image]))
    app = _make_app(agent=agent, reply_to_mentions_only=True)
    client = TestClient(app)

    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "<@BOTID> Generate a chart",
                "user": "U123",
                "channel": "C456",
                "ts": "2.0",
            },
        },
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=ok"},
    )
    assert response.status_code == 200

    func, args, kwargs = tasks[0]
    asyncio.run(func(*args, **kwargs))

    assert len(sent) == 1
    assert len(uploads) == 1
    assert uploads[0]["filename"] == "chart.png"
    assert uploads[0]["channel"] == "C456"


def test_slack_auto_downloads_files_from_event(monkeypatch):
    """Test that files shared in the event are downloaded and passed to the agent."""
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: True)

    tasks: List[Tuple[Any, tuple, dict]] = []
    sent: List[Dict[str, Any]] = []
    downloaded_files: List[str] = []

    def _capture_task(self, func, *args, **kwargs):
        tasks.append((func, args, kwargs))

    class _FakeSlackTools:
        def __init__(self):
            pass

        def send_message(self, channel: str, text: str, thread_ts: str = None) -> str:
            sent.append({"channel": channel, "text": text, "thread_ts": thread_ts})
            return json.dumps({"ok": True})

        def download_file_bytes(self, file_id: str) -> bytes:
            downloaded_files.append(file_id)
            return b"name,email\nAlice,alice@example.com"

    monkeypatch.setattr("agno.os.interfaces.slack.router.BackgroundTasks.add_task", _capture_task)
    monkeypatch.setattr("agno.os.interfaces.slack.router.SlackTools", _FakeSlackTools)

    agent = _FakeAgent(_FakeRunResponse(status="SUCCESS", content="I see your CSV file"))
    app = _make_app(agent=agent, reply_to_mentions_only=True)
    client = TestClient(app)

    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "<@BOTID> Analyze this file",
                "user": "U123",
                "channel": "C123",
                "ts": "1.0",
                "files": [
                    {
                        "id": "F12345",
                        "name": "data.csv",
                        "mimetype": "text/csv",
                    }
                ],
            },
        },
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=ok"},
    )
    assert response.status_code == 200

    func, args, kwargs = tasks[0]
    asyncio.run(func(*args, **kwargs))

    # Verify file was downloaded
    assert "F12345" in downloaded_files

    # Verify file was passed to agent
    assert len(agent.received_files) == 1
    assert agent.received_files[0].content == b"name,email\nAlice,alice@example.com"
    assert agent.received_files[0].filename == "data.csv"
    assert agent.received_files[0].mime_type == "text/csv"


def test_slack_auto_downloads_images_from_event(monkeypatch):
    """Test that images shared in the event are downloaded and passed to the agent."""
    monkeypatch.setattr("agno.os.interfaces.slack.router.verify_slack_signature", lambda *args, **kwargs: True)

    tasks: List[Tuple[Any, tuple, dict]] = []
    sent: List[Dict[str, Any]] = []
    downloaded_files: List[str] = []

    def _capture_task(self, func, *args, **kwargs):
        tasks.append((func, args, kwargs))

    class _FakeSlackTools:
        def __init__(self):
            pass

        def send_message(self, channel: str, text: str, thread_ts: str = None) -> str:
            sent.append({"channel": channel, "text": text, "thread_ts": thread_ts})
            return json.dumps({"ok": True})

        def download_file_bytes(self, file_id: str) -> bytes:
            downloaded_files.append(file_id)
            return b"\x89PNG\r\n\x1a\n..."

    monkeypatch.setattr("agno.os.interfaces.slack.router.BackgroundTasks.add_task", _capture_task)
    monkeypatch.setattr("agno.os.interfaces.slack.router.SlackTools", _FakeSlackTools)

    agent = _FakeAgent(_FakeRunResponse(status="SUCCESS", content="I see your image"))
    app = _make_app(agent=agent, reply_to_mentions_only=True)
    client = TestClient(app)

    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "<@BOTID> What's in this image?",
                "user": "U123",
                "channel": "C123",
                "ts": "1.0",
                "files": [
                    {
                        "id": "F67890",
                        "name": "photo.png",
                        "mimetype": "image/png",
                    }
                ],
            },
        },
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=ok"},
    )
    assert response.status_code == 200

    func, args, kwargs = tasks[0]
    asyncio.run(func(*args, **kwargs))

    # Verify image was downloaded
    assert "F67890" in downloaded_files

    # Verify image was passed to agent (as Image, not File)
    assert len(agent.received_images) == 1
    assert agent.received_images[0].content == b"\x89PNG\r\n\x1a\n..."
