import json
import time
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from .conftest import (
    SIGNING_KEY,
    RecordingSession,
    make_agent_response,
    make_discord_app,
    make_slash_command,
    post_interaction,
    sign_request,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_calls(session: RecordingSession, method: str) -> list[tuple[str, str, dict]]:
    return [c for c in session.calls if c[0] == method]


def _find_calls_with(session: RecordingSession, method: str, substring: str) -> list[tuple[str, str, dict]]:
    return [c for c in session.calls if c[0] == method and substring in c[1]]


# ===========================================================================
# Class 1: TestSlashCommandFlow (P0)
# ===========================================================================


class TestSlashCommandFlow:
    def test_deferred_ack_then_edit(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response(content="Paris is the capital"))
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        resp = post_interaction(client, make_slash_command(message="What is the capital of France?"))

        assert resp.status_code == 200
        assert resp.json()["type"] == 5  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE

        # Background task should have edited the original with the response
        patches = _get_calls(recording_session, "PATCH")
        assert len(patches) >= 1
        assert "@original" in patches[0][1]
        assert "Paris is the capital" in patches[0][2]["json"]["content"]

    def test_correct_session_id_passed(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command(channel_id="ch99", user_id="u42", guild_id="g1"))

        mock_agent.arun.assert_called_once()
        kwargs = mock_agent.arun.call_args.kwargs
        assert kwargs["session_id"] == "dc:channel:ch99:user:u42"

    def test_user_id_extracted_from_member(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command(user_id="user_abc"))

        kwargs = mock_agent.arun.call_args.kwargs
        assert kwargs["user_id"] == "user_abc"

    def test_missing_message_option(self, mock_agent, recording_session):
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        payload = make_slash_command()
        payload["data"]["options"] = []  # no message option
        post_interaction(client, payload)

        mock_agent.arun.assert_not_called()
        # "Please provide a message" sent via webhook
        posts = _get_calls(recording_session, "POST")
        assert any("Please provide a message" in str(c[2]) for c in posts)

    def test_agent_error_sends_apology(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(side_effect=RuntimeError("Model API down"))
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        resp = post_interaction(client, make_slash_command())
        assert resp.status_code == 200

        posts = _get_calls(recording_session, "POST")
        assert any("error processing" in str(c[2]).lower() for c in posts)

    def test_empty_response_handled(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=None)
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command())

        posts = _get_calls(recording_session, "POST")
        assert any("No response generated" in str(c[2]) for c in posts)


# ===========================================================================
# Class 2: TestSignatureVerification (P0)
# ===========================================================================


class TestSignatureVerification:
    def test_valid_signature_accepted(self, mock_agent, recording_session):
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        resp = post_interaction(client, {"type": 1})
        assert resp.status_code == 200
        assert resp.json()["type"] == 1  # PONG

    def test_missing_headers_rejected(self, mock_agent, recording_session):
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/discord/interactions",
            content=b'{"type": 1}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_tampered_body_rejected(self, mock_agent, recording_session):
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        payload = {"type": 1}
        _, headers = sign_request(payload)
        # Tamper with body after signing
        tampered_body = json.dumps({"type": 2}).encode()
        resp = client.post("/discord/interactions", content=tampered_body, headers=headers)
        assert resp.status_code == 401

    def test_stale_timestamp_rejected(self, mock_agent, recording_session):
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        payload = {"type": 1}
        body = json.dumps(payload).encode()
        # Timestamp 6 minutes ago (> 5 minute window)
        old_timestamp = str(int(time.time()) - 360)
        message = old_timestamp.encode() + body
        signature = SIGNING_KEY.sign(message).signature.hex()

        resp = client.post(
            "/discord/interactions",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": signature,
                "X-Signature-Timestamp": old_timestamp,
            },
        )
        assert resp.status_code == 401


# ===========================================================================
# Class 3: TestAllowlists (P1)
# ===========================================================================


