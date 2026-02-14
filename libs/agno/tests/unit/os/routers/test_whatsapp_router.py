import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


def _build_app(agent_mock: Mock) -> FastAPI:
    from agno.os.interfaces.whatsapp.router import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(router, agent=agent_mock)
    app.include_router(router)
    return app


def _make_agent_mock():
    agent_mock = AsyncMock()
    agent_mock.arun = AsyncMock(
        return_value=Mock(
            status="OK",
            content="done",
            reasoning_content=None,
            images=None,
            files=None,
            videos=None,
            audio=None,
        )
    )
    return agent_mock


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
    import asyncio

    elapsed = 0.0
    while not agent_mock.arun.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1


# === Webhook Verification (GET) ===


def test_webhook_verification():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools", return_value=Mock()),
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
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools", return_value=Mock()),
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
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools", return_value=Mock()),
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
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools") as mock_tools_cls,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        mock_tools = Mock()
        mock_tools.send_text_message = Mock(return_value='{"ok": true}')
        mock_tools_cls.return_value = mock_tools

        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook("text", text={"body": "hello world"})
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert call_args[0][0] == "hello world"
        assert call_args.kwargs["user_id"] == "sender_phone"
        assert call_args.kwargs["session_id"] == "wa:sender_phone"


@pytest.mark.asyncio
async def test_image_message_processing():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools") as mock_tools_cls,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch("agno.os.interfaces.whatsapp.router.get_media_async", new_callable=AsyncMock) as mock_get_media,
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        mock_tools = Mock()
        mock_tools.send_text_message = Mock(return_value='{"ok": true}')
        mock_tools_cls.return_value = mock_tools
        mock_get_media.return_value = b"\x89PNG"

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


@pytest.mark.asyncio
async def test_interactive_button_reply():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools") as mock_tools_cls,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        mock_tools = Mock()
        mock_tools.send_text_message = Mock(return_value='{"ok": true}')
        mock_tools_cls.return_value = mock_tools

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
        assert "[Button Selected] Yes (id: btn_yes)" == call_args[0][0]


@pytest.mark.asyncio
async def test_interactive_list_reply():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools") as mock_tools_cls,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        mock_tools = Mock()
        mock_tools.send_text_message = Mock(return_value='{"ok": true}')
        mock_tools_cls.return_value = mock_tools

        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook(
            "interactive",
            interactive={"type": "list_reply", "list_reply": {"id": "row_1", "title": "Option A"}},
        )
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert "[List Selected] Option A (id: row_1)" == call_args[0][0]


@pytest.mark.asyncio
async def test_location_message():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools") as mock_tools_cls,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        mock_tools = Mock()
        mock_tools.send_text_message = Mock(return_value='{"ok": true}')
        mock_tools_cls.return_value = mock_tools

        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook(
            "location",
            location={"latitude": "37.7749", "longitude": "-122.4194", "name": "San Francisco"},
        )
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert "[Location] San Francisco (37.7749, -122.4194)" == call_args[0][0]


@pytest.mark.asyncio
async def test_reaction_message():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools") as mock_tools_cls,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        mock_tools = Mock()
        mock_tools.send_text_message = Mock(return_value='{"ok": true}')
        mock_tools_cls.return_value = mock_tools

        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook(
            "reaction",
            reaction={"message_id": "wamid.orig", "emoji": "\U0001f44d"},
        )
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert "\U0001f44d" in call_args[0][0]
        assert "wamid.orig" in call_args[0][0]


@pytest.mark.asyncio
async def test_contacts_message():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools") as mock_tools_cls,
        patch("agno.os.interfaces.whatsapp.router.typing_indicator_async", new_callable=AsyncMock),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        mock_tools = Mock()
        mock_tools.send_text_message = Mock(return_value='{"ok": true}')
        mock_tools_cls.return_value = mock_tools

        app = _build_app(agent_mock)
        client = TestClient(app)
        body = _make_whatsapp_webhook(
            "contacts",
            contacts=[{"name": {"formatted_name": "John Doe"}}],
        )
        response = client.post("/webhook", json=body)
        assert response.status_code == 200

        await _wait_for_agent_call(agent_mock)

        agent_mock.arun.assert_called_once()
        call_args = agent_mock.arun.call_args
        assert "[Contacts Shared] John Doe" == call_args[0][0]


def test_non_whatsapp_object_ignored():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools", return_value=Mock()),
        patch.dict("os.environ", WHATSAPP_ENV),
    ):
        app = _build_app(agent_mock)
        client = TestClient(app)
        body = {"object": "instagram", "entry": []}
        response = client.post("/webhook", json=body)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"


def test_empty_messages_no_crash():
    agent_mock = _make_agent_mock()
    with (
        patch("agno.os.interfaces.whatsapp.router.validate_webhook_signature", return_value=True),
        patch("agno.os.interfaces.whatsapp.router.WhatsAppTools", return_value=Mock()),
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
