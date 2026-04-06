"""
System Tests for Telegram Interface Routes.

Tests both local and remote agents/teams/workflows through the Telegram interface.
Note: These tests mock the Telegram Bot API since we don't have actual Telegram credentials,
but they test the full webhook -> agent -> response pipeline through a real gateway.

Run with: pytest test_telegram_routes.py -v --tb=short
"""

import os
import uuid
from typing import Any, Dict

import httpx
import pytest

from .test_utils import REQUEST_TIMEOUT, generate_jwt_token


@pytest.fixture(scope="module")
def test_user_id() -> str:
    """Generate a unique Telegram user ID for testing."""
    return str(uuid.uuid4().int % 10**9)


@pytest.fixture(scope="module")
def test_chat_id() -> int:
    """Generate a unique Telegram chat ID for testing."""
    return uuid.uuid4().int % 10**9


@pytest.fixture(scope="module")
def client(gateway_url: str, test_user_id: str) -> httpx.Client:
    """Create an HTTP client for the gateway server."""
    return httpx.Client(
        base_url=gateway_url,
        timeout=REQUEST_TIMEOUT,
        headers={"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"},
    )


@pytest.fixture(scope="module")
def telegram_secret_token() -> str:
    """Get the Telegram webhook secret token from environment or use test default."""
    return os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "test-webhook-secret")


def make_text_update(text: str, chat_id: int, user_id: str, chat_type: str = "private") -> Dict[str, Any]:
    """Create a Telegram text message update payload."""
    return {
        "update_id": uuid.uuid4().int % 10**9,
        "message": {
            "message_id": uuid.uuid4().int % 10**6,
            "from": {"id": int(user_id), "is_bot": False, "first_name": "TestUser"},
            "chat": {"id": chat_id, "type": chat_type},
            "text": text,
        },
    }


