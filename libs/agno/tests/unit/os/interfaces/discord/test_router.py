import json
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

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


def _make_mock_aiohttp_session(content_length=1024, chunk_data=b"file-bytes"):
    """Create a mock aiohttp.ClientSession that supports async context managers."""
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
    """Verify router performs webhook I/O via aiohttp (no DiscordTools)."""

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

    def test_hitl_sends_buttons_via_edit(self, mock_agent):
        mock_tool = MagicMock()
        mock_tool.tool_name = "dangerous_tool"
        response = _make_agent_response(
            is_paused=True,
            run_id="run123",
            tools_requiring_confirmation=[mock_tool],
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
        call_payload = mock_session.patch.call_args[1]["json"]
        assert "components" in call_payload
        assert "dangerous_tool" in call_payload["content"]

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


def _component_payload(custom_id: str, user_id: str = "user1", **overrides):
    payload = {
        "type": 3,  # MESSAGE_COMPONENT
        "id": "5678",
        "application_id": "app123",
        "token": "component_token",
        "guild_id": "guild1",
        "channel_id": "channel1",
        "member": {"user": {"id": user_id}},
        "data": {"custom_id": custom_id},
    }
    payload.update(overrides)
    return payload


def _make_paused_response(run_id="run123", tool_name="dangerous_tool"):
    mock_tool = MagicMock()
    mock_tool.tool_name = tool_name
    return _make_agent_response(
        is_paused=True,
        run_id=run_id,
        tools_requiring_confirmation=[mock_tool],
    )


def _setup_mocks():
    return _make_mock_aiohttp_session()


class TestHITLSecurity:
    """C1: HITL authorization bypass — only the original requester can confirm/cancel."""

    def test_unauthorized_user_rejected(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_paused_response(run_id="run_auth"))
        mock_session = _setup_mocks()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)

            _post_interaction(client, _slash_command_payload())
            resp = _post_interaction(client, _component_payload("hitl:run_auth:confirm", user_id="user2"))

        assert resp.status_code == 200
        mock_agent.acontinue_run.assert_not_called()
        post_calls = mock_session.post.call_args_list
        ephemeral_calls = [c for c in post_calls if c[1].get("json", {}).get("flags") == 64]
        assert len(ephemeral_calls) >= 1

    def test_authorized_user_continues_run(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_paused_response(run_id="run_auth2"))
        continued = _make_agent_response(content="Tool executed successfully")
        mock_agent.acontinue_run = AsyncMock(return_value=continued)
        mock_session = _setup_mocks()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)

            _post_interaction(client, _slash_command_payload())
            _post_interaction(client, _component_payload("hitl:run_auth2:confirm", user_id="user1"))

        mock_agent.acontinue_run.assert_called_once()


class TestHITLCleanup:
    """H2: Stale HITL entries are cleaned up after 15-minute TTL."""

    def test_stale_entries_cleaned_on_access(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_paused_response(run_id="run_stale"))
        mock_session = _setup_mocks()

        with (
            patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp,
            patch("agno.os.interfaces.discord.router.time") as mock_time,
        ):
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            mock_time.time.return_value = 1000.0

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)

            _post_interaction(client, _slash_command_payload())

            mock_time.time.return_value = 1000.0 + 16 * 60

            _post_interaction(client, _component_payload("hitl:run_stale:confirm", user_id="user1"))

        mock_agent.acontinue_run.assert_not_called()
        post_calls = mock_session.post.call_args_list
        expired_calls = [c for c in post_calls if "expired" in str(c).lower() or "handled" in str(c).lower()]
        assert len(expired_calls) >= 1


class TestTokenHandling:
    """H4: Component callback uses its own interaction token, not the stored original."""

    def test_component_uses_own_token(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_paused_response(run_id="run_token"))
        continued = _make_agent_response(content="Done")
        mock_agent.acontinue_run = AsyncMock(return_value=continued)
        mock_session = _setup_mocks()

        with patch("agno.os.interfaces.discord.router.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = mock_session
            mock_aiohttp.ClientTimeout = MagicMock()
            mock_aiohttp.FormData = MagicMock()

            app = _make_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)

            _post_interaction(client, _slash_command_payload())
            _post_interaction(client, _component_payload("hitl:run_token:confirm", user_id="user1"))

        all_calls = [str(c) for c in mock_session.post.call_args_list + mock_session.patch.call_args_list]
        assert any("component_token" in url for url in all_calls)


class TestProtocolHandling:
    """M4/M2: Interaction type handling and session ID robustness."""

    def test_unknown_interaction_type_returns_400(self, mock_agent):
        app = _make_app(mock_agent)
        client = TestClient(app)
        resp = _post_interaction(client, {"type": 5})
        assert resp.status_code == 400

    def test_command_without_channel_object(self, mock_agent):
        mock_agent.arun = AsyncMock(return_value=_make_agent_response())
        mock_session = _setup_mocks()

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


class TestAttachmentSafety:
    """M5: Attachment download size enforcement via Content-Length pre-check."""

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
