import asyncio
import os
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

# Default mode (enable_encryption=False): user_id is the raw phone number
_RAW_SENDER = "sender_phone"


def _build_app(agent_mock: Mock) -> FastAPI:
    from agno.os.interfaces.whatsapp.router import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(router, agent=agent_mock)
    app.include_router(router)
    return app


def _make_agent_mock(db=None):
    agent_mock = AsyncMock()
    agent_mock.name = "test_agent"
    agent_mock.id = "test_agent"
    agent_mock.db = db
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK",
            content="done",
            reasoning_content=None,
            images=None,
            files=None,
            videos=None,
            audio=None,
            response_audio=None,
        )
    )
    return agent_mock


def _make_mock_db():
    from agno.db.base import BaseDb

    db = Mock(spec=BaseDb)
    # Track upserted sessions so get_sessions can return them
    db._sessions = []

    def _upsert(session, **kwargs):
        db._sessions.append(session)
        return session

    def _get_sessions(**kwargs):
        user_id = kwargs.get("user_id")
        matches = [s for s in db._sessions if s.user_id == user_id]
        # Sort newest first (highest created_at)
        matches.sort(key=lambda s: s.created_at or 0, reverse=True)
        limit = kwargs.get("limit")
        if limit:
            matches = matches[:limit]
        return matches

    db.upsert_session = Mock(side_effect=_upsert)
    db.get_sessions = Mock(side_effect=_get_sessions)
    return db


def _make_whatsapp_webhook(message_type: str, **kwargs) -> dict:
    msg = {
        "from": "sender_phone",
        "id": "wamid.test123",
        "timestamp": str(int(time.time())),
        "type": message_type,
        **kwargs,
    }
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "1234567890",
                                "phone_number_id": "PHONE_ID",
                            },
                            "messages": [msg],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


WHATSAPP_ENV = {
    "WHATSAPP_ACCESS_TOKEN": "test-token",
    "WHATSAPP_PHONE_NUMBER_ID": "123456",
    "WHATSAPP_VERIFY_TOKEN": "test-verify-token",
    "WHATSAPP_APP_SECRET": "test-secret",
}


async def _wait_for_agent_call(agent_mock: AsyncMock, timeout: float = 5.0):
    elapsed = 0.0
    while not agent_mock.arun.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1


async def _wait_for_mock_call(mock, timeout: float = 5.0):
    elapsed = 0.0
    while not mock.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1
    # Yield once more so the coroutine finishes any remaining sync work
    await asyncio.sleep(0)


# === Webhook Verification (GET) ===


def test_webhook_verification():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        response = client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "test-verify-token",
                "hub.challenge": "challenge_123",
            },
        )
        assert response.status_code == 200
        assert response.text == "challenge_123"


def test_webhook_verification_invalid_token():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        response = client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "challenge_123",
            },
        )
        assert response.status_code == 403


# === Webhook Signature (POST) ===


def test_webhook_signature_invalid():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=False),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "hello"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 403


# === Message Processing ===


@pytest.mark.asyncio
async def test_text_message_processing():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "hello world"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert call_args[0][0] == "hello world"
        assert call_args.kwargs["user_id"] == _RAW_SENDER
        assert call_args.kwargs["session_id"] == f"wa:test_agent:{_RAW_SENDER}"


