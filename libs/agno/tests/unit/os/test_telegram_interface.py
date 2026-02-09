import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.os.interfaces.telegram import Telegram
from agno.os.interfaces.telegram.security import (
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
# router.py (process_message via direct invocation)
# ---------------------------------------------------------------------------


class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_text_message_calls_agent_arun(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Agent reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        with (
            patch(f"{ROUTER_MODULE}.send_chat_action_async", new_callable=AsyncMock) as mock_action,
            patch(f"{ROUTER_MODULE}.send_text_chunked_async", new_callable=AsyncMock) as mock_send,
        ):
            from fastapi import APIRouter

            from agno.os.interfaces.telegram.router import attach_routes

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

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

            mock_action.assert_called_once_with(12345, "typing")
            mock_send.assert_called_once_with(12345, "Agent reply")

    @pytest.mark.asyncio
    async def test_photo_message_downloads_file(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "I see an image"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        with (
            patch(f"{ROUTER_MODULE}.send_chat_action_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_text_chunked_async", new_callable=AsyncMock),
            patch(
                f"{ROUTER_MODULE}.get_file_bytes_async", new_callable=AsyncMock, return_value=b"fake-image-bytes"
            ) as mock_download,
        ):
            from fastapi import APIRouter

            from agno.os.interfaces.telegram.router import attach_routes

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

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

            mock_download.assert_called_once_with("large_id")
            agent.arun.assert_called_once()
            call_kwargs = agent.arun.call_args
            assert call_kwargs[0][0] == "What is this?"
            assert call_kwargs[1]["images"] is not None
            assert len(call_kwargs[1]["images"]) == 1

    @pytest.mark.asyncio
    async def test_error_response_sends_error_message(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "ERROR"
        mock_response.content = "Internal error details"

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        with (
            patch(f"{ROUTER_MODULE}.send_chat_action_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_text_chunked_async", new_callable=AsyncMock) as mock_send,
        ):
            from fastapi import APIRouter

            from agno.os.interfaces.telegram.router import attach_routes

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

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

            mock_send.assert_called_once()
            sent_text = mock_send.call_args[0][1]
            assert "Sorry" in sent_text

    @pytest.mark.asyncio
    async def test_no_chat_id_skips_processing(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock()
        agent.arun = AsyncMock()

        with (
            patch(f"{ROUTER_MODULE}.send_chat_action_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_text_chunked_async", new_callable=AsyncMock),
        ):
            from fastapi import APIRouter

            from agno.os.interfaces.telegram.router import attach_routes

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

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

    @pytest.mark.asyncio
    async def test_unsupported_message_type_skips(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = AsyncMock()
        agent.arun = AsyncMock()

        with (
            patch(f"{ROUTER_MODULE}.send_chat_action_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_text_chunked_async", new_callable=AsyncMock),
        ):
            from fastapi import APIRouter

            from agno.os.interfaces.telegram.router import attach_routes

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

            resp = client.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 100,
                        "from": {"id": 67890},
                        "chat": {"id": 12345, "type": "private"},
                        "sticker": {"file_id": "sticker_id", "width": 512, "height": 512},
                    },
                },
            )
            assert resp.status_code == 200
            agent.arun.assert_not_called()


# ---------------------------------------------------------------------------
# Outbound image handling
# ---------------------------------------------------------------------------


class TestOutboundImages:
    @pytest.mark.asyncio
    async def test_base64_string_image_sent(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        raw_image = b"fake-png-data"
        b64_str = base64.b64encode(raw_image).decode("utf-8")

        mock_image = MagicMock()
        mock_image.content = b64_str

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Here is the image"
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        with (
            patch(f"{ROUTER_MODULE}.send_chat_action_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_text_chunked_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_photo_message_async", new_callable=AsyncMock) as mock_photo,
        ):
            from fastapi import APIRouter

            from agno.os.interfaces.telegram.router import attach_routes

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

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

            mock_photo.assert_called_once()
            call_kwargs = mock_photo.call_args[1]
            assert call_kwargs["chat_id"] == 12345
            assert call_kwargs["photo_bytes"] == raw_image
            assert call_kwargs["caption"] == "Here is the image"

    @pytest.mark.asyncio
    async def test_raw_bytes_image_sent(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        raw_image = b"\x89PNG\r\n\x1a\nfake-png-data"

        mock_image = MagicMock()
        mock_image.content = raw_image

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Here is the image"
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        with (
            patch(f"{ROUTER_MODULE}.send_chat_action_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_text_chunked_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_photo_message_async", new_callable=AsyncMock) as mock_photo,
        ):
            from fastapi import APIRouter

            from agno.os.interfaces.telegram.router import attach_routes

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

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

            mock_photo.assert_called_once()
            call_kwargs = mock_photo.call_args[1]
            # Raw bytes (not valid UTF-8) should be passed through directly
            assert call_kwargs["photo_bytes"] == raw_image

    @pytest.mark.asyncio
    async def test_image_failure_falls_back_to_text(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        raw_image = b"fake-png"
        b64_str = base64.b64encode(raw_image).decode("utf-8")

        mock_image = MagicMock()
        mock_image.content = b64_str

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Fallback text"
        mock_response.reasoning_content = None
        mock_response.images = [mock_image]

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        with (
            patch(f"{ROUTER_MODULE}.send_chat_action_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_text_chunked_async", new_callable=AsyncMock) as mock_text,
            patch(
                f"{ROUTER_MODULE}.send_photo_message_async", new_callable=AsyncMock, side_effect=Exception("API error")
            ),
        ):
            from fastapi import APIRouter

            from agno.os.interfaces.telegram.router import attach_routes

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

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
            mock_text.assert_called_once_with(12345, "Fallback text")


# ---------------------------------------------------------------------------
# Message splitting (now in utils, but test end-to-end)
# ---------------------------------------------------------------------------


class TestMessageSplitting:
    @pytest.mark.asyncio
    async def test_sends_via_chunked(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Short reply"
        mock_response.reasoning_content = None
        mock_response.images = None

        agent = AsyncMock()
        agent.arun = AsyncMock(return_value=mock_response)

        with (
            patch(f"{ROUTER_MODULE}.send_chat_action_async", new_callable=AsyncMock),
            patch(f"{ROUTER_MODULE}.send_text_chunked_async", new_callable=AsyncMock) as mock_send,
        ):
            from fastapi import APIRouter

            from agno.os.interfaces.telegram.router import attach_routes

            router = APIRouter(prefix="/telegram")
            attach_routes(router=router, agent=agent)

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

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

            mock_send.assert_called_once_with(12345, "Short reply")


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
