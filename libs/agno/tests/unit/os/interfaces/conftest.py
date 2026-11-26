import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

SIGNING_SECRET = "test-secret"
TOKEN = "xoxb-test"
BOT_ID = "B_SELF"
BOT_USER_ID = "U_SELF"
SLACK_LIMIT = 12_000


def sign(body: bytes, timestamp: str, signing_secret: str = SIGNING_SECRET) -> str:
    sig_base = f"v0:{timestamp}:{body.decode()}"
    return "v0=" + hmac.new(signing_secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()


def make_signed_request(
    client: TestClient,
    body: Any,
    signing_secret: str = SIGNING_SECRET,
    path: str = "/events",
    headers: Optional[Dict[str, str]] = None,
):
    """POST a body signed as Slack signs it: JSON for events, a form `payload=` for interactions."""
    if isinstance(body, bytes):
        body_bytes, content_type = body, "application/json"
    elif path.endswith("/interactions"):
        body_bytes, content_type = (
            urlencode({"payload": json.dumps(body)}).encode(),
            "application/x-www-form-urlencoded",
        )
    else:
        body_bytes, content_type = json.dumps(body).encode(), "application/json"
    timestamp = str(int(time.time()))
    return client.post(
        path,
        content=body_bytes,
        headers={
            "Content-Type": content_type,
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": sign(body_bytes, timestamp, signing_secret),
            **(headers or {}),
        },
    )


def build_app(agent_mock: Mock, **kwargs) -> FastAPI:
    from agno.os.interfaces.slack.router import attach_routes

    kwargs.setdefault("streaming", False)
    kwargs.setdefault("token", TOKEN)
    kwargs.setdefault("signing_secret", SIGNING_SECRET)
    app = FastAPI()
    router = APIRouter()
    attach_routes(router, agent=agent_mock, **kwargs)
    app.include_router(router)
    return app


def make_agent_mock():
    agent_mock = AsyncMock()
    agent_mock.id = "agent-1"
    agent_mock.name = "Test Agent"
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK", content="done", reasoning_content=None, images=None, files=None, videos=None, audio=None
        )
    )
    # Session lookup returns None by default so resolve_session_id uses the new key format
    agent_mock.aget_session = AsyncMock(return_value=None)
    return agent_mock


def make_async_client_mock():
    client = AsyncMock()
    client.assistant_threads_setStatus = AsyncMock()
    client.assistant_threads_setTitle = AsyncMock()
    client.assistant_threads_setSuggestedPrompts = AsyncMock()
    client.chat_postMessage = AsyncMock()
    client.chat_postEphemeral = AsyncMock()
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


def make_ctx(**overrides: Any):
    """A SlackContext for handler tests, shaped like the interface builds it."""
    from agno.os.interfaces.slack.context import build_context

    settings: Dict[str, Any] = {"agent": make_agent_mock(), "token": TOKEN, "signing_secret": SIGNING_SECRET}
    settings.update(overrides)
    return build_context(**settings)


def make_event_context(**overrides: Any):
    """An EventContext for one run, with any field overridden."""
    from agno.os.interfaces.slack.context import EventContext

    fields: Dict[str, Any] = {
        "run_id": "run-1",
        "session_id": "agent-1:C1:100.1",
        "channel": "C1",
        "thread_ts": "100.1",
        "message_ts": "100.1",
        "owner": "U1",
        "user_id": "U1",
        "entity_id": "agent-1",
        "team_id": "T1",
    }
    fields.update(overrides)
    return EventContext(**fields)


def make_message_event_context(ctx: Any, text: str = "hello", ts: str = "100.1", **event_fields: Any):
    """The EventContext a Slack message gets, with the session id resolve_context gives it."""
    from agno.os.interfaces.slack.context import new_event_context

    event_context = new_event_context(make_event_body(text=text, ts=ts, **event_fields), ctx)
    event_context.session_id = f"{ctx.entity_id}:{event_context.channel}:{event_context.thread_ts}"
    return event_context


def make_event_body(
    text: str = "hello",
    user: str = "U123",
    channel: str = "C123",
    ts: str = "1700000000.000100",
    thread_ts: Optional[str] = None,
    event_type: str = "message",
    channel_type: str = "im",
    team_id: str = "T123",
    event_id: str = "Ev1",
    **event_fields: Any,
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "type": event_type,
        "channel_type": channel_type,
        "text": text,
        "user": user,
        "channel": channel,
        "ts": ts,
        **event_fields,
    }
    if thread_ts:
        event["thread_ts"] = thread_ts
    return {
        "type": "event_callback",
        "team_id": team_id,
        "event_id": event_id,
        "authorizations": [{"user_id": BOT_USER_ID}],
        "event": event,
    }


def make_stop_body(
    user: str = "U123",
    channel: str = "C123",
    thread_ts: str = "1700000000.000100",
    streaming_message_ts: Optional[list] = None,
    event_id: str = "EvStop",
) -> Dict[str, Any]:
    return {
        "type": "event_callback",
        "team_id": "T123",
        "event_id": event_id,
        "event": {
            "type": "agent_session_stopped",
            "channel": channel,
            "thread_ts": thread_ts,
            "streaming_message_ts": streaming_message_ts or [],
            "user": user,
            "event_ts": "1700000001.000100",
        },
    }


def make_action_body(action_id: str, value: str = "", user: str = "U123") -> Dict[str, Any]:
    return {
        "type": "block_actions",
        "team": {"id": "T123"},
        "user": {"id": user},
        "channel": {"id": "C123"},
        "message": {"ts": "222.333", "thread_ts": "111.222", "blocks": []},
        "actions": [{"action_id": action_id, "block_id": "b1", "value": value}],
    }


