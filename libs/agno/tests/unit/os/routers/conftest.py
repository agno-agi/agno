import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from slack_bolt.authorization import AuthorizeResult

# Bound at import time: some tests patch httpx.AsyncClient to stub file downloads,
# and the harness must keep talking to the ASGI app while that patch is active.
_ASGITransport = httpx.ASGITransport
_AsyncClient = httpx.AsyncClient

SIGNING_SECRET = "test-secret"
BOT_TOKEN = "xoxb-test"
# Identity Bolt attributes to this app; events carrying these ids are the bot's own
OWN_BOT_ID = "B_SELF"
OWN_BOT_USER_ID = "U_SELF_BOT"


async def stub_authorize(**kwargs: Any) -> AuthorizeResult:
    """Replaces Bolt's auth.test lookup so tests never touch the network."""
    return AuthorizeResult(
        enterprise_id=None,
        team_id="T123",
        bot_id=OWN_BOT_ID,
        bot_user_id=OWN_BOT_USER_ID,
        bot_token=BOT_TOKEN,
    )


def _asgi_app(client_or_app: Any) -> FastAPI:
    # Accept a FastAPI app or anything exposing one (e.g. a TestClient)
    return getattr(client_or_app, "app", client_or_app)


def sign_headers(body_bytes: bytes, signing_secret: str = SIGNING_SECRET, **extra: str) -> dict:
    timestamp = str(int(time.time()))
    sig_base = f"v0:{timestamp}:{body_bytes.decode()}"
    signature = "v0=" + hmac.new(signing_secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
    }
    headers.update(extra)
    return headers


async def post_raw(client_or_app: Any, path: str, content: bytes, headers: dict) -> httpx.Response:
    # Bolt continues the listener as an asyncio task after acknowledging, so the request
    # must run on the test's own event loop for the follow-up work to be observable.
    transport = _ASGITransport(app=_asgi_app(client_or_app))
    async with _AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, content=content, headers=headers)


async def make_signed_request(
    client_or_app: Any, body: dict, signing_secret: str = SIGNING_SECRET, **extra_headers: str
) -> httpx.Response:
    body_bytes = json.dumps(body).encode()
    return await post_raw(
        client_or_app, "/events", body_bytes, sign_headers(body_bytes, signing_secret, **extra_headers)
    )


async def make_signed_interaction(
    client_or_app: Any, payload: dict, signing_secret: str = SIGNING_SECRET, **extra_headers: str
) -> httpx.Response:
    from urllib.parse import urlencode

    body_bytes = urlencode({"payload": json.dumps(payload)}).encode()
    headers = sign_headers(body_bytes, signing_secret, **extra_headers)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    return await post_raw(client_or_app, "/interactions", body_bytes, headers)


def build_app(agent_mock: Mock, **kwargs) -> FastAPI:
    from agno.os.interfaces.slack import Slack

    kwargs.setdefault("streaming", False)
    kwargs.setdefault("token", BOT_TOKEN)
    kwargs.setdefault("signing_secret", SIGNING_SECRET)
    authorize = kwargs.pop("authorize", stub_authorize)
    app = FastAPI()
    router = APIRouter()
    Slack(agent=agent_mock, **kwargs).attach(router, authorize=authorize)
    app.include_router(router)
    return app


def make_agent_mock():
    agent_mock = AsyncMock()
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK", content="done", reasoning_content=None, images=None, files=None, videos=None, audio=None
        )
    )
    # Session lookup returns None by default so resolve_session_id uses the new key format
    agent_mock.aget_session = AsyncMock(return_value=None)
    return agent_mock


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
    client.chat_postMessage = AsyncMock()
    # Used by resolve_slack_user() and bot_name_resolver.resolve()
    client.users_info = AsyncMock(
        return_value={
            "ok": True,
            "user": {
                "id": "U123",
                "name": "testuser",
                "profile": {
                    "email": "test@example.com",
                    "display_name": "Test User",
                    "real_name": "Test User",
                },
            },
        }
    )
    # Used by resolve_channel_name()
    client.conversations_info = AsyncMock(return_value={"ok": True, "channel": {"name": "general"}})
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
    # Session lookup returns None by default so resolve_session_id uses the new key format
    agent.aget_session = AsyncMock(return_value=None)

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
        await asyncio.sleep(0.05)
        elapsed += 0.05


@pytest.fixture
def agent_mock():
    return make_agent_mock()


@pytest.fixture
def stream_mock():
    return make_stream_mock()


@pytest.fixture
def async_client_mock(stream_mock):
    return make_async_client_mock(stream_mock)
