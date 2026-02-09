import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.os.interfaces.discord.discord import Discord


def _make_signing_helpers():
    from nacl.signing import SigningKey

    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key
    public_key_hex = verify_key.encode().hex()
    return signing_key, public_key_hex


def _sign(signing_key, body: bytes, timestamp: str) -> str:
    message = timestamp.encode() + body
    signed = signing_key.sign(message)
    return signed.signature.hex()


SIGNING_KEY, PUBLIC_KEY_HEX = _make_signing_helpers()


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.arun = AsyncMock()
    agent.acontinue_run = AsyncMock()
    return agent


def _make_app(mock_agent, prefix="/discord", **kwargs):
    discord = Discord(agent=mock_agent, prefix=prefix, **kwargs)
    app = FastAPI()
    app.include_router(discord.get_router())
    return app


def _post_interaction(client, payload: dict, path="/discord/interactions"):
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    signature = _sign(SIGNING_KEY, body, timestamp)

    return client.post(
        path,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature-Ed25519": signature,
            "X-Signature-Timestamp": timestamp,
        },
    )


@pytest.fixture(autouse=True)
def patch_public_key():
    with patch("agno.os.interfaces.discord.security.DISCORD_PUBLIC_KEY", PUBLIC_KEY_HEX):
        yield


class TestPingPong:
    def test_ping_returns_pong(self, mock_agent):
        app = _make_app(mock_agent)
        client = TestClient(app)
        resp = _post_interaction(client, {"type": 1})
        assert resp.status_code == 200
        assert resp.json()["type"] == 1


class TestSignatureValidation:
    def test_missing_headers_returns_401(self, mock_agent):
        app = _make_app(mock_agent)
        client = TestClient(app)
        resp = client.post(
            "/discord/interactions",
            content=b'{"type": 1}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_invalid_signature_returns_401(self, mock_agent):
        app = _make_app(mock_agent)
        client = TestClient(app)
        resp = client.post(
            "/discord/interactions",
            content=b'{"type": 1}',
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": "aa" * 64,
                "X-Signature-Timestamp": str(int(time.time())),
            },
        )
        assert resp.status_code == 401


class TestApplicationCommand:
    def test_slash_command_returns_deferred_ack(self, mock_agent):
        app = _make_app(mock_agent)
        client = TestClient(app)

        payload = {
            "type": 2,
            "id": "1234",
            "application_id": "app123",
            "token": "interaction_token",
            "guild_id": "guild1",
            "channel_id": "channel1",
            "member": {"user": {"id": "user1"}},
            "data": {
                "name": "ask",
                "options": [{"name": "message", "value": "Hello agent", "type": 3}],
            },
        }

        resp = _post_interaction(client, payload)
        assert resp.status_code == 200
        assert resp.json()["type"] == 5