@pytest.mark.asyncio
async def test_image_message_processing():
    from agno.media import Image

    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch(
            "agno.os.interfaces.whatsapp.router.download_event_media_async",
            new_callable=AsyncMock,
            return_value=({"images": [Image(content=b"\x89PNG")]}, []),
        ),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("image", image={"id": "media_123", "caption": "Check this"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert call_args[0][0] == "Check this"
        images = call_args.kwargs.get("images")
        assert images is not None
        assert len(images) == 1


def test_non_whatsapp_object_ignored():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = {"object": "instagram", "entry": []}
        response = client.post("/webhook", json=body)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"


# === Interactive Message Processing ===


@pytest.mark.asyncio
async def test_button_reply_processing():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook(
            "interactive",
            interactive={"type": "button_reply", "button_reply": {"id": "btn_yes", "title": "Yes"}},
        )
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert call_args[0][0] == "Yes"
        assert call_args.kwargs["user_id"] == _RAW_SENDER


@pytest.mark.asyncio
async def test_list_reply_processing():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook(
            "interactive",
            interactive={
                "type": "list_reply",
                "list_reply": {"id": "rome", "title": "Rome, Italy", "description": "Colosseum & Vatican"},
            },
        )
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert call_args[0][0] == "Rome, Italy: Colosseum & Vatican"


@pytest.mark.asyncio
async def test_list_reply_without_description():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook(
            "interactive",
            interactive={"type": "list_reply", "list_reply": {"id": "rome", "title": "Rome, Italy"}},
        )
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert call_args[0][0] == "Rome, Italy"


def test_empty_messages_no_crash():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = {
            "object": "whatsapp_business_account",
            "entry": [{"id": "123", "changes": [{"value": {"messages": []}, "field": "messages"}]}],
        }
        response = client.post("/webhook", json=body)
        assert response.status_code == 200


# === Video / Audio / Document Message Types ===


@pytest.mark.asyncio
async def test_video_message_processing():
    from agno.media import Video

    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch(
            "agno.os.interfaces.whatsapp.router.download_event_media_async",
            new_callable=AsyncMock,
            return_value=({"videos": [Video(content=b"\x00\x00\x00\x1cftypisom")]}, []),
        ),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("video", video={"id": "vid_123", "caption": "Watch this"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert call_args[0][0] == "Watch this"
        videos = call_args.kwargs.get("videos")
        assert videos is not None
        assert len(videos) == 1


@pytest.mark.asyncio
async def test_audio_message_processing():
    from agno.media import Audio

    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch(
            "agno.os.interfaces.whatsapp.router.download_event_media_async",
            new_callable=AsyncMock,
            return_value=({"audio": [Audio(content=b"\xff\xfb\x90\x00", mime_type="audio/mpeg")]}, []),
        ),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("audio", audio={"id": "aud_123"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert call_args[0][0] == ""
        audio = call_args.kwargs.get("audio")
        assert audio is not None
        assert len(audio) == 1


@pytest.mark.asyncio
async def test_document_message_processing():
    from agno.media import File

    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch(
            "agno.os.interfaces.whatsapp.router.download_event_media_async",
            new_callable=AsyncMock,
            return_value=({"files": [File(content=b"%PDF-1.4")]}, []),
        ),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("document", document={"id": "doc_123", "caption": "Review this PDF"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert call_args[0][0] == "Review this PDF"
        files = call_args.kwargs.get("files")
        assert files is not None
        assert len(files) == 1


# === Unknown Types ===


@pytest.mark.asyncio
async def test_unknown_message_type_agent_not_called():
    agent_mock = _make_agent_mock()
    done = asyncio.Event()
    original_extract = None

    def _extract_and_signal(message):
        result = original_extract(message)
        if result is None:
            done.set()
        return result

    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        from agno.os.interfaces.whatsapp.helpers import extract_message_content

        original_extract = extract_message_content
        with patch("agno.os.interfaces.whatsapp.router.extract_message_content", side_effect=_extract_and_signal):
            app = _build_app(agent_mock)
            client = TestClient(app)
            body = _make_whatsapp_webhook("sticker", sticker={"id": "sticker_123"})
            response = client.post("/webhook", json=body)
            assert response.status_code == 200

            await asyncio.wait_for(done.wait(), timeout=5.0)
            agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_interactive_type_agent_not_called():
    agent_mock = _make_agent_mock()
    done = asyncio.Event()
    original_extract = None

    def _extract_and_signal(message):
        result = original_extract(message)
        if result is None:
            done.set()
        return result

    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        from agno.os.interfaces.whatsapp.helpers import extract_message_content

        original_extract = extract_message_content
        with patch("agno.os.interfaces.whatsapp.router.extract_message_content", side_effect=_extract_and_signal):
            app = _build_app(agent_mock)
            client = TestClient(app)
            body = _make_whatsapp_webhook(
                "interactive",
                interactive={"type": "nfm_reply", "nfm_reply": {"body": "flow data"}},
            )
            response = client.post("/webhook", json=body)
            assert response.status_code == 200

            await asyncio.wait_for(done.wait(), timeout=5.0)
            agent_mock.arun.assert_not_called()


# === Error Handling ===


@pytest.mark.asyncio
async def test_agent_error_response_sends_error_message():
    agent_mock = AsyncMock()
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="ERROR",
            content="Something went wrong",
            reasoning_content=None,
            images=None,
            files=None,
            videos=None,
            audio=None,
            response_audio=None,
        )
    )
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send_text,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "trigger error"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)
        await _wait_for_mock_call(mock_send_text)

        # Verify error message was sent to user
        mock_send_text.assert_called()
        error_call = mock_send_text.call_args_list[0]
        assert "error" in error_call.kwargs.get("text", error_call[0][1] if len(error_call[0]) > 1 else "").lower()


@pytest.mark.asyncio
async def test_agent_exception_sends_fallback_error():
    agent_mock = AsyncMock()
    agent_mock.arun = AsyncMock(side_effect=RuntimeError("Agent crashed"))
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send_text,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "crash me"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_mock_call(mock_send_text)
        # Exception path sends error message to user
        mock_send_text.assert_called()


# === Webhook Verification Edge Cases ===


def test_webhook_verification_missing_verify_token_env():
    agent_mock = _make_agent_mock()
    env_without_token = {k: v for k, v in WHATSAPP_ENV.items() if k != "WHATSAPP_VERIFY_TOKEN"}
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch.dict("os.environ", env_without_token, clear=True),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        response = client.get(
            "/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "any", "hub.challenge": "c"},
        )
        assert response.status_code == 500


def test_webhook_verification_missing_challenge():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        response = client.get(
            "/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "test-verify-token"},
        )
        assert response.status_code == 400


# === attach_routes Validation ===


def test_attach_routes_no_entity_raises():
    from agno.os.interfaces.whatsapp.router import attach_routes

    router = APIRouter()
    with pytest.raises(ValueError, match="Either agent, team, or workflow"):
        attach_routes(router)


# === Status Endpoint ===


def test_status_endpoint():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        response = client.get("/status")
        assert response.status_code == 200
        assert response.json() == {"status": "available"}


# === send_user_number_to_context ===


@pytest.mark.asyncio
async def test_send_user_number_to_context():
    from agno.os.interfaces.whatsapp.router import attach_routes

    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = FastAPI()
        router = APIRouter()
        attach_routes(router, agent=agent_mock, send_user_number_to_context=True)
        app.include_router(router)

        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "hello"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        call_kwargs = agent_mock.arun.call_args.kwargs
        assert "dependencies" in call_kwargs
        deps = call_kwargs["dependencies"]
        assert deps["User's WhatsApp number"] == _RAW_SENDER
        assert "Incoming WhatsApp message ID" in deps
        assert call_kwargs["add_dependencies_to_context"] is True
        assert call_kwargs["user_id"] == _RAW_SENDER


# === Media Response: caption truncation + text fallback ===


@pytest.mark.asyncio
async def test_image_response_short_caption_no_extra_text():
    agent_mock = AsyncMock()
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK",
            content="Short caption",
            reasoning_content=None,
            images=[Mock(content=b"\x89PNG")],
            files=None,
            videos=None,
            audio=None,
            response_audio=None,
            tools=None,
        )
    )
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send_text,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.upload_and_send_media_async", new_callable=AsyncMock) as mock_upload,
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "show me an image"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)
        await _wait_for_mock_call(mock_upload)

        mock_upload.assert_called_once()
        # Text always sent as separate message (matching Telegram pattern)
        mock_send_text.assert_called_once()


@pytest.mark.asyncio
async def test_image_response_long_caption_sends_full_text():
    long_content = "x" * 1500
    agent_mock = AsyncMock()
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK",
            content=long_content,
            reasoning_content=None,
            images=[Mock(content=b"\x89PNG")],
            files=None,
            videos=None,
            audio=None,
            response_audio=None,
            tools=None,
        )
    )
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send_text,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.upload_and_send_media_async", new_callable=AsyncMock) as mock_upload,
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "show me an image"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)
        await _wait_for_mock_call(mock_upload)

        mock_upload.assert_called_once()
        # Long content — full text sent as separate message after media
        mock_send_text.assert_called_once()
        assert len(mock_send_text.call_args.kwargs["text"]) == 1500