class TestAllowlists:
    def test_disallowed_guild_ephemeral(self, mock_agent, recording_session):
        app = make_discord_app(mock_agent, allowed_guild_ids=["allowed"])
        client = TestClient(app, raise_server_exceptions=False)

        resp = post_interaction(client, make_slash_command(guild_id="wrong"))
        data = resp.json()
        assert data["type"] == 4
        assert data["data"]["flags"] == 64
        assert "not enabled" in data["data"]["content"]

    def test_allowed_guild_proceeds(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())
        app = make_discord_app(mock_agent, allowed_guild_ids=["guild1"])
        client = TestClient(app, raise_server_exceptions=False)

        resp = post_interaction(client, make_slash_command(guild_id="guild1"))
        assert resp.json()["type"] == 5

    def test_disallowed_channel_ephemeral(self, mock_agent, recording_session):
        app = make_discord_app(mock_agent, allowed_channel_ids=["allowed_ch"])
        client = TestClient(app, raise_server_exceptions=False)

        resp = post_interaction(client, make_slash_command(channel_id="wrong_ch"))
        data = resp.json()
        assert data["type"] == 4
        assert data["data"]["flags"] == 64
        assert "not enabled" in data["data"]["content"]

    def test_no_allowlists_allows_all(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        resp = post_interaction(client, make_slash_command(guild_id="any", channel_id="any"))
        assert resp.json()["type"] == 5


# ===========================================================================
# Class 4: TestSessionBuilding (P1)
# ===========================================================================


class TestSessionBuilding:
    def test_dm_session(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        payload = make_slash_command(guild_id="", channel_id="dm_ch")
        payload.pop("guild_id", None)
        # DMs have user directly, not member
        payload.pop("member", None)
        payload["user"] = {"id": "dm_user"}

        post_interaction(client, payload)
        kwargs = mock_agent.arun.call_args.kwargs
        assert kwargs["session_id"] == "dc:dm:dm_ch"

    def test_thread_session(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        payload = make_slash_command(channel_id="thread_ch")
        payload["channel"] = {"id": "thread_ch", "type": 11}  # PUBLIC_THREAD

        post_interaction(client, payload)
        kwargs = mock_agent.arun.call_args.kwargs
        assert kwargs["session_id"] == "dc:thread:thread_ch"

    def test_guild_channel_session(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command(channel_id="ch1", user_id="u1", guild_id="g1"))
        kwargs = mock_agent.arun.call_args.kwargs
        assert kwargs["session_id"] == "dc:channel:ch1:user:u1"


# ===========================================================================
# Class 5: TestAttachmentHandling (P1)
# ===========================================================================


class TestAttachmentHandling:
    def test_image_attachment(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        attachment = {
            "id": "att1",
            "url": "https://cdn.discordapp.com/test.png",
            "content_type": "image/png",
            "filename": "test.png",
            "size": 1024,
        }
        post_interaction(client, make_slash_command(attachment=attachment))

        kwargs = mock_agent.arun.call_args.kwargs
        assert kwargs["images"] is not None
        assert len(kwargs["images"]) == 1

        # Verify aiohttp GET was called to download the attachment
        gets = _get_calls(recording_session, "GET")
        assert len(gets) == 1
        assert "cdn.discordapp.com" in gets[0][1]

    def test_audio_attachment(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())

        # Recording session returns audio bytes
        recording_session._get_response_factory = lambda url, kwargs: recording_session._make_response(
            content_length=2048, chunk_data=b"audio-data"
        )

        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        attachment = {
            "id": "att2",
            "url": "https://cdn.discordapp.com/test.mp3",
            "content_type": "audio/mpeg",
            "filename": "test.mp3",
            "size": 2048,
        }
        post_interaction(client, make_slash_command(attachment=attachment))

        kwargs = mock_agent.arun.call_args.kwargs
        assert kwargs["audio"] is not None
        assert len(kwargs["audio"]) == 1

    def test_oversized_attachment_skipped(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        attachment = {
            "id": "att3",
            "url": "https://cdn.discordapp.com/huge.bin",
            "content_type": "image/png",
            "filename": "huge.png",
            "size": 30 * 1024 * 1024,  # 30MB — exceeds 25MB limit
        }
        post_interaction(client, make_slash_command(attachment=attachment))

        # Agent called without images (oversized attachment skipped at metadata level)
        kwargs = mock_agent.arun.call_args.kwargs
        assert kwargs["images"] is None

    def test_download_failure_graceful(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response())

        def _failing_get(url, kwargs):
            raise ConnectionError("CDN unavailable")

        recording_session._get_response_factory = _failing_get
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        attachment = {
            "id": "att4",
            "url": "https://cdn.discordapp.com/fail.png",
            "content_type": "image/png",
            "filename": "fail.png",
            "size": 1024,
        }
        post_interaction(client, make_slash_command(attachment=attachment))

        # Agent still called, just without the failed attachment
        mock_agent.arun.assert_called_once()
        kwargs = mock_agent.arun.call_args.kwargs
        assert kwargs["images"] is None


# ===========================================================================
# Class 6: TestMediaUpload (P1)
# ===========================================================================


class TestMediaUpload:
    def test_response_image_uploaded(self, mock_agent, recording_session):
        mock_image = MagicMock()
        mock_image.get_content_bytes.return_value = b"png-bytes"
        mock_image.filename = None
        mock_agent.arun = AsyncMock(return_value=make_agent_response(images=[mock_image]))

        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)
        post_interaction(client, make_slash_command())

        # Image uploaded via POST to webhooks endpoint with form data
        uploads = _find_calls_with(recording_session, "POST", "/webhooks/")
        assert len(uploads) >= 1
        # Should have 'data' kwarg (FormData) for file upload
        upload_call = [c for c in uploads if "data" in c[2]]
        assert len(upload_call) >= 1

    def test_multiple_media_types(self, mock_agent, recording_session):
        mock_image = MagicMock()
        mock_image.get_content_bytes.return_value = b"img"
        mock_image.filename = "photo.png"

        mock_file = MagicMock()
        mock_file.get_content_bytes.return_value = b"doc"
        mock_file.filename = "report.pdf"

        mock_agent.arun = AsyncMock(return_value=make_agent_response(images=[mock_image], files=[mock_file]))
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)
        post_interaction(client, make_slash_command())

        # Both media items uploaded via POST
        uploads = [c for c in _get_calls(recording_session, "POST") if "data" in c[2]]
        assert len(uploads) >= 2


# ===========================================================================
# Class 7: TestLongMessageSplitting (P1)
# ===========================================================================


class TestLongMessageSplitting:
    def test_short_message_single_edit(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response(content="Short"))
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command())

        patches = _get_calls(recording_session, "PATCH")
        assert len(patches) == 1
        assert "Short" in patches[0][2]["json"]["content"]
        # No follow-up POSTs for content (only for the edit)
        content_posts = [
            c for c in _get_calls(recording_session, "POST") if "json" in c[2] and "content" in c[2].get("json", {})
        ]
        assert len(content_posts) == 0

    def test_long_message_split(self, mock_agent, recording_session):
        long_text = "x" * 4000
        mock_agent.arun = AsyncMock(return_value=make_agent_response(content=long_text))
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command())

        # First batch edits original, remaining as follow-up POSTs
        patches = _get_calls(recording_session, "PATCH")
        assert len(patches) == 1
        assert "[1/" in patches[0][2]["json"]["content"]

        content_posts = [c for c in _get_calls(recording_session, "POST") if "json" in c[2]]
        assert len(content_posts) >= 1


# ===========================================================================
# Class 8: TestReasoningContent (P1)
# ===========================================================================


class TestReasoningContent:
    def test_reasoning_shown_then_content(self, mock_agent, recording_session):
        response = make_agent_response(
            content="The answer is 42",
            reasoning_content="Let me think step by step...",
        )
        mock_agent.arun = AsyncMock(return_value=response)
        app = make_discord_app(mock_agent, show_reasoning=True)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command())

        # Reasoning sent as italics via PATCH (edit original)
        patches = _get_calls(recording_session, "PATCH")
        assert len(patches) == 1
        assert "*Let me think step by step...*" in patches[0][2]["json"]["content"]

        # Content sent as POST (follow-up)
        content_posts = [c for c in _get_calls(recording_session, "POST") if "json" in c[2]]
        assert any("The answer is 42" in str(c[2]) for c in content_posts)

    def test_reasoning_hidden(self, mock_agent, recording_session):
        response = make_agent_response(
            content="The answer is 42",
            reasoning_content="Hidden reasoning",
        )
        mock_agent.arun = AsyncMock(return_value=response)
        app = make_discord_app(mock_agent, show_reasoning=False)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command())

        patches = _get_calls(recording_session, "PATCH")
        assert len(patches) == 1
        # Content directly in the edit, no reasoning
        assert "The answer is 42" in patches[0][2]["json"]["content"]
        assert "Hidden reasoning" not in patches[0][2]["json"]["content"]


# ===========================================================================
# Class 9: TestErrorStatus (P0)
# ===========================================================================


class TestErrorStatus:
    def test_error_status_response(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_agent_response(status="ERROR", content="Bad request"))
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command())

        posts = _get_calls(recording_session, "POST")
        assert any("error processing" in str(c[2]).lower() for c in posts)

    def test_exception_no_crash(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(side_effect=ValueError("Unexpected"))
        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        resp = post_interaction(client, make_slash_command())
        assert resp.status_code == 200  # Deferred ACK still returned

        # Error message sent via webhook, server did not crash
        posts = _get_calls(recording_session, "POST")
        assert any("error processing" in str(c[2]).lower() for c in posts)
