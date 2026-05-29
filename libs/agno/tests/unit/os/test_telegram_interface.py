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
from agno.os.interfaces.telegram.formatting import markdown_to_telegram_html  # noqa: E402
from agno.os.interfaces.telegram.security import (  # noqa: E402
    _is_dev_mode as is_development_mode,
)
from agno.os.interfaces.telegram.security import (  # noqa: E402
    get_webhook_secret_token,
    validate_webhook_secret_token,
)

SECURITY_MODULE = "agno.os.interfaces.telegram.security"


@pytest.fixture(autouse=True)
def _bypass_router_security():
    with patch("agno.os.interfaces.telegram.router.validate_webhook_secret_token", return_value=True):
        yield


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
        monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", raising=False)
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

    def test_reply_to_mentions_only_default(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        assert tg.reply_to_mentions_only is True

    def test_reply_to_mentions_only_false(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent, reply_to_mentions_only=False)
        assert tg.reply_to_mentions_only is False

    def test_quoted_responses_default(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        assert tg.quoted_responses is False

    def test_quoted_responses_true(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent, quoted_responses=True)
        assert tg.quoted_responses is True

    def test_get_router_returns_api_router(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        router = tg.get_router()
        assert router is not None
        routes = [r.path for r in router.routes]
        assert "/telegram/status" in routes
        assert "/telegram/webhook" in routes


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
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        app = FastAPI()
        app.include_router(tg.get_router())

        with patch(f"{ROUTER_MODULE}.validate_webhook_secret_token", return_value=False):
            client = TestClient(app)
            resp = client.post(
                "/telegram/webhook",
                json=self._text_update(),
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            )
        assert resp.status_code == 403

    def test_valid_secret_token_in_prod(self, monkeypatch):
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
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        app = FastAPI()
        app.include_router(tg.get_router())

        with patch(f"{ROUTER_MODULE}.validate_webhook_secret_token", return_value=False):
            client = TestClient(app)
            resp = client.post("/telegram/webhook", json=self._text_update())
        assert resp.status_code == 403


def _build_telegram_client(
    agent=None,
    team=None,
    workflow=None,
    reply_to_mentions_only=True,
    reply_to_bot_messages=True,
    start_message=None,
    help_message=None,
    error_message=None,
    show_reasoning=False,
    streaming=False,
    token=None,
    quoted_responses=False,
):
    from fastapi import APIRouter

    from agno.os.interfaces.telegram.router import attach_routes

    router = APIRouter(prefix="/telegram")
    kwargs: dict = dict(
        router=router,
        agent=agent,
        team=team,
        workflow=workflow,
        reply_to_mentions_only=reply_to_mentions_only,
        reply_to_bot_messages=reply_to_bot_messages,
        show_reasoning=show_reasoning,
        streaming=streaming,
        quoted_responses=quoted_responses,
    )
    if token is not None:
        kwargs["token"] = token
    if start_message is not None:
        kwargs["start_message"] = start_message
    if help_message is not None:
        kwargs["help_message"] = help_message
    if error_message is not None:
        kwargs["error_message"] = error_message
    attach_routes(**kwargs)
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

        agent = AsyncMock(id="test-agent")
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
        assert call_kwargs[1]["session_id"] == "tg:test-agent:12345"
        assert "images" not in call_kwargs[1]
        mock_bot.send_chat_action.assert_called()
        mock_bot.send_message.assert_called_with(
            12345, "Agent reply", parse_mode="HTML", reply_to_message_id=None, message_thread_id=None
        )

    def test_photo_message_downloads_file(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I see an image"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
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

        agent = AsyncMock(id="test-agent")
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

        agent = AsyncMock(id="test-agent")
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

        agent = AsyncMock(id="test-agent")
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

        agent = AsyncMock(id="test-agent")
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

    def test_base64_string_image_sent(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        raw_image = b"fake-png-data"
        b64_str = base64.b64encode(raw_image).decode("utf-8")

        mock_image = MagicMock()
        mock_image.url = None
        mock_image.filepath = None
        mock_image.content = b64_str
        mock_image.get_content_bytes = MagicMock(return_value=raw_image)

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Here is the image"
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]

        agent = AsyncMock(id="test-agent")
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

    def test_raw_bytes_image_sent(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        raw_image = b"\x89PNG\r\n\x1a\nfake-png-data"

        mock_image = MagicMock()
        mock_image.url = None
        mock_image.filepath = None
        mock_image.content = raw_image
        mock_image.get_content_bytes = MagicMock(return_value=raw_image)

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Here is the image"
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]

        agent = AsyncMock(id="test-agent")
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

        agent = AsyncMock(id="test-agent")
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


class TestInboundMedia:
    def test_voice_message_passes_audio(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I heard audio"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock(id="test-agent")
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
        assert "images" not in call_kwargs

    def test_video_message_passes_video(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I see a video"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock(id="test-agent")
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
        assert "images" not in call_kwargs

    def test_document_message_passes_file(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Processed the file"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock(id="test-agent")
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
        assert "images" not in call_kwargs

    def test_sticker_message_passes_image(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "A funny sticker"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock(id="test-agent")
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


class TestOutboundAudioVideoFiles:
    def _make_response(self, **overrides):
        r = MagicMock()
        r.status = "COMPLETED"
        r.content = "Here is media"
        r.reasoning_content = None
        r.images = None
        r.audio = None
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

        mock_response = self._make_response(audio=[mock_audio])
        agent = AsyncMock(id="test-agent")
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

    def test_video_url_sent_directly(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_video = MagicMock()
        mock_video.url = "https://example.com/video.mp4"
        mock_video.content = None
        mock_video.filepath = None
        mock_video.get_content_bytes = MagicMock(return_value=None)

        mock_response = self._make_response(videos=[mock_video])
        agent = AsyncMock(id="test-agent")
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
        mock_file.content = b"fake-doc-bytes"
        mock_file.filepath = None
        mock_file.get_content_bytes = MagicMock(return_value=b"fake-doc-bytes")

        mock_response = self._make_response(files=[mock_file])
        agent = AsyncMock(id="test-agent")
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

        mock_response = self._make_response(images=[mock_img], audio=[mock_audio])
        agent = AsyncMock(id="test-agent")
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
        # No captions — text sent separately from media
        mock_bot.send_photo.assert_called_once()
        mock_bot.send_audio.assert_called_once()
        mock_bot.send_message.assert_called_once()


class TestMessageSplitting:
    def test_sends_via_chunked(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Short reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
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
        mock_bot.send_message.assert_called_with(
            12345, "Short reply", parse_mode="HTML", reply_to_message_id=None, message_thread_id=None
        )


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


class TestBotCommands:
    def _group_update(self, text, chat_id=-100123, msg_id=200, user_id=67890, entities=None):
        msg = {
            "update_id": 1,
            "message": {
                "message_id": msg_id,
                "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
                "chat": {"id": chat_id, "type": "supergroup"},
                "text": text,
            },
        }
        if entities:
            msg["message"]["entities"] = entities
        return msg

    def _dm_update(self, text, chat_id=12345, msg_id=100):
        return {
            "update_id": 1,
            "message": {
                "message_id": msg_id,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": chat_id, "type": "private"},
                "text": text,
            },
        }

    def test_start_command_in_dm(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")
        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json=self._dm_update("/start"))

        assert resp.status_code == 200
        agent.arun.assert_not_called()
        mock_bot.send_message.assert_called_once()
        sent_text = mock_bot.send_message.call_args[0][1]
        assert "ready to help" in sent_text.lower()

    def test_help_command_in_dm(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")
        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json=self._dm_update("/help"))

        assert resp.status_code == 200
        agent.arun.assert_not_called()
        mock_bot.send_message.assert_called_once()
        sent_text = mock_bot.send_message.call_args[0][1]
        assert "text" in sent_text.lower()

    def test_start_with_bot_suffix_in_group(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")
        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "my_bot"
        mock_me.id = 99999
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json=self._group_update("/start@my_bot"))

        assert resp.status_code == 200
        agent.arun.assert_not_called()
        mock_bot.send_message.assert_called_once()

    def test_regular_text_not_treated_as_command(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json=self._dm_update("Hello there"))

        assert resp.status_code == 200
        agent.arun.assert_called_once()


class TestGroupMentionFiltering:
    def _group_mention_update(self, text, bot_username="test_bot", chat_id=-100123, msg_id=200):
        mention = f"@{bot_username}"
        offset = text.find(mention)
        entities = []
        if offset >= 0:
            entities = [{"type": "mention", "offset": offset, "length": len(mention)}]
        return {
            "update_id": 1,
            "message": {
                "message_id": msg_id,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": chat_id, "type": "supergroup"},
                "text": text,
                "entities": entities,
            },
        }

    def _group_plain_update(self, text="Hello everyone", chat_id=-100123, msg_id=200):
        return {
            "update_id": 1,
            "message": {
                "message_id": msg_id,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": chat_id, "type": "supergroup"},
                "text": text,
            },
        }

    def test_group_with_mention_is_processed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Group reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
            resp = client.post(
                "/telegram/webhook",
                json=self._group_mention_update("@test_bot what is Python?"),
            )

        assert resp.status_code == 200
        agent.arun.assert_called_once()

    def test_group_without_mention_is_skipped(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
            resp = client.post(
                "/telegram/webhook",
                json=self._group_plain_update("Hello everyone"),
            )

        assert resp.status_code == 200
        agent.arun.assert_not_called()

    def test_group_without_mention_processed_when_flag_false(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=False)
            resp = client.post(
                "/telegram/webhook",
                json=self._group_plain_update("Hello everyone"),
            )

        assert resp.status_code == 200
        agent.arun.assert_called_once()

    def test_dm_always_processed_regardless_of_flag(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "DM reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
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

    def test_photo_with_mention_in_caption_processed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I see an image"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)

        mock_file_info = MagicMock()
        mock_file_info.file_path = "photos/file.jpg"
        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)
        mock_bot.download_file = AsyncMock(return_value=b"fake-bytes")
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 200,
                        "from": {"id": 67890},
                        "chat": {"id": -100123, "type": "supergroup"},
                        "photo": [{"file_id": "photo_id", "width": 800, "height": 600}],
                        "caption": "@test_bot describe this",
                        "caption_entities": [{"type": "mention", "offset": 0, "length": 9}],
                    },
                },
            )

        assert resp.status_code == 200
        agent.arun.assert_called_once()


class TestReplyToBotFiltering:
    BOT_USER_ID = 11111

    def _reply_to_bot_update(self, text="follow up", chat_id=-100123, msg_id=300, bot_msg_id=200):
        return {
            "update_id": 1,
            "message": {
                "message_id": msg_id,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": chat_id, "type": "supergroup"},
                "text": text,
                "reply_to_message": {
                    "message_id": bot_msg_id,
                    "from": {"id": self.BOT_USER_ID, "is_bot": True, "first_name": "Bot"},
                    "chat": {"id": chat_id, "type": "supergroup"},
                    "text": "previous bot response",
                },
            },
        }

    def _reply_to_human_update(self, text="replying to human", chat_id=-100123, msg_id=300):
        return {
            "update_id": 1,
            "message": {
                "message_id": msg_id,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": chat_id, "type": "supergroup"},
                "text": text,
                "reply_to_message": {
                    "message_id": 150,
                    "from": {"id": 99999, "is_bot": False, "first_name": "Other"},
                    "chat": {"id": chat_id, "type": "supergroup"},
                    "text": "some other message",
                },
            },
        }

    def test_reply_to_bot_is_processed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "follow up reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True, reply_to_bot_messages=True)
            resp = client.post("/telegram/webhook", json=self._reply_to_bot_update("multiply by 10"))

        assert resp.status_code == 200
        agent.arun.assert_called_once()

    def test_reply_to_bot_skipped_when_disabled(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True, reply_to_bot_messages=False)
            resp = client.post("/telegram/webhook", json=self._reply_to_bot_update("multiply by 10"))

        assert resp.status_code == 200
        agent.arun.assert_not_called()

    def test_reply_to_human_is_skipped(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True, reply_to_bot_messages=True)
            resp = client.post("/telegram/webhook", json=self._reply_to_human_update())

        assert resp.status_code == 200
        agent.arun.assert_not_called()

    def test_reply_to_bot_without_mentions_only_flag(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=False)
            resp = client.post("/telegram/webhook", json=self._reply_to_bot_update())

        assert resp.status_code == 200
        agent.arun.assert_called_once()


class TestMentionStripping:
    def test_mention_at_start_stripped(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 200,
                        "from": {"id": 67890},
                        "chat": {"id": -100123, "type": "supergroup"},
                        "text": "@test_bot what is Python?",
                        "entities": [{"type": "mention", "offset": 0, "length": 9}],
                    },
                },
            )

        assert resp.status_code == 200
        agent.arun.assert_called_once()
        sent_text = agent.arun.call_args[0][0]
        assert "@test_bot" not in sent_text
        assert "what is Python?" in sent_text

    def test_mention_in_middle_stripped(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 200,
                        "from": {"id": 67890},
                        "chat": {"id": -100123, "type": "supergroup"},
                        "text": "hey @test_bot explain this",
                        "entities": [{"type": "mention", "offset": 4, "length": 9}],
                    },
                },
            )

        assert resp.status_code == 200
        agent.arun.assert_called_once()
        sent_text = agent.arun.call_args[0][0]
        assert "@test_bot" not in sent_text
        assert "hey" in sent_text
        assert "explain this" in sent_text

    def test_dm_text_not_stripped(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
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
                        "text": "Hello world",
                    },
                },
            )

        assert resp.status_code == 200
        agent.arun.assert_called_once()
        assert agent.arun.call_args[0][0] == "Hello world"


class TestGroupSessionId:
    def test_dm_session_id(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
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
                        "text": "Hello",
                    },
                },
            )

        assert resp.status_code == 200
        assert agent.arun.call_args[1]["session_id"] == "tg:test-agent:12345"

    def test_group_new_message_session_id(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 500,
                        "from": {"id": 67890},
                        "chat": {"id": -100123, "type": "supergroup"},
                        "text": "@test_bot hello",
                        "entities": [{"type": "mention", "offset": 0, "length": 9}],
                    },
                },
            )

        assert resp.status_code == 200
        assert agent.arun.call_args[1]["session_id"] == "tg:test-agent:-100123"

    def test_group_reply_uses_root_message_id(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 600,
                        "from": {"id": 67890},
                        "chat": {"id": -100123, "type": "supergroup"},
                        "text": "@test_bot follow up",
                        "entities": [{"type": "mention", "offset": 0, "length": 9}],
                        "reply_to_message": {"message_id": 500},
                    },
                },
            )

        assert resp.status_code == 200
        assert agent.arun.call_args[1]["session_id"] == "tg:test-agent:-100123"