def wait_until(condition, timeout: float = 5.0) -> None:
    """Wait in the test thread for work the app spawned after acking."""
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)


def slack_error(code: str):
    from slack_sdk.errors import SlackApiError

    return SlackApiError(code, Mock(data={"ok": False, "error": code}))


def _text_of(chunks: Any) -> str:
    out = ""
    for chunk in chunks or []:
        data = chunk if isinstance(chunk, dict) else chunk.to_dict()
        if data.get("type") == "markdown_text":
            out += data.get("text", "")
    return out


def _cards_of(chunks: Any) -> List[Dict[str, Any]]:
    out = []
    for chunk in chunks or []:
        data = chunk if isinstance(chunk, dict) else chunk.to_dict()
        if data.get("type") == "task_update":
            out.append(data)
    return out


class FakeSlack:
    """Slack's stream methods with their limits: 12,000 chars, the first 50 cards per message, nothing after a stop.

    chat_stream returns slack_sdk's own ChatStream, which keeps refused text in its buffer, so a
    stream built on it would show the duplicates these tests guard against.
    """

    def __init__(self, unit: str = "char", slow: float = 0.0):
        self.unit = unit
        self.slow = slow
        self.msgs: Dict[str, Dict[str, Any]] = {}
        self.order: List[str] = []
        self.calls: List[tuple] = []
        self.fail_next: Dict[str, List[str]] = {}
        self.assistant_threads_setStatus = AsyncMock()

    def _size(self, text: str) -> int:
        return len(text.encode("utf-16-le")) // 2 if self.unit == "utf16" else len(text)

    def _maybe_fail(self, method: str) -> None:
        queue = self.fail_next.get(method)
        if queue:
            raise slack_error(queue.pop(0))

    def _apply(self, msg: Dict[str, Any], chunks: Any) -> None:
        text = _text_of(chunks)
        if msg["size"] + self._size(text) > SLACK_LIMIT:
            raise slack_error("msg_too_long")
        msg["text"] += text
        msg["size"] += self._size(text)
        for card in _cards_of(chunks):
            # Slack keeps the first 50 cards of a message and drops the rest without an error
            if card["id"] in msg["cards"] or len(msg["cards"]) < 50:
                msg["cards"][card["id"]] = (card.get("title"), card.get("status"))

    async def chat_stream(self, **kwargs: Any):
        from slack_sdk.web.async_chat_stream import AsyncChatStream

        return AsyncChatStream(self, logger=logging.getLogger("test"), **kwargs)

    async def chat_startStream(self, **kwargs: Any) -> Dict[str, Any]:
        if self.slow:
            await asyncio.sleep(self.slow)
        self.calls.append(("start", kwargs))
        self._maybe_fail("start")
        ts = f"900.{len(self.order) + 1}"
        msg = {"text": "", "size": 0, "cards": {}, "stopped": False, "status": None}
        self._apply(msg, kwargs.get("chunks"))
        self.msgs[ts] = msg
        self.order.append(ts)
        return {"ok": True, "ts": ts}

    async def chat_appendStream(self, **kwargs: Any) -> Dict[str, Any]:
        if self.slow:
            await asyncio.sleep(self.slow)
        self.calls.append(("append", kwargs))
        msg = self.msgs[kwargs["ts"]]
        if msg["stopped"]:
            raise slack_error("message_not_in_streaming_state")
        self._maybe_fail("append")
        self._apply(msg, kwargs.get("chunks"))
        return {"ok": True}

    async def chat_stopStream(self, **kwargs: Any) -> Dict[str, Any]:
        if self.slow:
            await asyncio.sleep(self.slow)
        self.calls.append(("stop", kwargs))
        msg = self.msgs[kwargs["ts"]]
        if msg["stopped"]:
            raise slack_error("message_not_in_streaming_state")
        self._maybe_fail("stop")
        self._apply(msg, kwargs.get("chunks"))
        msg["stopped"] = True
        msg["status"] = kwargs.get("session_status")
        # A card still open when its stream stops shows as failed
        for card_id, (title, status) in list(msg["cards"].items()):
            if status == "in_progress":
                msg["cards"][card_id] = (title, "error")
        return {"ok": True}

    def texts(self) -> List[str]:
        return [self.msgs[ts]["text"] for ts in self.order]

    def joined(self) -> str:
        from agno.os.interfaces.slack.stream import _CONTINUED_PREFIX

        return "".join(t[len(_CONTINUED_PREFIX) :] if t.startswith(_CONTINUED_PREFIX) else t for t in self.texts())


def make_client() -> Any:
    """An AsyncMock Slack client whose stream methods behave like FakeSlack's."""
    fake = FakeSlack()
    client = make_async_client_mock()
    client.chat_startStream = AsyncMock(side_effect=fake.chat_startStream)
    client.chat_appendStream = AsyncMock(side_effect=fake.chat_appendStream)
    client.chat_stopStream = AsyncMock(side_effect=fake.chat_stopStream)
    client.fake = fake
    return client


@pytest.fixture
def auth_test_mock():
    from slack_sdk.web.async_client import AsyncWebClient

    mock = AsyncMock(return_value={"ok": True, "bot_id": BOT_ID, "user_id": BOT_USER_ID})
    with patch.object(AsyncWebClient, "auth_test", mock):
        yield mock


@pytest.fixture
def async_client_mock():
    return make_async_client_mock()