# === Session Behavior ===


@pytest.mark.asyncio
async def test_same_phone_same_session_id():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)

        # Send two messages from same phone number
        body = _make_whatsapp_webhook("text", text={"body": "first message"})
        client.post("/webhook", json=body)
        await _wait_for_agent_call(agent_mock)

        first_call = agent_mock.arun.call_args

        agent_mock.arun.reset_mock()
        body = _make_whatsapp_webhook("text", text={"body": "second message"})
        client.post("/webhook", json=body)
        await _wait_for_agent_call(agent_mock)

        second_call = agent_mock.arun.call_args

        # Both calls get the same deterministic session_id and user_id
        assert first_call.kwargs["session_id"] == second_call.kwargs["session_id"]
        assert first_call.kwargs["user_id"] == second_call.kwargs["user_id"]
        assert first_call.kwargs["session_id"] == f"wa:test_agent:{_RAW_SENDER}"


@pytest.mark.asyncio
async def test_different_phones_different_session_ids():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)

        # Phone A
        body_a = _make_whatsapp_webhook("text", text={"body": "hello"})
        client.post("/webhook", json=body_a)
        await _wait_for_agent_call(agent_mock)
        call_a = agent_mock.arun.call_args

        # Phone B — different sender
        agent_mock.arun.reset_mock()
        body_b = _make_whatsapp_webhook("text", text={"body": "hello"})
        body_b["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "other_phone"
        client.post("/webhook", json=body_b)
        await _wait_for_agent_call(agent_mock)
        call_b = agent_mock.arun.call_args

        assert call_a.kwargs["session_id"] != call_b.kwargs["session_id"]
        assert call_a.kwargs["user_id"] != call_b.kwargs["user_id"]


@pytest.mark.asyncio
async def test_user_id_is_raw_phone_by_default():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "hi"})
        client.post("/webhook", json=body)
        await _wait_for_agent_call(agent_mock)

        call_kwargs = agent_mock.arun.call_args.kwargs
        # Default mode: raw phone used directly as user_id
        assert call_kwargs["user_id"] == "sender_phone"
        assert call_kwargs["session_id"] == "wa:test_agent:sender_phone"