class TestReplyThreading:
    def test_group_reply_to_message_id_set(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Group reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 300,
                        "from": {"id": 67890},
                        "chat": {"id": -100123, "type": "supergroup"},
                        "text": "@test_bot hello",
                        "entities": [{"type": "mention", "offset": 0, "length": 9}],
                    },
                },
            )

        assert resp.status_code == 200
        send_call = mock_bot.send_message.call_args
        assert send_call[1].get("reply_to_message_id") == 300

    def test_dm_reply_to_message_id_not_set(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "DM reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
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
                        "text": "Hello",
                    },
                },
            )

        assert resp.status_code == 200
        send_call = mock_bot.send_message.call_args
        assert send_call[1].get("reply_to_message_id") is None

    def test_dm_reply_to_message_id_set_when_enabled(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "DM reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, quoted_responses=True)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Hello",
                    },
                },
            )

        assert resp.status_code == 200
        send_call = mock_bot.send_message.call_args
        assert send_call[1].get("reply_to_message_id") == 100

    def test_group_chunked_only_first_chunk_replies(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        long_text = "A" * 5000

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = long_text
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()
        mock_me = MagicMock()
        mock_me.username = "test_bot"
        mock_me.id = 11111
        mock_bot.get_me = AsyncMock(return_value=mock_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, reply_to_mentions_only=True)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 300,
                        "from": {"id": 67890},
                        "chat": {"id": -100123, "type": "supergroup"},
                        "text": "@test_bot write something long",
                        "entities": [{"type": "mention", "offset": 0, "length": 9}],
                    },
                },
            )

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        # Find HTML chunk calls (parse_mode="HTML")
        chunk_calls = [c for c in send_calls if c[1].get("parse_mode") == "HTML"]
        assert len(chunk_calls) >= 2
        # First chunk has reply_to_message_id
        assert chunk_calls[0][1].get("reply_to_message_id") == 300
        # Second chunk does not
        assert chunk_calls[1][1].get("reply_to_message_id") is None