class TestAllowlists:
    def test_disallowed_guild_returns_ephemeral(self, mock_agent):
        app = _make_app(mock_agent, allowed_guild_ids=["allowed_guild"])
        client = TestClient(app)

        payload = {
            "type": 2,
            "id": "1234",
            "application_id": "app123",
            "token": "tok",
            "guild_id": "wrong_guild",
            "channel_id": "ch1",
            "member": {"user": {"id": "user1"}},
            "data": {"name": "ask", "options": []},
        }

        resp = _post_interaction(client, payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == 4
        assert data["data"]["flags"] == 64

    def test_allowed_guild_passes(self, mock_agent):
        app = _make_app(mock_agent, allowed_guild_ids=["allowed_guild"])
        client = TestClient(app)

        payload = {
            "type": 2,
            "id": "1234",
            "application_id": "app123",
            "token": "tok",
            "guild_id": "allowed_guild",
            "channel_id": "ch1",
            "member": {"user": {"id": "user1"}},
            "data": {"name": "ask", "options": [{"name": "message", "value": "hi", "type": 3}]},
        }

        resp = _post_interaction(client, payload)
        assert resp.status_code == 200
        assert resp.json()["type"] == 5


class TestSessionId:
    def test_dm_session_id(self):
        data = {"channel_id": "ch123", "user": {"id": "user1"}}
        channel_id = data.get("channel_id", "")
        guild_id = data.get("guild_id")

        if not guild_id:
            session_id = f"dc:dm:{channel_id}"
        else:
            user_id = data.get("user", {}).get("id", "")
            session_id = f"dc:channel:{channel_id}:user:{user_id}"

        assert session_id == "dc:dm:ch123"

    def test_guild_channel_session_id(self):
        channel_id = "ch456"
        guild_id = "guild1"
        user_id = "user1"
        session_id = f"dc:channel:{channel_id}:user:{user_id}"
        assert session_id == "dc:channel:ch456:user:user1"

    def test_thread_session_id(self):
        channel_id = "thread789"
        session_id = f"dc:thread:{channel_id}"
        assert session_id == "dc:thread:thread789"


class TestMessageBatching:
    def test_short_message_no_split(self):
        msg = "Hello world"
        max_chars = 1900
        if len(msg) <= max_chars:
            result = [msg]
        else:
            batches = [msg[i : i + max_chars] for i in range(0, len(msg), max_chars)]
            result = [f"[{i}/{len(batches)}] {batch}" for i, batch in enumerate(batches, 1)]
        assert result == ["Hello world"]

    def test_long_message_splits(self):
        msg = "x" * 4000
        max_chars = 1900
        if len(msg) <= max_chars:
            result = [msg]
        else:
            batches = [msg[i : i + max_chars] for i in range(0, len(msg), max_chars)]
            result = [f"[{i}/{len(batches)}] {batch}" for i, batch in enumerate(batches, 1)]

        assert len(result) == 3
        assert result[0].startswith("[1/3]")
        assert result[1].startswith("[2/3]")
        assert result[2].startswith("[3/3]")


class TestDiscordClass:
    def test_requires_agent_team_or_workflow(self):
        with pytest.raises(ValueError, match="Discord requires an agent, team or workflow"):
            Discord()

    def test_default_values(self, mock_agent):
        discord = Discord(agent=mock_agent)
        assert discord.type == "discord"
        assert discord.prefix == "/discord"
        assert discord.tags == ["Discord"]
        assert discord.show_reasoning is True
        assert discord.max_message_chars == 1900

    def test_custom_values(self, mock_agent):
        discord = Discord(
            agent=mock_agent,
            prefix="/bot",
            show_reasoning=False,
            max_message_chars=1500,
            allowed_guild_ids=["g1"],
        )
        assert discord.prefix == "/bot"
        assert discord.show_reasoning is False
        assert discord.max_message_chars == 1500
        assert discord.allowed_guild_ids == ["g1"]

    def test_get_router_returns_api_router(self, mock_agent):
        discord = Discord(agent=mock_agent)
        router = discord.get_router()
        assert router is not None
        route_paths = [r.path for r in router.routes]
        assert "/discord/interactions" in route_paths


def _make_agent_response(**overrides):
    defaults = dict(
        status="OK",
        content="Hello from agent",
        reasoning_content=None,
        is_paused=False,
        images=None,
        files=None,
        videos=None,
        audio=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_mock_discord_tools():
    mock_dt = MagicMock()
    mock_dt.edit_webhook_message = AsyncMock()
    mock_dt.send_webhook_followup = AsyncMock()
    mock_dt.download_attachment_async = AsyncMock(return_value=b"file-bytes")
    mock_dt.upload_webhook_file = AsyncMock()
    return mock_dt


def _slash_command_payload(**overrides):
    payload = {
        "type": 2,
        "id": "1234",
        "application_id": "app123",
        "token": "interaction_token",
        "guild_id": "guild1",
        "channel_id": "channel1",
        "member": {"user": {"id": "user1"}},
        "data": {
            "name": "ask",
            "options": [{"name": "message", "value": "Hello", "type": 3}],
        },
    }
    payload.update(overrides)
    return payload


class TestBackgroundDelegation:
    """Verify router delegates API calls to DiscordTools (zero httpx in router)."""

    def test_command_edits_original_with_response(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_agent_response())
        mock_dt = _make_mock_discord_tools()

        with patch("agno.os.interfaces.discord.router.DiscordTools", return_value=mock_dt):
            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            resp = _post_interaction(client, _slash_command_payload())

        assert resp.status_code == 200
        mock_dt.edit_webhook_message.assert_called_once()
        args = mock_dt.edit_webhook_message.call_args
        assert args[0][0] == "app123"
        assert args[0][1] == "interaction_token"
        assert "Hello from agent" in args[0][2]

    def test_long_response_splits_into_followups(self, mock_agent):
        long_text = "x" * 4000
        mock_agent.arun = AsyncMock(return_value=_make_agent_response(content=long_text))
        mock_dt = _make_mock_discord_tools()

        with patch("agno.os.interfaces.discord.router.DiscordTools", return_value=mock_dt):
            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, _slash_command_payload())

        # First batch → edit_webhook_message, remaining → send_webhook_followup
        mock_dt.edit_webhook_message.assert_called_once()
        assert mock_dt.send_webhook_followup.call_count >= 1

    def test_hitl_sends_buttons_via_edit(self, mock_agent):
        mock_tool = MagicMock()
        mock_tool.tool_name = "dangerous_tool"
        response = _make_agent_response(
            is_paused=True,
            run_id="run123",
            tools_requiring_confirmation=[mock_tool],
        )
        mock_agent.arun = AsyncMock(return_value=response)
        mock_dt = _make_mock_discord_tools()

        with patch("agno.os.interfaces.discord.router.DiscordTools", return_value=mock_dt):
            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, _slash_command_payload())

        mock_dt.edit_webhook_message.assert_called_once()
        call_kwargs = mock_dt.edit_webhook_message.call_args
        # Should include components (HITL buttons)
        assert call_kwargs.kwargs.get("components") or (len(call_kwargs[0]) >= 4 and call_kwargs[0][3] is not None)

    def test_attachment_download_delegates(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_agent_response())
        mock_dt = _make_mock_discord_tools()

        payload = _slash_command_payload()
        payload["data"]["options"].append({"name": "file", "value": "att123", "type": 11})
        payload["data"]["resolved"] = {
            "attachments": {
                "att123": {
                    "url": "https://cdn.discordapp.com/file.png",
                    "content_type": "image/png",
                    "filename": "file.png",
                    "size": 1024,
                }
            }
        }

        with patch("agno.os.interfaces.discord.router.DiscordTools", return_value=mock_dt):
            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, payload)

        mock_dt.download_attachment_async.assert_called_once_with("https://cdn.discordapp.com/file.png")

    def test_response_media_uploads_via_webhook(self, mock_agent):
        mock_image = MagicMock()
        mock_image.get_content_bytes.return_value = b"png-bytes"
        mock_image.filename = None

        response = _make_agent_response(images=[mock_image])
        mock_agent.arun = AsyncMock(return_value=response)
        mock_dt = _make_mock_discord_tools()

        with patch("agno.os.interfaces.discord.router.DiscordTools", return_value=mock_dt):
            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, _slash_command_payload())

        mock_dt.upload_webhook_file.assert_called_once()
        args = mock_dt.upload_webhook_file.call_args
        assert args[0][0] == "app123"
        assert args[0][2] == "image.png"
        assert args[0][3] == b"png-bytes"
