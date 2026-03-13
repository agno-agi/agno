import json
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.os.interfaces.discord.discord import Discord


# Generate an Ed25519 keypair for signing test payloads
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
    return agent


# Build a FastAPI TestClient with a Discord-wired router
def _make_app(mock_agent, prefix="/discord", **kwargs):
    discord = Discord(agent=mock_agent, prefix=prefix, **kwargs)
    app = FastAPI()
    app.include_router(discord.get_router())
    return app


# Sign a payload and POST to the interactions endpoint
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


# Discord PING/PONG verification handshake
class TestPingPong:
    def test_ping_returns_pong(self, mock_agent):
        app = _make_app(mock_agent)
        client = TestClient(app)
        resp = _post_interaction(client, {"type": 1})
        assert resp.status_code == 200
        assert resp.json()["type"] == 1


# Ed25519 signature validation: missing headers, bad signature
class TestSignatureValidation:
    def test_missing_headers_returns_400(self, mock_agent):
        app = _make_app(mock_agent)
        client = TestClient(app)
        resp = client.post(
            "/discord/interactions",
            content=b'{"type": 1}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_invalid_signature_returns_403(self, mock_agent):
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
        assert resp.status_code == 403


# Slash command returns deferred ACK (type 5)
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


# Guild and channel allowlist enforcement (ephemeral rejection)
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

    def test_disallowed_channel_returns_ephemeral(self, mock_agent):
        app = _make_app(mock_agent, allowed_channel_ids=["allowed_ch"])
        client = TestClient(app)

        payload = {
            "type": 2,
            "id": "1234",
            "application_id": "app123",
            "token": "tok",
            "guild_id": "guild1",
            "channel_id": "wrong_ch",
            "member": {"user": {"id": "user1"}},
            "data": {"name": "ask", "options": []},
        }

        resp = _post_interaction(client, payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == 4
        assert data["data"]["flags"] == 64

    def test_no_allowlists_allows_all(self, mock_agent):
        app = _make_app(mock_agent)
        client = TestClient(app)

        resp = _post_interaction(client, _slash_command_payload())
        assert resp.status_code == 200
        assert resp.json()["type"] == 5


# Session ID construction via _build_session_id: DM, guild channel, thread
class TestSessionId:
    def test_dm_session_id(self):
        from agno.os.interfaces.discord.router import _build_session_id

        data = {"channel_id": "ch123", "user": {"id": "user1"}}
        assert _build_session_id(data) == "dc:dm:ch123"

    def test_guild_channel_session_id(self):
        from agno.os.interfaces.discord.router import _build_session_id

        data = {"channel_id": "ch456", "guild_id": "g1", "member": {"user": {"id": "user1"}}}
        assert _build_session_id(data) == "dc:channel:ch456:user:user1"

    def test_thread_session_id(self):
        from agno.os.interfaces.discord.router import _build_session_id

        data = {"channel_id": "thread789", "guild_id": "g1", "channel": {"type": 11}}
        assert _build_session_id(data) == "dc:thread:thread789"


# Message splitting via split_message() with [1/N] prefixes
class TestMessageBatching:
    def test_short_message_no_split(self):
        from agno.os.interfaces.discord.processing import split_message

        assert split_message("Hello world") == ["Hello world"]

    def test_long_message_splits(self):
        from agno.os.interfaces.discord.processing import split_message

        result = split_message("x" * 4000)
        assert len(result) == 3
        assert result[0].startswith("[1/3]")
        assert result[1].startswith("[2/3]")
        assert result[2].startswith("[3/3]")


# Discord class instantiation and configuration
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


# Construct a mock arun() response with sensible defaults
def _make_agent_response(**overrides):
    defaults = dict(
        status="OK",
        content="Hello from agent",
        reasoning_content=None,
        images=None,
        files=None,
        videos=None,
        audio=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_mock_aiohttp_session(content_length=1024, chunk_data=b"file-bytes"):
    mock_session = MagicMock()
    mock_session.closed = False

    # Mock for PATCH (used by _edit_original)
    mock_patch_resp = AsyncMock()
    mock_patch_resp.raise_for_status = Mock()
    mock_patch_ctx = AsyncMock()
    mock_patch_ctx.__aenter__.return_value = mock_patch_resp
    mock_patch_ctx.__aexit__.return_value = False
    mock_session.patch.return_value = mock_patch_ctx

    # Mock for POST (used by _send_webhook and _upload_webhook_file)
    mock_post_resp = AsyncMock()
    mock_post_resp.raise_for_status = Mock()
    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__.return_value = mock_post_resp
    mock_post_ctx.__aexit__.return_value = False
    mock_session.post.return_value = mock_post_ctx

    # Mock for GET (used by _download_bytes with iter_chunked)
    mock_get_resp = AsyncMock()
    mock_get_resp.raise_for_status = Mock()
    mock_get_resp.content_length = content_length

    async def _iter_chunked(size):
        yield chunk_data

    mock_content = MagicMock()
    mock_content.iter_chunked = _iter_chunked
    mock_get_resp.content = mock_content

    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_get_resp
    mock_get_ctx.__aexit__.return_value = False
    mock_session.get.return_value = mock_get_ctx

    return mock_session


# Build a minimal slash command interaction payload with overridable fields
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
    def test_command_edits_original_with_response(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_agent_response())
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            resp = _post_interaction(client, _slash_command_payload())

        assert resp.status_code == 200
        mock_session.patch.assert_called_once()
        call_args = mock_session.patch.call_args
        assert "@original" in call_args[0][0]
        assert "Hello from agent" in call_args[1]["json"]["content"]

    def test_long_response_splits_into_followups(self, mock_agent):
        long_text = "x" * 4000
        mock_agent.arun = AsyncMock(return_value=_make_agent_response(content=long_text))
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, _slash_command_payload())

        mock_session.patch.assert_called_once()
        assert mock_session.post.call_count >= 1

    def test_attachment_download_via_aiohttp(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_agent_response())
        mock_session = _make_mock_aiohttp_session()

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

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, payload)

        mock_session.get.assert_called_once()
        call_args = mock_session.get.call_args
        assert "cdn.discordapp.com" in call_args[0][0]

    def test_response_media_uploads_via_webhook(self, mock_agent):
        mock_image = MagicMock()
        mock_image.get_content_bytes.return_value = b"png-bytes"
        mock_image.filename = None

        response = _make_agent_response(images=[mock_image])
        mock_agent.arun = AsyncMock(return_value=response)
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, _slash_command_payload())

        assert mock_session.post.call_count >= 1
        post_url = mock_session.post.call_args[0][0]
        assert "/webhooks/" in post_url

    def test_audio_attachment_routed_correctly(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_agent_response())
        mock_session = _make_mock_aiohttp_session()

        payload = _slash_command_payload()
        payload["data"]["options"].append({"name": "file", "value": "att123", "type": 11})
        payload["data"]["resolved"] = {
            "attachments": {
                "att123": {
                    "url": "https://cdn.discordapp.com/test.mp3",
                    "content_type": "audio/mpeg",
                    "filename": "test.mp3",
                    "size": 2048,
                }
            }
        }

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, payload)

        mock_agent.arun.assert_called_once()
        call_kwargs = mock_agent.arun.call_args
        assert call_kwargs.kwargs.get("audio") is not None
        assert len(call_kwargs.kwargs["audio"]) == 1

    def test_multiple_media_types_uploaded(self, mock_agent):
        mock_image = MagicMock()
        mock_image.get_content_bytes.return_value = b"img"
        mock_image.filename = "photo.png"

        mock_file = MagicMock()
        mock_file.get_content_bytes.return_value = b"doc"
        mock_file.filename = "report.pdf"

        response = _make_agent_response(images=[mock_image], files=[mock_file])
        mock_agent.arun = AsyncMock(return_value=response)
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, _slash_command_payload())

        assert mock_session.post.call_count >= 2

    def test_error_sends_error_message(self, mock_agent):
        mock_agent.arun = AsyncMock(side_effect=Exception("Agent crashed"))
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            resp = _post_interaction(client, _slash_command_payload())

        assert resp.status_code == 200
        assert mock_session.post.call_count >= 1

    def test_reasoning_content_displayed(self, mock_agent):
        response = _make_agent_response(
            content="Final answer",
            reasoning_content="Let me think about this...",
        )
        mock_agent.arun = AsyncMock(return_value=response)
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, _slash_command_payload())

        mock_session.patch.assert_called_once()
        patch_payload = mock_session.patch.call_args[1]["json"]["content"]
        assert "Let me think about this..." in patch_payload
        assert mock_session.post.call_count >= 1