class TestCodexReviewFixes:
    def test_long_text_sent_after_media(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        long_text = "A" * 2000

        mock_image = MagicMock()
        mock_image.url = "https://example.com/image.png"
        mock_image.content = None
        mock_image.filepath = None

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = long_text
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock(id="test-agent")
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
                        "text": "Generate an image with details",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.send_photo.assert_called_once()
        photo_args = mock_bot.send_photo.call_args
        assert "caption" not in photo_args[1]
        mock_bot.send_message.assert_called()
        text_call = mock_bot.send_message.call_args
        assert text_call[0][1] == long_text

    def test_file_string_content_sent_as_document(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        csv_content = "name,age\nAlice,30\nBob,25"

        mock_file = MagicMock()
        mock_file.url = None
        mock_file.content = csv_content
        mock_file.filepath = None
        mock_file.get_content_bytes = MagicMock(return_value=csv_content.encode("utf-8"))

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Here is the CSV"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = [mock_file]

        agent = AsyncMock(id="test-agent")
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
                        "text": "Give me the CSV",
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.send_document.assert_called_once()
        call_args = mock_bot.send_document.call_args
        assert call_args[0][1] == csv_content.encode("utf-8")

    def test_reasoning_content_sent(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Final answer"
        mock_response.reasoning_content = "Step 1: think. Step 2: conclude."
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, show_reasoning=True)
            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Think step by step",
                    },
                },
            )

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        reasoning_call = send_calls[0]
        # _send_html converts to HTML
        sent_text = reasoning_call[0][1]
        assert "Reasoning:" in sent_text
        assert "Step 1" in sent_text

    def test_video_note_parsed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I see a video note"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)

        mock_file_info = MagicMock()
        mock_file_info.file_path = "video_notes/file_vnote.mp4"
        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)
        mock_bot.download_file = AsyncMock(return_value=b"fake-vnote-bytes")

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
                        "video_note": {"file_id": "vnote_file_id", "duration": 5, "length": 240},
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.get_file.assert_called_with("vnote_file_id")
        agent.arun.assert_called_once()
        call_kwargs = agent.arun.call_args[1]
        assert call_kwargs["videos"] is not None
        assert len(call_kwargs["videos"]) == 1

    def test_animation_parsed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I see a GIF"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)

        mock_file_info = MagicMock()
        mock_file_info.file_path = "animations/file_anim.mp4"
        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)
        mock_bot.download_file = AsyncMock(return_value=b"fake-anim-bytes")

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
                        "animation": {"file_id": "anim_file_id", "duration": 3, "width": 320, "height": 240},
                    },
                },
            )

        assert resp.status_code == 200
        mock_bot.get_file.assert_called_with("anim_file_id")
        agent.arun.assert_called_once()
        call_kwargs = agent.arun.call_args[1]
        assert call_kwargs["videos"] is not None
        assert len(call_kwargs["videos"]) == 1

    def test_media_download_failure_handled(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "No media available"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)

        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(side_effect=Exception("Telegram API timeout"))

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
                        "photo": [
                            {"file_id": "small_id", "width": 90, "height": 90},
                            {"file_id": "large_id", "width": 800, "height": 600},
                        ],
                    },
                },
            )

        assert resp.status_code == 200
        # No text and media download failed → nothing to process, model not invoked
        agent.arun.assert_not_called()