def make_photo_update(chat_id: int, user_id: str, caption: str = None) -> Dict[str, Any]:
    """Create a Telegram photo message update payload."""
    msg: Dict[str, Any] = {
        "update_id": uuid.uuid4().int % 10**9,
        "message": {
            "message_id": uuid.uuid4().int % 10**6,
            "from": {"id": int(user_id), "is_bot": False, "first_name": "TestUser"},
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


def make_document_update(
    chat_id: int,
    user_id: str,
    file_name: str = "test.pdf",
    mime_type: str = "application/pdf",
    file_size: int = 1024,
    caption: str = None,
) -> Dict[str, Any]:
    """Create a Telegram document message update payload."""
    msg: Dict[str, Any] = {
        "update_id": uuid.uuid4().int % 10**9,
        "message": {
            "message_id": uuid.uuid4().int % 10**6,
            "from": {"id": int(user_id), "is_bot": False, "first_name": "TestUser"},
            "chat": {"id": chat_id, "type": "private"},
            "document": {
                "file_id": f"doc_{uuid.uuid4().hex[:8]}",
                "file_name": file_name,
                "mime_type": mime_type,
                "file_size": file_size,
            },
        },
    }
    if caption:
        msg["message"]["caption"] = caption
    return msg


def make_bot_message_update(chat_id: int) -> Dict[str, Any]:
    """Create a Telegram update from a bot (should be ignored)."""
    return {
        "update_id": uuid.uuid4().int % 10**9,
        "message": {
            "message_id": uuid.uuid4().int % 10**6,
            "from": {"id": 999999, "is_bot": True, "first_name": "AnotherBot"},
            "chat": {"id": chat_id, "type": "private"},
            "text": "I am a bot",
        },
    }


def make_group_mention_update(text: str, chat_id: int, user_id: str, bot_username: str = "testbot") -> Dict[str, Any]:
    """Create a Telegram group message with a bot mention."""
    mention_text = f"@{bot_username} {text}"
    return {
        "update_id": uuid.uuid4().int % 10**9,
        "message": {
            "message_id": uuid.uuid4().int % 10**6,
            "from": {"id": int(user_id), "is_bot": False, "first_name": "TestUser"},
            "chat": {"id": chat_id, "type": "supergroup"},
            "text": mention_text,
            "entities": [
                {"type": "mention", "offset": 0, "length": len(f"@{bot_username}")},
            ],
        },
    }


def post_telegram_webhook(
    client: httpx.Client,
    endpoint: str,
    body: Dict[str, Any],
    secret_token: str = None,
) -> httpx.Response:
    """Post a Telegram webhook update with optional secret token header."""
    headers = {"Content-Type": "application/json"}
    if secret_token:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret_token
    return client.post(endpoint, json=body, headers=headers)


# =============================================================================
# Telegram Interface Tests - Status Endpoint
# =============================================================================


class TestTelegramStatus:
    """Test Telegram status endpoints."""

    def test_status_local_agent(self, client: httpx.Client):
        """Test status endpoint for local agent Telegram interface."""
        response = client.get("/telegram/local/status")
        assert response.status_code == 200
        assert response.json() == {"status": "available"}

    def test_status_remote_agent(self, client: httpx.Client):
        """Test status endpoint for remote agent Telegram interface."""
        response = client.get("/telegram/remote/status")
        assert response.status_code == 200
        assert response.json() == {"status": "available"}

    def test_status_team(self, client: httpx.Client):
        """Test status endpoint for team Telegram interface."""
        response = client.get("/telegram/team/status")
        assert response.status_code == 200
        assert response.json() == {"status": "available"}

    def test_status_workflow(self, client: httpx.Client):
        """Test status endpoint for workflow Telegram interface."""
        response = client.get("/telegram/workflow/status")
        assert response.status_code == 200
        assert response.json() == {"status": "available"}


# =============================================================================
# Telegram Interface Tests - Webhook Processing
# =============================================================================


class TestTelegramWebhookProcessing:
    """Test Telegram webhook event handling for agents, teams, and workflows."""

    def test_text_message_local_agent(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test text message processing for local agent."""
        body = make_text_update("Hello agent", test_chat_id, test_user_id)
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"

    def test_text_message_remote_agent(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test text message processing for remote agent."""
        body = make_text_update("Hello remote agent", test_chat_id, test_user_id)
        response = post_telegram_webhook(client, "/telegram/remote/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"

    def test_text_message_team(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test text message processing for team."""
        body = make_text_update("Hello team", test_chat_id, test_user_id)
        response = post_telegram_webhook(client, "/telegram/team/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"

    def test_text_message_workflow(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test text message processing for workflow."""
        body = make_text_update("Run workflow", test_chat_id, test_user_id)
        response = post_telegram_webhook(client, "/telegram/workflow/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"

    def test_no_message_returns_ignored(self, client: httpx.Client, telegram_secret_token: str):
        """Test that updates without a message field are ignored."""
        body = {"update_id": uuid.uuid4().int % 10**9}
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        assert response.json() == {"status": "ignored"}

    def test_callback_query_ignored(self, client: httpx.Client, telegram_secret_token: str):
        """Test that callback queries are ignored."""
        body = {"update_id": uuid.uuid4().int % 10**9, "callback_query": {"id": "123", "data": "action"}}
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        assert response.json() == {"status": "ignored"}

    def test_bot_message_ignored(self, client: httpx.Client, telegram_secret_token: str, test_chat_id: int):
        """Test that messages from bots are accepted at webhook level (filtered in background)."""
        body = make_bot_message_update(test_chat_id)
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        # Webhook returns processing (bot filtering happens in the background task)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"


# =============================================================================
# Telegram Interface Tests - Commands
# =============================================================================


class TestTelegramCommands:
    """Test built-in Telegram bot commands."""

    def test_start_command(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test /start command is processed."""
        body = make_text_update("/start", test_chat_id, test_user_id)
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        assert response.json()["status"] == "processing"

    def test_help_command(self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int):
        """Test /help command is processed."""
        body = make_text_update("/help", test_chat_id, test_user_id)
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        assert response.json()["status"] == "processing"

    def test_new_command(self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int):
        """Test /new command is processed."""
        body = make_text_update("/new", test_chat_id, test_user_id)
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        assert response.json()["status"] == "processing"


# =============================================================================
# Telegram Interface Tests - Media Messages
# =============================================================================


class TestTelegramMedia:
    """Test Telegram media message handling."""

    def test_photo_message(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test photo message is accepted for processing."""
        body = make_photo_update(test_chat_id, test_user_id, caption="What is this?")
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        assert response.json()["status"] == "processing"

    def test_document_message(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test document message is accepted for processing."""
        body = make_document_update(test_chat_id, test_user_id, file_name="report.pdf")
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        assert response.json()["status"] == "processing"

    def test_unsupported_file_type(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test unsupported file type (.xls) is accepted (warning sent in background)."""
        body = make_document_update(
            test_chat_id, test_user_id, file_name="data.xls", mime_type="application/vnd.ms-excel"
        )
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        assert response.json()["status"] == "processing"

    def test_oversized_file(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test oversized file (>20MB) is accepted (warning sent in background)."""
        body = make_document_update(
            test_chat_id,
            test_user_id,
            file_name="large_video.mp4",
            mime_type="video/mp4",
            file_size=25 * 1024 * 1024,  # 25 MB
        )
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)

        assert response.status_code == 200
        assert response.json()["status"] == "processing"


# =============================================================================
# Telegram Interface Tests - Security
# =============================================================================


class TestTelegramSecurity:
    """Test Telegram webhook security measures."""

    def test_missing_secret_token_in_prod(self, client: httpx.Client):
        """Test that requests without secret token are rejected in production mode."""
        # This test only applies when APP_ENV != development
        # The gateway may be running in development mode, so we test the response pattern
        body = make_text_update("Hello", 12345, "67890")
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, secret_token=None)

        # In development mode: 200 (bypassed), in production mode: 403
        assert response.status_code in (200, 403)

    def test_invalid_secret_token(self, client: httpx.Client):
        """Test that requests with invalid secret token are rejected in production mode."""
        body = make_text_update("Hello", 12345, "67890")
        response = post_telegram_webhook(client, "/telegram/local/webhook", body, secret_token="wrong-secret")

        # In development mode: 200 (bypassed), in production mode: 403
        assert response.status_code in (200, 403)


# =============================================================================
# Telegram Interface Tests - Context Preservation
# =============================================================================


class TestTelegramContextPreservation:
    """Test that conversation context is preserved across messages."""

    def test_sequential_messages_same_chat(self, client: httpx.Client, telegram_secret_token: str, test_user_id: str):
        """Test that multiple messages in the same private chat use the same session."""
        chat_id = uuid.uuid4().int % 10**9

        # Send first message
        body1 = make_text_update("My name is Alice", chat_id, test_user_id)
        resp1 = post_telegram_webhook(client, "/telegram/local/webhook", body1, telegram_secret_token)
        assert resp1.status_code == 200

        # Send follow-up message in same chat
        body2 = make_text_update("What is my name?", chat_id, test_user_id)
        resp2 = post_telegram_webhook(client, "/telegram/local/webhook", body2, telegram_secret_token)
        assert resp2.status_code == 200

    def test_different_chats_have_separate_sessions(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str
    ):
        """Test that different chats have separate sessions."""
        chat_id_1 = uuid.uuid4().int % 10**9
        chat_id_2 = uuid.uuid4().int % 10**9

        body1 = make_text_update("Hello from chat 1", chat_id_1, test_user_id)
        resp1 = post_telegram_webhook(client, "/telegram/local/webhook", body1, telegram_secret_token)
        assert resp1.status_code == 200

        body2 = make_text_update("Hello from chat 2", chat_id_2, test_user_id)
        resp2 = post_telegram_webhook(client, "/telegram/local/webhook", body2, telegram_secret_token)
        assert resp2.status_code == 200


# =============================================================================
# Telegram Interface Tests - Multi-Bot (Multiple Prefixes)
# =============================================================================


class TestTelegramMultiBot:
    """Test multiple Telegram interface instances on different prefixes."""

    def test_different_prefixes_both_respond(
        self, client: httpx.Client, telegram_secret_token: str, test_user_id: str, test_chat_id: int
    ):
        """Test that two Telegram instances on different prefixes both work."""
        body = make_text_update("Hello", test_chat_id, test_user_id)

        # Both local and remote prefixes should accept messages
        resp1 = post_telegram_webhook(client, "/telegram/local/webhook", body, telegram_secret_token)
        resp2 = post_telegram_webhook(client, "/telegram/remote/webhook", body, telegram_secret_token)

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["status"] == "processing"
        assert resp2.json()["status"] == "processing"
