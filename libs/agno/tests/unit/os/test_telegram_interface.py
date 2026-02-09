import base64
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _install_fake_telebot():
    telebot = types.ModuleType("telebot")
    telebot_async = types.ModuleType("telebot.async_telebot")
    telebot_apihelper = types.ModuleType("telebot.apihelper")

    class AsyncTeleBot:
        def __init__(self, token=None):
            self.token = token

    class TeleBot:
        def __init__(self, token=None):
            self.token = token

    class ApiTelegramException(Exception):
        pass

    telebot.TeleBot = TeleBot
    telebot_async.AsyncTeleBot = AsyncTeleBot
    telebot_apihelper.ApiTelegramException = ApiTelegramException
    sys.modules.setdefault("telebot", telebot)
    sys.modules.setdefault("telebot.async_telebot", telebot_async)
    sys.modules.setdefault("telebot.apihelper", telebot_apihelper)


_install_fake_telebot()

from agno.os.interfaces.telegram import Telegram  # noqa: E402
from agno.os.interfaces.telegram.security import (  # noqa: E402
    get_webhook_secret_token,
    is_development_mode,
    validate_webhook_secret_token,
)

# ---------------------------------------------------------------------------
# security.py
# ---------------------------------------------------------------------------


class TestIsDevelopmentMode:
    def test_unset_is_not_dev(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        assert is_development_mode() is False

    def test_explicit_development(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        assert is_development_mode() is True

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "Development")
        assert is_development_mode() is True

    def test_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        assert is_development_mode() is False

    def test_staging(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        assert is_development_mode() is False


class TestGetWebhookSecretToken:
    def test_returns_token(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "my-secret")
        assert get_webhook_secret_token() == "my-secret"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", raising=False)
        with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_SECRET_TOKEN"):
            get_webhook_secret_token()


class TestValidateWebhookSecretToken:
    def test_dev_mode_bypasses(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        assert validate_webhook_secret_token(None) is True
        assert validate_webhook_secret_token("anything") is True

    def test_prod_valid_token(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "correct-token")
        assert validate_webhook_secret_token("correct-token") is True

    def test_prod_invalid_token(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "correct-token")
        assert validate_webhook_secret_token("wrong-token") is False

    def test_prod_missing_header(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "correct-token")
        assert validate_webhook_secret_token(None) is False

    def test_prod_empty_header(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "correct-token")
        assert validate_webhook_secret_token("") is False


# ---------------------------------------------------------------------------
# telegram.py (Telegram class)
# ---------------------------------------------------------------------------


class TestTelegramClass:
    def test_requires_agent_team_or_workflow(self):
        with pytest.raises(ValueError, match="requires an agent, team, or workflow"):
            Telegram()

    def test_with_agent(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        assert tg.agent is agent
        assert tg.type == "telegram"
        assert tg.prefix == "/telegram"
        assert tg.tags == ["Telegram"]

    def test_with_team(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        team = MagicMock()
        tg = Telegram(team=team)
        assert tg.team is team

    def test_with_workflow(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        wf = MagicMock()
        tg = Telegram(workflow=wf)
        assert tg.workflow is wf

    def test_custom_prefix_and_tags(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent, prefix="/bot", tags=["Bot", "Custom"])
        assert tg.prefix == "/bot"
        assert tg.tags == ["Bot", "Custom"]

    def test_get_router_returns_api_router(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        router = tg.get_router()
        assert router is not None
        routes = [r.path for r in router.routes]
        assert "/telegram/status" in routes
        assert "/telegram/webhook" in routes


# ---------------------------------------------------------------------------
# router.py (FastAPI endpoints via TestClient)
# ---------------------------------------------------------------------------

ROUTER_MODULE = "agno.os.interfaces.telegram.router"


def _make_app(monkeypatch, agent=None, team=None, workflow=None):
    monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
    monkeypatch.setenv("APP_ENV", "development")
    tg = Telegram(agent=agent, team=team, workflow=workflow)
    app = FastAPI()
    app.include_router(tg.get_router())
    return app


class TestStatusEndpoint:
    def test_returns_available(self, monkeypatch):
        app = _make_app(monkeypatch, agent=MagicMock())
        client = TestClient(app)
        resp = client.get("/telegram/status")
        assert resp.status_code == 200
        assert resp.json() == {"status": "available"}


class TestWebhookEndpoint:
    def _text_update(self, text="Hello", chat_id=12345, user_id=67890):
        return {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
                "chat": {"id": chat_id, "type": "private"},
                "text": text,
            },
        }

    def _photo_update(self, caption=None, chat_id=12345):
        msg = {
            "update_id": 2,
            "message": {
                "message_id": 101,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": chat_id, "type": "private"},
                "photo": [
                    {"file_id": "small_id", "width": 90, "height": 90},
                    {"file_id": "large_id", "width": 800, "height": 600},
                ],
            },
        }
        if caption:
            msg["message"]["caption"] = caption
        return msg

    def test_text_message_returns_processing(self, monkeypatch):
        agent = MagicMock()
        app = _make_app(monkeypatch, agent=agent)
        client = TestClient(app)
        resp = client.post("/telegram/webhook", json=self._text_update())
        assert resp.status_code == 200
        assert resp.json() == {"status": "processing"}

    def test_no_message_returns_ignored(self, monkeypatch):
        agent = MagicMock()
        app = _make_app(monkeypatch, agent=agent)
        client = TestClient(app)
        resp = client.post("/telegram/webhook", json={"update_id": 1})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ignored"}

    def test_callback_query_ignored(self, monkeypatch):
        agent = MagicMock()
        app = _make_app(monkeypatch, agent=agent)
        client = TestClient(app)
        resp = client.post(
            "/telegram/webhook",
            json={"update_id": 1, "callback_query": {"id": "123", "data": "action"}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ignored"}

    def test_invalid_secret_token_in_prod(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "correct")
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        app = FastAPI()
        app.include_router(tg.get_router())
        client = TestClient(app)

        resp = client.post(
            "/telegram/webhook",
            json=self._text_update(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert resp.status_code == 403

    def test_valid_secret_token_in_prod(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "correct")
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        app = FastAPI()
        app.include_router(tg.get_router())
        client = TestClient(app)

        resp = client.post(
            "/telegram/webhook",
            json=self._text_update(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "correct"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "processing"}

    def test_missing_secret_token_in_prod(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "correct")
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        app = FastAPI()
        app.include_router(tg.get_router())
        client = TestClient(app)

        resp = client.post("/telegram/webhook", json=self._text_update())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# router.py (process_message — end-to-end via TestClient + mocked AsyncTeleBot)
# ---------------------------------------------------------------------------


def _build_telegram_client(agent=None, team=None, workflow=None):
    from fastapi import APIRouter

    from agno.os.interfaces.telegram.router import attach_routes

    router = APIRouter(prefix="/telegram")
    attach_routes(router=router, agent=agent, team=team, workflow=workflow)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestProcessMessage:
    def test_text_message_calls_agent_arun(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Agent reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Hello bot",
                    },
                },
            )

        assert resp.status_code == 200
        agent.arun.assert_called_once()
        call_kwargs = agent.arun.call_args
        assert call_kwargs[0][0] == "Hello bot"
        assert call_kwargs[1]["user_id"] == "67890"
        assert call_kwargs[1]["session_id"] == "tg:12345"
        assert call_kwargs[1]["images"] is None
        mock_bot.send_chat_action.assert_called_with(12345, "typing")
        mock_bot.send_message.assert_called_with(12345, "Agent reply")

    def test_photo_message_downloads_file(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I see an image"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        mock_file_info = MagicMock()
        mock_file_info.file_path = "photos/file_123.jpg"
        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)
        mock_bot.download_file = AsyncMock(return_value=b"fake-image-bytes")

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 2,
                    "message": {
                        "message_id": 101,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "photo": [
                            {"file_id": "small_id", "width": 90, "height": 90},
                            {"file_id": "large_id", "width": 800, "height": 600},
                        ],
                        "caption": "What is this?",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.get_file.assert_called_with("large_id")
        mock_bot.download_file.assert_called_with("photos/file_123.jpg")
        agent.arun.assert_called_once()
        call_kwargs = agent.arun.call_args
        assert call_kwargs[0][0] == "What is this?"
        assert call_kwargs[1]["images"] is not None
        assert len(call_kwargs[1]["images"]) == 1

    def test_error_response_sends_error_message(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "ERROR"
        mock_response.content = "Internal error details"

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "trigger error",
                    },
                },
            )

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        sent_texts = [call[0][1] for call in send_calls]
        assert any("Sorry" in t for t in sent_texts)

    def test_no_chat_id_skips_processing(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock()
        agent.arun = AsyncMock()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "text": "no chat field",
                    },
                },
            )

        assert resp.status_code == 200
        agent.arun.assert_not_called()

    def test_unsupported_message_type_skips(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock()
        agent.arun = AsyncMock()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "location": {"latitude": 40.7128, "longitude": -74.0060},
                    },
                },
            )

        assert resp.status_code == 200
        agent.arun.assert_not_called()


# ---------------------------------------------------------------------------
# Outbound image handling
# ---------------------------------------------------------------------------


class TestOutboundImages:
    def test_url_image_sent_directly(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_image = MagicMock()
        mock_image.url = "https://example.com/dalle-image.png"
        mock_image.content = None
        mock_image.filepath = None

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Here is a generated image"
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Generate an image",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.send_photo.assert_called_once()
        call_args = mock_bot.send_photo.call_args
        assert call_args[0][0] == 12345
        assert call_args[0][1] == "https://example.com/dalle-image.png"
        assert call_args[1]["caption"] == "Here is a generated image"

    def test_base64_string_image_sent(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        raw_image = b"fake-png-data"
        b64_str = base64.b64encode(raw_image).decode("utf-8")

        mock_image = MagicMock()
        mock_image.url = None
        mock_image.filepath = None
        mock_image.content = b64_str

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Here is the image"
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Generate an image",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.send_photo.assert_called_once()
        call_args = mock_bot.send_photo.call_args
        assert call_args[0][0] == 12345
        assert call_args[0][1] == raw_image
        assert call_args[1]["caption"] == "Here is the image"

    def test_raw_bytes_image_sent(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        raw_image = b"\x89PNG\r\n\x1a\nfake-png-data"

        mock_image = MagicMock()
        mock_image.url = None
        mock_image.filepath = None
        mock_image.content = raw_image

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Here is the image"
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Generate an image",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.send_photo.assert_called_once()
        call_args = mock_bot.send_photo.call_args
        # Raw bytes (not valid UTF-8) should be passed through directly
        assert call_args[0][1] == raw_image

    def test_image_failure_falls_back_to_text(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        raw_image = b"fake-png"
        b64_str = base64.b64encode(raw_image).decode("utf-8")

        mock_image = MagicMock()
        mock_image.url = None
        mock_image.filepath = None
        mock_image.content = b64_str

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Fallback text"
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_bot.send_photo = AsyncMock(side_effect=Exception("API error"))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Generate an image",
                    },
                },
            )

        assert resp.status_code == 200
        # Fallback to text when photo fails
        send_calls = mock_bot.send_message.call_args_list
        sent_texts = [call[0][1] for call in send_calls]
        assert "Fallback text" in sent_texts


# ---------------------------------------------------------------------------
# Inbound media (voice, video, document, sticker)
# ---------------------------------------------------------------------------


class TestInboundMedia:
    def test_voice_message_passes_audio(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I heard audio"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audios = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        mock_file_info = MagicMock()
        mock_file_info.file_path = "voice/file_voice.ogg"
        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)
        mock_bot.download_file = AsyncMock(return_value=b"fake-audio-bytes")

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "voice": {"file_id": "voice_file_id", "duration": 3},
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.get_file.assert_called_with("voice_file_id")
        agent.arun.assert_called_once()
        call_kwargs = agent.arun.call_args[1]
        assert call_kwargs["audio"] is not None
        assert len(call_kwargs["audio"]) == 1
        assert call_kwargs["images"] is None

    def test_video_message_passes_video(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I see a video"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audios = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        mock_file_info = MagicMock()
        mock_file_info.file_path = "video/file_vid.mp4"
        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)
        mock_bot.download_file = AsyncMock(return_value=b"fake-video-bytes")

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "video": {"file_id": "video_file_id", "duration": 10, "width": 1920, "height": 1080},
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.get_file.assert_called_with("video_file_id")
        agent.arun.assert_called_once()
        call_kwargs = agent.arun.call_args[1]
        assert call_kwargs["videos"] is not None
        assert len(call_kwargs["videos"]) == 1
        assert call_kwargs["images"] is None

    def test_document_message_passes_file(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Processed the file"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audios = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        mock_file_info = MagicMock()
        mock_file_info.file_path = "documents/report.pdf"
        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)
        mock_bot.download_file = AsyncMock(return_value=b"fake-pdf-bytes")

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "document": {
                            "file_id": "doc_file_id",
                            "file_name": "report.pdf",
                            "mime_type": "application/pdf",
                        },
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.get_file.assert_called_with("doc_file_id")
        agent.arun.assert_called_once()
        call_kwargs = agent.arun.call_args[1]
        assert call_kwargs["files"] is not None
        assert len(call_kwargs["files"]) == 1
        assert call_kwargs["images"] is None

    def test_sticker_message_passes_image(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "A funny sticker"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audios = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        mock_file_info = MagicMock()
        mock_file_info.file_path = "stickers/sticker.webp"
        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)
        mock_bot.download_file = AsyncMock(return_value=b"fake-sticker-bytes")

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "sticker": {"file_id": "sticker_file_id", "width": 512, "height": 512},
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.get_file.assert_called_with("sticker_file_id")
        agent.arun.assert_called_once()
        call_kwargs = agent.arun.call_args[1]
        assert call_kwargs["images"] is not None
        assert len(call_kwargs["images"]) == 1


# ---------------------------------------------------------------------------
# Outbound audio, video, and document handling
# ---------------------------------------------------------------------------


class TestOutboundAudioVideoFiles:
    def _make_response(self, **overrides):
        r = MagicMock()
        r.status = "COMPLETED"
        r.content = "Here is media"
        r.reasoning_content = None
        r.images = None
        r.audios = None
        r.videos = None
        r.files = None
        for k, v in overrides.items():
            setattr(r, k, v)
        return r

    def test_audio_url_sent_directly(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_audio = MagicMock()
        mock_audio.url = "https://example.com/audio.mp3"
        mock_audio.content = None
        mock_audio.filepath = None
        mock_audio.get_content_bytes = MagicMock(return_value=None)

        mock_response = self._make_response(audios=[mock_audio])
        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Generate audio",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.send_audio.assert_called_once()
        call_args = mock_bot.send_audio.call_args
        assert call_args[0][0] == 12345
        assert call_args[0][1] == "https://example.com/audio.mp3"
        assert call_args[1]["caption"] == "Here is media"

    def test_video_url_sent_directly(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_video = MagicMock()
        mock_video.url = "https://example.com/video.mp4"
        mock_video.content = None
        mock_video.filepath = None
        mock_video.get_content_bytes = MagicMock(return_value=None)

        mock_response = self._make_response(videos=[mock_video])
        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Generate video",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.send_video.assert_called_once()
        call_args = mock_bot.send_video.call_args
        assert call_args[0][0] == 12345
        assert call_args[0][1] == "https://example.com/video.mp4"

    def test_document_bytes_sent(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_file = MagicMock()
        mock_file.url = None
        mock_file.get_content_bytes = MagicMock(return_value=b"fake-doc-bytes")

        mock_response = self._make_response(files=[mock_file])
        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Generate a report",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.send_document.assert_called_once()
        call_args = mock_bot.send_document.call_args
        assert call_args[0][0] == 12345
        assert call_args[0][1] == b"fake-doc-bytes"

    def test_caption_only_on_first_media(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_img = MagicMock()
        mock_img.url = "https://example.com/img.png"
        mock_img.content = None
        mock_img.filepath = None

        mock_audio = MagicMock()
        mock_audio.url = "https://example.com/audio.mp3"
        mock_audio.get_content_bytes = MagicMock(return_value=None)

        mock_response = self._make_response(images=[mock_img], audios=[mock_audio])
        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Generate image and audio",
                    },
                },
            )

        assert resp.status_code == 200
        # Image gets caption, audio does not
        photo_args = mock_bot.send_photo.call_args
        assert photo_args[1]["caption"] == "Here is media"
        audio_args = mock_bot.send_audio.call_args
        assert audio_args[1]["caption"] is None
        # Text not sent separately since media was sent
        mock_bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Message splitting (end-to-end via process_message)
# ---------------------------------------------------------------------------


class TestMessageSplitting:
    def test_sends_via_chunked(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Short reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Quick question",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.send_message.assert_called_with(12345, "Short reply")


# ---------------------------------------------------------------------------
# attach_routes validation
# ---------------------------------------------------------------------------


class TestAttachRoutesValidation:
    def test_raises_without_agent_team_workflow(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from fastapi import APIRouter

        from agno.os.interfaces.telegram.router import attach_routes

        with pytest.raises(ValueError, match="Either agent, team, or workflow"):
            attach_routes(router=APIRouter())

    def test_raises_without_telegram_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        from fastapi import APIRouter

        from agno.os.interfaces.telegram.router import attach_routes

        with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
            attach_routes(router=APIRouter(), agent=MagicMock())