class TestBotMessageFiltering:
    def _bot_update(self, text="Hello from bot", chat_id=12345):
        return {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "from": {"id": 99999, "is_bot": True, "first_name": "OtherBot"},
                "chat": {"id": chat_id, "type": "private"},
                "text": text,
            },
        }

    def test_bot_messages_are_ignored(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json=self._bot_update())

        assert resp.status_code == 200
        agent.arun.assert_not_called()

    def test_human_messages_are_processed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock(id="test-agent")
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
                        "from": {"id": 67890, "is_bot": False, "first_name": "Human"},
                        "chat": {"id": 12345, "type": "private"},
                        "text": "Hello from human",
                    },
                },
            )

        assert resp.status_code == 200
        agent.arun.assert_called_once()


class TestCustomMessages:
    def _dm_update(self, text, chat_id=12345):
        return {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": chat_id, "type": "private"},
                "text": text,
            },
        }

    def test_custom_start_message(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")
        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, start_message="Welcome aboard!")
            resp = client.post("/telegram/webhook", json=self._dm_update("/start"))

        assert resp.status_code == 200
        agent.arun.assert_not_called()
        sent_text = mock_bot.send_message.call_args[0][1]
        # _send_html converts to HTML; plain text with no markdown stays as-is
        assert sent_text == "Welcome aboard!"

    def test_custom_help_message(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")
        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, help_message="Ask me anything!")
            resp = client.post("/telegram/webhook", json=self._dm_update("/help"))

        assert resp.status_code == 200
        agent.arun.assert_not_called()
        sent_text = mock_bot.send_message.call_args[0][1]
        # _send_html converts to HTML; plain text stays as-is
        assert sent_text == "Ask me anything!"

    def test_custom_error_message(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "ERROR"
        mock_response.content = "Internal error"

        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, error_message="Oops! Something broke.")
            resp = client.post(
                "/telegram/webhook",
                json=self._dm_update("trigger error"),
            )

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        sent_texts = [call[0][1] for call in send_calls]
        # _send_html converts to HTML; "!" stays as-is
        assert any("Oops!" in t for t in sent_texts)