# === /new Session Reset ===


@pytest.mark.asyncio
async def test_new_command_starts_fresh_session():
    mock_db = _make_mock_db()
    agent_mock = _make_agent_mock(db=mock_db)
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send_text,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)

        # First: send a normal message, capture session_id
        body = _make_whatsapp_webhook("text", text={"body": "hello"})
        client.post("/webhook", json=body)
        await _wait_for_agent_call(agent_mock)
        original_session = agent_mock.arun.call_args.kwargs["session_id"]
        assert original_session == f"wa:test_agent:{_RAW_SENDER}"

        # Second: send /new — persists new session to DB
        agent_mock.arun.reset_mock()
        mock_send_text.reset_mock()
        body = _make_whatsapp_webhook("text", text={"body": "/new"})
        client.post("/webhook", json=body)

        await _wait_for_mock_call(mock_send_text)

        # Agent should NOT be called — /new is intercepted
        agent_mock.arun.assert_not_called()
        # Session persisted to DB
        mock_db.upsert_session.assert_called_once()
        persisted = mock_db.upsert_session.call_args[0][0]
        assert persisted.user_id == _RAW_SENDER
        assert persisted.session_id.startswith(f"wa:test_agent:{_RAW_SENDER}:")
        # Confirmation sent to user
        mock_send_text.assert_called_once()
        sent_text = mock_send_text.call_args.kwargs.get(
            "text", mock_send_text.call_args[0][1] if len(mock_send_text.call_args[0]) > 1 else ""
        )
        assert "New conversation started!" in sent_text

        # Third: next message should use the NEW session_id from DB
        agent_mock.arun.reset_mock()
        body = _make_whatsapp_webhook("text", text={"body": "after reset"})
        client.post("/webhook", json=body)
        await _wait_for_agent_call(agent_mock)
        new_session = agent_mock.arun.call_args.kwargs["session_id"]

        assert new_session != original_session
        # /new sessions scoped by entity_id for multi-bot isolation
        assert new_session.startswith(f"wa:test_agent:{_RAW_SENDER}:")
        # user_id stays the same — memories persist
        assert agent_mock.arun.call_args.kwargs["user_id"] == _RAW_SENDER


