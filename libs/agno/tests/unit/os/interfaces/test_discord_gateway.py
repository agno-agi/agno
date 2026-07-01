"""Unit tests for the Discord Gateway events endpoint and gating logic.

These tests exercise the FastAPI route and the pure gating helpers only —
no discord.py required, no listener thread started.
"""

from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os.interfaces.discord.gateway_router import (
    GATEWAY_SECRET_HEADER,
    attach_gateway_routes,
    should_respond,
    strip_bot_mention,
)

SECRET = "test-gateway-secret"
BOT_ID = "111111111111111111"


def _payload(**overrides) -> dict:
    base = {
        "type": "message",
        "message_id": "200",
        "channel_id": "300",
        "guild_id": "400",
        "channel_type": 0,
        "is_dm": False,
        "is_thread": False,
        "thread_parent_id": None,
        "author": {"id": "500", "username": "tester", "global_name": "Tester", "bot": False},
        "bot_user_id": BOT_ID,
        "mentions_bot": False,
        "bot_in_thread": False,
        "content": "hello there",
        "attachments": [],
    }
    base.update(overrides)
    return base


def _client() -> TestClient:
    agent = Agent(name="Gateway Test Agent")
    router = attach_gateway_routes(
        router=APIRouter(prefix="/discord"),
        agent=agent,
        bot_token="test-bot-token",
        gateway_secret=SECRET,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# === Endpoint auth ===


def test_missing_secret_returns_401():
    client = _client()
    resp = client.post("/discord/gateway/events", json=_payload())
    assert resp.status_code == 401


def test_wrong_secret_returns_401():
    client = _client()
    resp = client.post("/discord/gateway/events", json=_payload(), headers={GATEWAY_SECRET_HEADER: "wrong"})
    assert resp.status_code == 401


def test_non_message_type_is_ignored():
    client = _client()
    resp = client.post(
        "/discord/gateway/events",
        json=_payload(type="reaction"),
        headers={GATEWAY_SECRET_HEADER: SECRET},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}


def test_unmentioned_channel_message_is_ignored():
    client = _client()
    resp = client.post(
        "/discord/gateway/events",
        json=_payload(),
        headers={GATEWAY_SECRET_HEADER: SECRET},
    )
    assert resp.json() == {"status": "ignored"}


def test_mentioned_channel_message_is_accepted():
    client = _client()
    with patch("agno.os.interfaces.discord.gateway_router.asyncio.create_task") as create_task:
        resp = client.post(
            "/discord/gateway/events",
            json=_payload(mentions_bot=True, content=f"<@{BOT_ID}> hello"),
            headers={GATEWAY_SECRET_HEADER: SECRET},
        )
    assert resp.json() == {"status": "accepted"}
    assert create_task.called
    create_task.call_args[0][0].close()


def test_dm_is_accepted_without_mention():
    client = _client()
    with patch("agno.os.interfaces.discord.gateway_router.asyncio.create_task") as create_task:
        resp = client.post(
            "/discord/gateway/events",
            json=_payload(is_dm=True, guild_id=None),
            headers={GATEWAY_SECRET_HEADER: SECRET},
        )
    assert resp.json() == {"status": "accepted"}
    create_task.call_args[0][0].close()


def test_bot_author_is_ignored():
    client = _client()
    resp = client.post(
        "/discord/gateway/events",
        json=_payload(is_dm=True, author={"id": "500", "username": "other-bot", "global_name": None, "bot": True}),
        headers={GATEWAY_SECRET_HEADER: SECRET},
    )
    assert resp.json() == {"status": "ignored"}


# === Gating matrix ===


def test_should_respond_self_message():
    assert should_respond(_payload(is_dm=True, author={"id": BOT_ID, "bot": False})) is False


def test_should_respond_dm_disabled():
    assert should_respond(_payload(is_dm=True), respond_to_dms=False) is False


def test_should_respond_thread_with_bot_participation():
    assert should_respond(_payload(is_thread=True, bot_in_thread=True)) is True


def test_should_respond_thread_without_participation_or_mention():
    assert should_respond(_payload(is_thread=True)) is False


def test_should_respond_thread_with_mention_only():
    assert should_respond(_payload(is_thread=True, mentions_bot=True)) is True


def test_should_respond_channel_with_mention():
    assert should_respond(_payload(mentions_bot=True)) is True


# === Mention stripping ===


def test_strip_plain_mention():
    assert strip_bot_mention(f"<@{BOT_ID}> hello", BOT_ID) == "hello"


def test_strip_nickname_mention():
    assert strip_bot_mention(f"<@!{BOT_ID}> hello", BOT_ID) == "hello"


def test_strip_mention_mid_message():
    assert strip_bot_mention(f"hey <@{BOT_ID}> what is up", BOT_ID) == "hey  what is up"


def test_strip_leaves_other_mentions():
    assert strip_bot_mention("<@999> hello", BOT_ID) == "<@999> hello"