class TestTeamWorkflowProcessing:
    def _text_update(self, text="Hello"):
        return {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 12345, "type": "private"},
                "text": text,
            },
        }

    def test_team_arun_called(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Team reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        team = AsyncMock(id="test-team")
        team.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(team=team)
            resp = client.post("/telegram/webhook", json=self._text_update("Hello team"))

        assert resp.status_code == 200
        team.arun.assert_called_once()
        assert team.arun.call_args[0][0] == "Hello team"
        assert team.arun.call_args[1]["session_id"] == "tg:test-team:12345"
        mock_bot.send_message.assert_called_with(
            12345, "Team reply", parse_mode="HTML", reply_to_message_id=None, message_thread_id=None
        )

    def test_workflow_arun_called(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Workflow reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        workflow = AsyncMock(id="test-workflow")
        workflow.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(workflow=workflow)
            resp = client.post("/telegram/webhook", json=self._text_update("Hello workflow"))

        assert resp.status_code == 200
        workflow.arun.assert_called_once()
        assert workflow.arun.call_args[0][0] == "Hello workflow"
        mock_bot.send_message.assert_called_with(
            12345, "Workflow reply", parse_mode="HTML", reply_to_message_id=None, message_thread_id=None
        )


class TestStreamingErrorHandling:
    """Test that streaming mode sends error messages back to the user."""

    def _text_update(self, text="Hello"):
        return {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 12345, "type": "private"},
                "text": text,
            },
        }

    def test_streaming_error_sends_error_message(self, monkeypatch):
        """When streaming returns ERROR status, error message should be sent to user."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        from agno.run.agent import RunOutput

        mock_run_output = MagicMock(spec=RunOutput)
        mock_run_output.status = "ERROR"
        mock_run_output.content = "Something went wrong"
        mock_run_output.reasoning_content = None
        mock_run_output.images = None
        mock_run_output.audio = None
        mock_run_output.videos = None
        mock_run_output.files = None

        async def fake_stream(*args, **kwargs):
            yield mock_run_output

        agent = AsyncMock(id="test-agent")
        agent.arun = MagicMock(return_value=fake_stream())
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, streaming=True)
            resp = client.post("/telegram/webhook", json=self._text_update("trigger error"))

        assert resp.status_code == 200
        # Verify error message was sent to the user
        send_calls = mock_bot.send_message.call_args_list
        sent_texts = [call[0][1] if len(call[0]) > 1 else call[1].get("text", "") for call in send_calls]
        assert any("Sorry" in str(t) for t in sent_texts), f"Expected error message in sends, got: {sent_texts}"

    def test_streaming_success_no_error_message(self, monkeypatch):
        """When streaming succeeds, no error message should be sent."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        from agno.run.agent import RunContentEvent, RunOutput

        mock_content_event = MagicMock(spec=RunContentEvent)
        mock_content_event.content = "Hello world"

        mock_run_output = MagicMock(spec=RunOutput)
        mock_run_output.status = "COMPLETED"
        mock_run_output.content = "Hello world"
        mock_run_output.reasoning_content = None
        mock_run_output.images = None
        mock_run_output.audio = None
        mock_run_output.videos = None
        mock_run_output.files = None

        async def fake_stream(*args, **kwargs):
            yield mock_content_event
            yield mock_run_output

        agent = AsyncMock(id="test-agent")
        agent.arun = MagicMock(return_value=fake_stream())
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, streaming=True)
            resp = client.post("/telegram/webhook", json=self._text_update("hello"))

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        sent_texts = [str(call[0][1]) if len(call[0]) > 1 else "" for call in send_calls]
        assert not any("Sorry" in t for t in sent_texts)


