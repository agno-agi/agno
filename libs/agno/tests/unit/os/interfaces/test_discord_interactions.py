"""Unit tests for the Discord Interactions endpoint: ephemeral replies and
user-installable command registration. No live Discord needed — requests are
signed locally with the same Ed25519 scheme Discord uses."""

import json
import time
from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from agno.agent import Agent
from agno.os.interfaces.discord.interactions import DiscordInteractions
from agno.os.interfaces.discord.router import attach_routes

SIGNING_KEY = SigningKey.generate()
PUBLIC_KEY = SIGNING_KEY.verify_key.encode().hex()

EPHEMERAL_FLAG = 64


def _client(ephemeral: bool = False) -> TestClient:
    agent = Agent(name="Interactions Test Agent")
    router = attach_routes(
        router=APIRouter(prefix="/discord"),
        agent=agent,
        public_key=PUBLIC_KEY,
        application_id="app-id",
        bot_token="bot-token",
        ephemeral=ephemeral,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _signed_post(client: TestClient, body: dict):
    raw = json.dumps(body).encode()
    ts = str(int(time.time()))
    sig = SIGNING_KEY.sign(ts.encode() + raw).signature.hex()
    return client.post(
        "/discord/interactions",
        content=raw,
        headers={
            "X-Signature-Ed25519": sig,
            "X-Signature-Timestamp": ts,
            "Content-Type": "application/json",
        },
    )


def _ask_payload(extra_options=None) -> dict:
    options = [{"name": "question", "value": "hello"}]
    if extra_options:
        options.extend(extra_options)
    return {
        "type": 2,
        "token": "interaction-token",
        "channel_id": "123",
        "guild_id": "456",
        "channel": {"type": 0},
        "member": {"user": {"id": "789", "username": "tester"}},
        "data": {"name": "ask", "options": options},
    }


# === Ephemeral deferred ack ===


def test_default_ask_is_public():
    client = _client()
    with patch("agno.os.interfaces.discord.router.asyncio.create_task") as create_task:
        resp = _signed_post(client, _ask_payload())
    assert resp.status_code == 200
    assert resp.json() == {"type": 5}
    create_task.call_args[0][0].close()


def test_ephemeral_option_sets_flag():
    client = _client()
    with patch("agno.os.interfaces.discord.router.asyncio.create_task") as create_task:
        resp = _signed_post(client, _ask_payload([{"name": "ephemeral", "value": True}]))
    assert resp.json() == {"type": 5, "data": {"flags": EPHEMERAL_FLAG}}
    create_task.call_args[0][0].close()


def test_interface_default_ephemeral():
    client = _client(ephemeral=True)
    with patch("agno.os.interfaces.discord.router.asyncio.create_task") as create_task:
        resp = _signed_post(client, _ask_payload())
    assert resp.json() == {"type": 5, "data": {"flags": EPHEMERAL_FLAG}}
    create_task.call_args[0][0].close()


def test_option_overrides_interface_default_back_to_public():
    client = _client(ephemeral=True)
    with patch("agno.os.interfaces.discord.router.asyncio.create_task") as create_task:
        resp = _signed_post(client, _ask_payload([{"name": "ephemeral", "value": False}]))
    assert resp.json() == {"type": 5}
    create_task.call_args[0][0].close()


def test_unsigned_request_is_rejected():
    client = _client()
    resp = client.post("/discord/interactions", json=_ask_payload())
    assert resp.status_code == 401


# === Command registration payload ===


def _interface(**kwargs) -> DiscordInteractions:
    agent = Agent(name="Interactions Test Agent")
    return DiscordInteractions(
        agent=agent,
        public_key=PUBLIC_KEY,
        application_id="app-id",
        bot_token="bot-token",
        auto_register_command=False,
        **kwargs,
    )


def test_user_install_registration_payload():
    payload = _interface(user_install=True)._build_command_payload()
    assert len(payload) == 2
    for command in payload:
        assert command["integration_types"] == [0, 1]
        assert command["contexts"] == [0, 1, 2]


def test_guild_only_registration_payload():
    payload = _interface(user_install=False)._build_command_payload()
    for command in payload:
        assert "integration_types" not in command
        assert "contexts" not in command


def test_ask_command_has_ephemeral_option():
    payload = _interface()._build_command_payload()
    ask = payload[0]
    option_names = [opt["name"] for opt in ask["options"]]
    assert option_names == ["question", "file", "ephemeral"]
    ephemeral_option = ask["options"][2]
    assert ephemeral_option["type"] == 5
    assert ephemeral_option["required"] is False
