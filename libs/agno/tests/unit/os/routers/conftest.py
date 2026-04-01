import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

SIGNING_SECRET = "test-secret"


def make_signed_request(client: TestClient, body: dict, signing_secret: str = SIGNING_SECRET):
    body_bytes = json.dumps(body).encode()
    timestamp = str(int(time.time()))
    sig_base = f"v0:{timestamp}:{body_bytes.decode()}"
    signature = "v0=" + hmac.new(signing_secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()
    return client.post(
        "/events",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        },
    )


def build_app(agent_mock: Mock, **kwargs) -> FastAPI:
    from agno.os.interfaces.slack.router import attach_routes

    kwargs.setdefault("streaming", False)
    app = FastAPI()
    router = APIRouter()
    attach_routes(router, agent=agent_mock, **kwargs)
    app.include_router(router)
    return app


def make_agent_mock():
    agent_mock = AsyncMock()
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK", content="done", reasoning_content=None, images=None, files=None, videos=None, audio=None
        )
    )
    return agent_mock


def make_slack_mock(**kwargs):
    mock_slack = Mock()
    mock_slack.send_message = Mock()
    mock_slack.upload_file = Mock()
    mock_slack.max_file_size = 1_073_741_824
    for k, v in kwargs.items():
        setattr(mock_slack, k, v)
    return mock_slack


def slack_event_with_files(files: list, event_type: str = "message") -> dict:
    for f in files:
        f.setdefault("url_private", f"https://files.slack.com/{f.get('id', 'F0')}")
        f.setdefault("size", 100)
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


def make_httpx_mock(responses: list[bytes] | bytes = b"file-data"):
    if isinstance(responses, bytes):
        responses = [responses]
    idx = {"i": 0}

    async def _get(*args, **kwargs):
        data = responses[min(idx["i"], len(responses) - 1)]
        idx["i"] += 1
        resp = Mock()
        resp.content = data
        resp.raise_for_status = Mock()
        return resp

    client = AsyncMock()
    client.get = _get
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def make_stream_mock():
    stream = AsyncMock()
    stream.append = AsyncMock()
    stream.stop = AsyncMock()
    return stream


def make_async_client_mock(stream_mock=None):
    client = AsyncMock()
    client.assistant_threads_setStatus = AsyncMock()
    client.assistant_threads_setTitle = AsyncMock()
    client.assistant_threads_setSuggestedPrompts = AsyncMock()
    client.chat_stream = AsyncMock(return_value=stream_mock or make_stream_mock())
    return client


def make_streaming_body(
    user: str = "U_HUMAN",
    channel: str = "C123",
    thread_ts: str | None = None,
    text: str = "hello",
    team_id: str = "T123",
    bot_user_id: str = "B_BOT",
) -> dict:
    ts = thread_ts or str(time.time())
    return {
        "type": "event_callback",
        "team_id": team_id,
        "authorizations": [{"user_id": bot_user_id}],
        "event": {
            "type": "message",
            "channel_type": "im",
            "text": text,
            "user": user,
            "channel": channel,
            "ts": str(float(ts) + 1),
            "thread_ts": ts,
        },
    }


def make_streaming_agent(chunks=None):
    agent = AsyncMock()
    agent.name = "Test Agent"

    async def _arun_stream(*args, **kwargs):
        for c in chunks or []:
            yield c

    agent.arun = _arun_stream
    return agent


def content_chunk(text):
    from agno.agent import RunEvent

    return Mock(
        event=RunEvent.run_content.value, content=text, tool=None, images=None, videos=None, audio=None, files=None
    )


async def wait_for_call(mock_method, timeout: float = 5.0):
    import asyncio

    elapsed = 0.0
    while not mock_method.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1


@pytest.fixture
def agent_mock():
    return make_agent_mock()


@pytest.fixture
def slack_mock():
    return make_slack_mock()


@pytest.fixture
def stream_mock():
    return make_stream_mock()


@pytest.fixture
def async_client_mock(stream_mock):
    return make_async_client_mock(stream_mock)