class TestMultiBotTokenParam:
    """Test that the token parameter allows multiple bot configurations."""

    def test_token_param_used_instead_of_env(self, monkeypatch):
        """When token param is passed, it should be used instead of TELEGRAM_TOKEN env."""
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        monkeypatch.setenv("APP_ENV", "development")

        agent = MagicMock()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot) as mock_telebot_cls:
            client = _build_telegram_client(agent=agent, token="custom-bot-token")
            resp = client.get("/telegram/status")

        assert resp.status_code == 200
        mock_telebot_cls.assert_called_with("custom-bot-token")

    def test_env_token_used_when_no_param(self, monkeypatch):
        """When no token param, TELEGRAM_TOKEN env should be used."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "env-bot-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = MagicMock()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot) as mock_telebot_cls:
            client = _build_telegram_client(agent=agent)
            resp = client.get("/telegram/status")

        assert resp.status_code == 200
        mock_telebot_cls.assert_called_with("env-bot-token")

    def test_missing_token_raises_error(self, monkeypatch):
        """When no token param and no TELEGRAM_TOKEN env, should raise ValueError."""
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        monkeypatch.setenv("APP_ENV", "development")

        from agno.os.interfaces.telegram.router import attach_routes

        agent = MagicMock()

        with pytest.raises(ValueError, match="TELEGRAM_TOKEN.*not set.*no token"):
            from fastapi import APIRouter

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

    def test_telegram_class_accepts_token(self, monkeypatch):
        """Telegram class should accept and store the token parameter."""
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        agent = MagicMock()
        tg = Telegram(agent=agent, token="my-bot-token")
        assert tg.token == "my-bot-token"

    def test_telegram_class_token_default_none(self, monkeypatch):
        """Token parameter should default to None."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        assert tg.token is None