@pytest.mark.asyncio
async def test_new_command_case_insensitive():
    mock_db = _make_mock_db()
    agent_mock = _make_agent_mock(db=mock_db)
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock) as mock_send_text,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)

        for variant in ["/NEW", "/New", "  /new  ", " /NEW "]:
            agent_mock.arun.reset_mock()
            mock_send_text.reset_mock()

            body = _make_whatsapp_webhook("text", text={"body": variant})
            client.post("/webhook", json=body)

            await _wait_for_mock_call(mock_send_text)

            agent_mock.arun.assert_not_called(), f"arun should not be called for '{variant}'"
            mock_send_text.assert_called_once()


@pytest.mark.asyncio
async def test_new_with_extra_text_not_intercepted():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        # "/new something" is a normal message, not a reset
        body = _make_whatsapp_webhook("text", text={"body": "/new something"})
        client.post("/webhook", json=body)

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()


# === Phone Encryption Mode ===

_TEST_KEY = os.urandom(32)


def _build_encrypted_app(agent_mock: Mock, **extra_kwargs) -> FastAPI:
    from agno.os.interfaces.whatsapp.router import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(router, agent=agent_mock, enable_encryption=True, encryption_key=_TEST_KEY, **extra_kwargs)
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_encrypted_phone_mode():
    from agno.os.interfaces.whatsapp.router import decrypt_phone

    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_encrypted_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "hello"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        call_kwargs = agent_mock.arun.call_args.kwargs
        # user_id should NOT be the raw phone
        assert call_kwargs["user_id"] != "sender_phone"
        # But it should be decryptable back to the original phone
        assert decrypt_phone(call_kwargs["user_id"], _TEST_KEY) == "sender_phone"
        # session_id contains the encrypted user_id
        assert call_kwargs["session_id"] == f"wa:test_agent:{call_kwargs['user_id']}"


@pytest.mark.asyncio
async def test_encrypted_mode_deterministic():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_encrypted_app(agent_mock)
        client = TestClient(app)

        body = _make_whatsapp_webhook("text", text={"body": "first"})
        client.post("/webhook", json=body)
        await _wait_for_agent_call(agent_mock)
        first_user_id = agent_mock.arun.call_args.kwargs["user_id"]

        agent_mock.arun.reset_mock()
        body = _make_whatsapp_webhook("text", text={"body": "second"})
        client.post("/webhook", json=body)
        await _wait_for_agent_call(agent_mock)
        second_user_id = agent_mock.arun.call_args.kwargs["user_id"]

        # Same phone → same encrypted user_id
        assert first_user_id == second_user_id


@pytest.mark.asyncio
async def test_encrypted_mode_keeps_raw_phone_in_context():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_encrypted_app(agent_mock, send_user_number_to_context=True)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "hello"})
        client.post("/webhook", json=body)
        await _wait_for_agent_call(agent_mock)

        call_kwargs = agent_mock.arun.call_args.kwargs
        # user_id is encrypted for DB
        assert call_kwargs["user_id"] != "sender_phone"
        # Dependencies have raw phone — encryption only protects DB, not LLM context
        assert call_kwargs["dependencies"]["User's WhatsApp number"] == "sender_phone"


# === Media Download Skip Notice ===


@pytest.mark.asyncio
async def test_media_download_failure_prepends_skip_notice():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch(
            "agno.os.interfaces.whatsapp.router.download_event_media_async",
            new_callable=AsyncMock,
            return_value=({}, ["image (download failed: 404)"]),
        ),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("image", image={"id": "media_bad", "caption": "Look at this"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        message_text = agent_mock.arun.call_args[0][0]
        assert message_text.startswith("[Some media could not be downloaded:")
        assert "Look at this" in message_text


@pytest.mark.asyncio
async def test_media_download_success_no_skip_notice():
    from agno.media import Image

    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.helpers._send_text", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch(
            "agno.os.interfaces.whatsapp.router.download_event_media_async",
            new_callable=AsyncMock,
            return_value=({"images": [Image(content=b"\x89PNG")]}, []),
        ),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("image", image={"id": "media_ok", "caption": "Nice photo"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        message_text = agent_mock.arun.call_args[0][0]
        # No skip notice — clean caption only
        assert message_text == "Nice photo"