class TestProtocolHandling:
    def test_unknown_interaction_type_returns_400(self, mock_agent):
        app = _make_app(mock_agent)
        client = TestClient(app)
        resp = _post_interaction(client, {"type": 5})
        assert resp.status_code == 400

    def test_command_without_channel_object(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_agent_response())
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            payload = _slash_command_payload()
            assert "channel" not in payload

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            resp = _post_interaction(client, payload)

        assert resp.status_code == 200
        mock_agent.arun.assert_called_once()
        call_kwargs = mock_agent.arun.call_args
        session_id = call_kwargs.kwargs.get("session_id", "")
        assert session_id.startswith("dc:channel:")

    def test_missing_message_option_sends_error(self, mock_agent):
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            payload = _slash_command_payload()
            payload["data"]["options"] = []

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            resp = _post_interaction(client, payload)

        assert resp.status_code == 200
        mock_agent.arun.assert_not_called()
        mock_session.patch.assert_called_once()
        patch_url = mock_session.patch.call_args[0][0]
        assert "@original" in patch_url


class TestAttachmentSafety:
    def test_oversized_content_length_skips_download(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_agent_response())
        mock_session = _make_mock_aiohttp_session(content_length=30 * 1024 * 1024)

        payload = _slash_command_payload()
        payload["data"]["options"].append({"name": "file", "value": "att123", "type": 11})
        payload["data"]["resolved"] = {
            "attachments": {
                "att123": {
                    "url": "https://cdn.discordapp.com/file.bin",
                    "content_type": "image/png",
                    "filename": "large.png",
                    "size": 1024,
                }
            }
        }

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, payload)

        mock_agent.arun.assert_called_once()
        call_kwargs = mock_agent.arun.call_args
        assert call_kwargs.kwargs.get("images") is None

    def test_download_failure_skips_attachment(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_agent_response())
        mock_session = _make_mock_aiohttp_session()

        mock_get_ctx = AsyncMock()
        mock_get_ctx.__aenter__.side_effect = ConnectionError("CDN unavailable")
        mock_get_ctx.__aexit__.return_value = False
        mock_session.get.return_value = mock_get_ctx

        payload = _slash_command_payload()
        payload["data"]["options"].append({"name": "file", "value": "att123", "type": 11})
        payload["data"]["resolved"] = {
            "attachments": {
                "att123": {
                    "url": "https://cdn.discordapp.com/fail.png",
                    "content_type": "image/png",
                    "filename": "fail.png",
                    "size": 1024,
                }
            }
        }

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)
            _post_interaction(client, payload)

        mock_agent.arun.assert_called_once()
        call_kwargs = mock_agent.arun.call_args
        assert call_kwargs.kwargs.get("images") is None


class TestEntityDelegation:
    def test_team_entity_receives_command(self):
        mock_team = MagicMock()
        mock_team.arun = AsyncMock(return_value=_make_agent_response(content="Team response"))
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            discord = Discord(team=mock_team)
            app = FastAPI()
            app.include_router(discord.get_router())
            client = TestClient(app, raise_server_exceptions=False)
            resp = _post_interaction(client, _slash_command_payload())

        assert resp.status_code == 200
        assert resp.json()["type"] == 5
        mock_team.arun.assert_called_once()

    def test_workflow_entity_receives_command(self):
        mock_workflow = MagicMock()
        mock_workflow.arun = AsyncMock(return_value=_make_agent_response(content="Workflow response"))
        mock_session = _make_mock_aiohttp_session()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            discord = Discord(workflow=mock_workflow)
            app = FastAPI()
            app.include_router(discord.get_router())
            client = TestClient(app, raise_server_exceptions=False)
            resp = _post_interaction(client, _slash_command_payload())

        assert resp.status_code == 200
        assert resp.json()["type"] == 5
        mock_workflow.arun.assert_called_once()