class TestStreamingEnhancedEvents:
    """Test enhanced streaming events: reasoning started, tool completed, workflow streaming."""

    def _text_update(self, text="Hello"):
        return {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 12345, "type": "private"},
                "text": text,
            },
        }

    def test_reasoning_started_shows_status_line(self, monkeypatch):
        """ReasoningStartedEvent should add a 'Reasoning...' status line."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        from agno.run.agent import ReasoningStartedEvent, RunContentEvent, RunOutput

        mock_reasoning_event = MagicMock(spec=ReasoningStartedEvent)
        mock_reasoning_event.event = "ReasoningStarted"
        mock_content_event = MagicMock(spec=RunContentEvent)
        mock_content_event.event = "RunContent"
        mock_content_event.content = "Final answer"
        mock_run_output = MagicMock(spec=RunOutput)
        mock_run_output.status = "COMPLETED"
        mock_run_output.content = "Final answer"
        mock_run_output.reasoning_content = None
        mock_run_output.images = None
        mock_run_output.audio = None
        mock_run_output.videos = None
        mock_run_output.files = None

        async def fake_stream(*args, **kwargs):
            yield mock_reasoning_event
            yield mock_content_event
            yield mock_run_output

        agent = AsyncMock(id="test-agent")
        agent.arun = MagicMock(return_value=fake_stream())
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, streaming=True)
            resp = client.post("/telegram/webhook", json=self._text_update("think about this"))

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        edit_calls = mock_bot.edit_message_text.call_args_list
        all_texts = [str(call[0][1]) if len(call[0]) > 1 else "" for call in send_calls]
        all_texts += [str(call[0][0]) if len(call[0]) > 0 else "" for call in edit_calls]
        assert any("Reasoning..." in t for t in all_texts), f"Expected 'Reasoning...' in messages, got: {all_texts}"

    def test_tool_completed_updates_status_line(self, monkeypatch):
        """ToolCallCompletedEvent should update 'X...' to 'X'."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        from agno.run.agent import RunContentEvent, RunOutput, ToolCallCompletedEvent, ToolCallStartedEvent

        mock_tool = MagicMock()
        mock_tool.tool_name = "web_search"

        mock_started = MagicMock(spec=ToolCallStartedEvent)
        mock_started.event = "ToolCallStarted"
        mock_started.tool = mock_tool
        mock_started.agent_name = None

        mock_completed = MagicMock(spec=ToolCallCompletedEvent)
        mock_completed.event = "ToolCallCompleted"
        mock_completed.tool = mock_tool

        mock_content_event = MagicMock(spec=RunContentEvent)
        mock_content_event.event = "RunContent"
        mock_content_event.content = "Search results here"

        mock_run_output = MagicMock(spec=RunOutput)
        mock_run_output.status = "COMPLETED"
        mock_run_output.content = "Search results here"
        mock_run_output.reasoning_content = None
        mock_run_output.images = None
        mock_run_output.audio = None
        mock_run_output.videos = None
        mock_run_output.files = None

        async def fake_stream(*args, **kwargs):
            yield mock_started
            yield mock_completed
            yield mock_content_event
            yield mock_run_output

        agent = AsyncMock(id="test-agent")
        agent.arun = MagicMock(return_value=fake_stream())
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent, streaming=True)
            resp = client.post("/telegram/webhook", json=self._text_update("search for something"))

        assert resp.status_code == 200
        edit_calls = mock_bot.edit_message_text.call_args_list
        edit_texts = [str(call[0][0]) if len(call[0]) > 0 else "" for call in edit_calls]
        assert any("web_search" in t for t in edit_texts), f"Expected 'web_search' in edits, got: {edit_texts}"

    def test_workflow_step_progress_display(self, monkeypatch):
        """Workflow streaming should show step start/complete status lines."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        from agno.run.workflow import StepCompletedEvent, StepStartedEvent, WorkflowCompletedEvent

        mock_step_started = MagicMock(spec=StepStartedEvent)
        mock_step_started.event = "StepStarted"
        mock_step_started.step_name = "analyze_data"

        mock_step_completed = MagicMock(spec=StepCompletedEvent)
        mock_step_completed.event = "StepCompleted"
        mock_step_completed.step_name = "analyze_data"
        mock_step_completed.content = "Analysis complete"

        mock_wf_completed = MagicMock(spec=WorkflowCompletedEvent)
        mock_wf_completed.event = "WorkflowCompleted"
        mock_wf_completed.content = "Final workflow result"

        async def fake_stream(*args, **kwargs):
            yield mock_step_started
            yield mock_step_completed
            yield mock_wf_completed

        workflow = AsyncMock(id="test-workflow")
        workflow.arun = MagicMock(return_value=fake_stream())
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(workflow=workflow, streaming=True)
            resp = client.post("/telegram/webhook", json=self._text_update("run workflow"))

        assert resp.status_code == 200
        # Workflow should have been called with streaming=True
        workflow.arun.assert_called_once()
        call_kwargs = workflow.arun.call_args[1]
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_events"] is True

        send_calls = mock_bot.send_message.call_args_list
        edit_calls = mock_bot.edit_message_text.call_args_list
        all_texts = [str(call[0][1]) if len(call[0]) > 1 else "" for call in send_calls]
        all_texts += [str(call[0][0]) if len(call[0]) > 0 else "" for call in edit_calls]
        assert any("analyze_data" in t for t in all_texts), f"Expected step progress, got: {all_texts}"

    def test_workflow_parallel_execution_status(self, monkeypatch):
        """Workflow streaming should show parallel execution status."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        from agno.run.workflow import ParallelExecutionStartedEvent, WorkflowCompletedEvent

        mock_parallel = MagicMock(spec=ParallelExecutionStartedEvent)
        mock_parallel.event = "ParallelExecutionStarted"
        mock_parallel.parallel_step_count = 3

        mock_wf_completed = MagicMock(spec=WorkflowCompletedEvent)
        mock_wf_completed.event = "WorkflowCompleted"
        mock_wf_completed.content = "All done"

        async def fake_stream(*args, **kwargs):
            yield mock_parallel
            yield mock_wf_completed

        workflow = AsyncMock(id="test-workflow")
        workflow.arun = MagicMock(return_value=fake_stream())
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(workflow=workflow, streaming=True)
            resp = client.post("/telegram/webhook", json=self._text_update("parallel work"))

        assert resp.status_code == 200
        send_calls = mock_bot.send_message.call_args_list
        edit_calls = mock_bot.edit_message_text.call_args_list
        all_texts = [str(call[0][1]) if len(call[0]) > 1 else "" for call in send_calls]
        all_texts += [str(call[0][0]) if len(call[0]) > 0 else "" for call in edit_calls]
        assert any("Parallel" in t for t in all_texts), f"Expected parallel status, got: {all_texts}"

    def test_workflow_error_handling_in_stream(self, monkeypatch):
        """Workflow error events should display error message."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        from agno.run.workflow import WorkflowErrorEvent

        mock_error = MagicMock(spec=WorkflowErrorEvent)
        mock_error.event = "WorkflowError"
        mock_error.error = "Step failed: timeout"

        async def fake_stream(*args, **kwargs):
            yield mock_error

        workflow = AsyncMock(id="test-workflow")
        workflow.arun = MagicMock(return_value=fake_stream())
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(workflow=workflow, streaming=True)
            resp = client.post("/telegram/webhook", json=self._text_update("fail workflow"))

        assert resp.status_code == 200
        # WorkflowError sets accumulated_content to error_message, then finalize sends it
        send_calls = mock_bot.send_message.call_args_list
        sent_texts = [str(call[0][1]) if len(call[0]) > 1 else "" for call in send_calls]
        sent_texts += [str(call.kwargs.get("text", "")) for call in send_calls if call.kwargs]
        # The error handler sends the default error message
        assert any("error" in t.lower() for t in sent_texts if t), (
            f"Expected error message in sent texts, got: {sent_texts}"
        )


class TestMarkdownToTelegramHtml:
    def test_plain_text_unchanged(self):
        assert markdown_to_telegram_html("Hello world") == "Hello world"

    def test_html_entities_escaped(self):
        assert markdown_to_telegram_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"

    def test_bold_asterisks(self):
        assert markdown_to_telegram_html("**bold**") == "<b>bold</b>"

    def test_underline(self):
        assert markdown_to_telegram_html("__underline__") == "<u>underline</u>"

    def test_italic_asterisk(self):
        assert markdown_to_telegram_html("*italic*") == "<i>italic</i>"

    def test_italic_underscore(self):
        assert markdown_to_telegram_html("_italic_") == "<i>italic</i>"

    def test_inline_code(self):
        assert markdown_to_telegram_html("`code`") == "<code>code</code>"

    def test_strikethrough(self):
        assert markdown_to_telegram_html("~~deleted~~") == "<s>deleted</s>"

    def test_link_basic(self):
        result = markdown_to_telegram_html("[Google](https://google.com)")
        assert result == '<a href="https://google.com">Google</a>'

    def test_link_with_ampersand_no_double_escape(self):
        result = markdown_to_telegram_html("[Search](https://example.com?a=1&b=2)")
        assert "&amp;amp;" not in result
        assert 'href="https://example.com?a=1&amp;b=2"' in result

    def test_link_with_parentheses_in_url(self):
        # Nested parens in URLs are a known regex limitation — the closing )
        # of the markdown link syntax is indistinguishable from ) inside the URL.
        # Verify it still produces a valid link (truncated at first close paren).
        result = markdown_to_telegram_html("[Test](https://en.wikipedia.org/wiki/Test_(disambiguation))")
        assert '<a href="' in result
        assert ">Test</a>" in result

    def test_fenced_code_block(self):
        md = "```python\nprint('hi')\n```"
        result = markdown_to_telegram_html(md)
        assert "<pre>" in result
        assert "language-python" in result

    def test_heading_to_bold(self):
        assert markdown_to_telegram_html("## Title") == "<b>Title</b>"

    def test_mixed_bold_and_link(self):
        result = markdown_to_telegram_html("**See** [here](https://x.com)")
        assert "<b>See</b>" in result
        assert '<a href="https://x.com">here</a>' in result

    def test_code_inside_bold(self):
        result = markdown_to_telegram_html("**use `foo` here**")
        assert "<b>" in result
        assert "<code>foo</code>" in result

    def test_unclosed_code_block(self):
        md = "```\nunfinished"
        result = markdown_to_telegram_html(md)
        assert "<pre>" in result

    def test_html_in_link_display_text_escaped(self):
        result = markdown_to_telegram_html("[<script>](https://evil.com)")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_empty_string(self):
        assert markdown_to_telegram_html("") == ""

    def test_link_with_quotes_in_url(self):
        result = markdown_to_telegram_html('[Click](https://example.com?q="hello")')
        assert "&quot;" in result
        assert "<a href=" in result


class TestCommandTargeting:
    def _group_update(self, text, chat_id=-100123, msg_id=200):
        return {
            "update_id": 1,
            "message": {
                "message_id": msg_id,
                "from": {"id": 67890, "is_bot": False},
                "chat": {"id": chat_id, "type": "supergroup"},
                "text": text,
            },
        }

    def test_command_for_other_bot_ignored_in_group(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")
        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()
        mock_bot_me = MagicMock()
        mock_bot_me.username = "my_bot"
        mock_bot_me.id = 111
        mock_bot.get_me = AsyncMock(return_value=mock_bot_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json=self._group_update("/start@other_bot"))

        assert resp.status_code == 200
        agent.arun.assert_not_called()
        if mock_bot.send_message.called:
            sent_texts = [str(c[0][1]) for c in mock_bot.send_message.call_args_list]
            assert not any("ready to help" in t.lower() for t in sent_texts)

    def test_command_for_our_bot_processed_in_group(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")
        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()
        mock_bot_me = MagicMock()
        mock_bot_me.username = "my_bot"
        mock_bot_me.id = 111
        mock_bot.get_me = AsyncMock(return_value=mock_bot_me)

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json=self._group_update("/start@my_bot"))

        assert resp.status_code == 200
        agent.arun.assert_not_called()
        mock_bot.send_message.assert_called_once()

    def test_command_without_suffix_in_dm(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")
        agent = AsyncMock(id="test-agent")
        mock_bot = AsyncMock()

        dm_update = {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "from": {"id": 67890, "is_bot": False},
                "chat": {"id": 12345, "type": "private"},
                "text": "/start",
            },
        }

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp = client.post("/telegram/webhook", json=dm_update)

        assert resp.status_code == 200
        mock_bot.send_message.assert_called_once()


class TestIdempotencyGuard:
    def test_duplicate_update_id_returns_duplicate(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "reply"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.audio = None
        mock_response.videos = None
        mock_response.files = None
        agent = AsyncMock(id="test-agent")
        agent.arun = AsyncMock(return_value=mock_response)
        mock_bot = AsyncMock()

        update = {
            "update_id": 99999,
            "message": {
                "message_id": 100,
                "from": {"id": 67890, "is_bot": False},
                "chat": {"id": 12345, "type": "private"},
                "text": "Hello",
            },
        }

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            client = _build_telegram_client(agent=agent)
            resp1 = client.post("/telegram/webhook", json=update)
            resp2 = client.post("/telegram/webhook", json=update)

        assert resp1.json()["status"] == "processing"
        assert resp2.json()["status"] == "duplicate"
