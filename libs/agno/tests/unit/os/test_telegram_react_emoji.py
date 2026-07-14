"""Tests for Telegram react_emoji feature (eye reaction while processing)."""

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
    telebot_types = types.ModuleType("telebot.types")

    class AsyncTeleBot:
        def __init__(self, token=None):
            self.token = token

    class TeleBot:
        def __init__(self, token=None):
            self.token = token

    class ApiTelegramException(Exception):
        pass

    class ReactionTypeEmoji:
        def __init__(self, emoji: str = ""):
            self.emoji = emoji
            self.type = "emoji"

    telebot.TeleBot = TeleBot
    telebot_async.AsyncTeleBot = AsyncTeleBot
    telebot_apihelper.ApiTelegramException = ApiTelegramException
    telebot_types.ReactionTypeEmoji = ReactionTypeEmoji
    sys.modules.setdefault("telebot", telebot)
    sys.modules.setdefault("telebot.async_telebot", telebot_async)
    sys.modules.setdefault("telebot.apihelper", telebot_apihelper)
    sys.modules.setdefault("telebot.types", telebot_types)


_install_fake_telebot()

from agno.os.interfaces.telegram import Telegram  # noqa: E402

ROUTER_MODULE = "agno.os.interfaces.telegram.router"


def _make_agent():
    mock_response = MagicMock()
    mock_response.status = "COMPLETED"
    mock_response.content = "Agent reply"
    mock_response.reasoning_content = None
    mock_response.images = None

    agent = AsyncMock(id="test-agent")
    agent.arun = AsyncMock(return_value=mock_response)
    return agent


def _text_update(text="Hello", chat_id=12345, user_id=67890, message_id=100):
    return {
        "update_id": 1,
        "message": {
            "message_id": message_id,
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def _build_client(agent, react_emoji=None):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
    monkeypatch.setenv("APP_ENV", "development")

    tg = Telegram(agent=agent, react_emoji=react_emoji)
    app = FastAPI()
    app.include_router(tg.get_router())

    monkeypatch.undo()
    return app


class TestReactEmojiReaction:
    """Tests that react_emoji adds and removes reactions correctly."""

    def test_reaction_added_and_removed_on_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = _make_agent()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            tg = Telegram(agent=agent, react_emoji="\U0001f440", streaming=False)
            app = FastAPI()
            app.include_router(tg.get_router())
            client = TestClient(app)

            resp = client.post("/telegram/webhook", json=_text_update())

        assert resp.status_code == 200
        # set_message_reaction should be called: once to add, once to remove
        assert mock_bot.set_message_reaction.call_count == 2

        # First call: add reaction with emoji
        add_call = mock_bot.set_message_reaction.call_args_list[0]
        assert add_call.kwargs["chat_id"] == 12345
        assert add_call.kwargs["message_id"] == 100
        assert len(add_call.kwargs["reaction"]) == 1
        assert add_call.kwargs["reaction"][0].emoji == "\U0001f440"

        # Second call: remove reaction (empty list)
        remove_call = mock_bot.set_message_reaction.call_args_list[1]
        assert remove_call.kwargs["chat_id"] == 12345
        assert remove_call.kwargs["message_id"] == 100
        assert remove_call.kwargs["reaction"] == []

    def test_no_reaction_when_react_emoji_is_none(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = _make_agent()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            tg = Telegram(agent=agent, streaming=False)
            app = FastAPI()
            app.include_router(tg.get_router())
            client = TestClient(app)

            resp = client.post("/telegram/webhook", json=_text_update())

        assert resp.status_code == 200
        mock_bot.set_message_reaction.assert_not_called()

    def test_reaction_removed_on_empty_message(self, monkeypatch):
        """Reaction should be cleaned up even when message has no processable content."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = _make_agent()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            with patch(f"{ROUTER_MODULE}.extract_message_payload", return_value=None):
                tg = Telegram(agent=agent, react_emoji="\U0001f440", streaming=False)
                app = FastAPI()
                app.include_router(tg.get_router())
                client = TestClient(app)

                resp = client.post("/telegram/webhook", json=_text_update())

        assert resp.status_code == 200
        # Should be called once (add) then once more (remove on early return)
        assert mock_bot.set_message_reaction.call_count == 2
        remove_call = mock_bot.set_message_reaction.call_args_list[-1]
        assert remove_call.kwargs["reaction"] == []

    def test_reaction_failure_is_silent(self, monkeypatch):
        """Reaction errors should not break message processing."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = _make_agent()
        mock_bot = AsyncMock()
        # First call (add reaction) raises, second (remove) also raises
        mock_bot.set_message_reaction = AsyncMock(side_effect=Exception("Forbidden: bot is not a member"))

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            tg = Telegram(agent=agent, react_emoji="\U0001f440", streaming=False)
            app = FastAPI()
            app.include_router(tg.get_router())
            client = TestClient(app)

            resp = client.post("/telegram/webhook", json=_text_update())

        # Message should still be processed successfully
        assert resp.status_code == 200
        assert resp.json() == {"status": "processing"}
        agent.arun.assert_called_once()

    def test_custom_emoji(self, monkeypatch):
        """Any emoji string should work, not just the eye emoji."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = _make_agent()
        mock_bot = AsyncMock()

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            tg = Telegram(agent=agent, react_emoji="\u26a1", streaming=False)
            app = FastAPI()
            app.include_router(tg.get_router())
            client = TestClient(app)

            resp = client.post("/telegram/webhook", json=_text_update())

        assert resp.status_code == 200
        add_call = mock_bot.set_message_reaction.call_args_list[0]
        assert add_call.kwargs["reaction"][0].emoji == "\u26a1"

    def test_reaction_removed_on_no_text_no_media(self, monkeypatch):
        """Reaction should be removed when message has no text and no media."""
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("APP_ENV", "development")

        agent = _make_agent()
        mock_bot = AsyncMock()

        update = {
            "update_id": 1,
            "message": {
                "message_id": 200,
                "from": {"id": 67890, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 12345, "type": "private"},
                # No text, no photo, no audio, no video, no document
            },
        }

        with patch(f"{ROUTER_MODULE}.AsyncTeleBot", return_value=mock_bot):
            with patch(
                f"{ROUTER_MODULE}.extract_message_payload",
                return_value={"message": "", "warning": None},
            ):
                tg = Telegram(agent=agent, react_emoji="\U0001f440", streaming=False)
                app = FastAPI()
                app.include_router(tg.get_router())
                client = TestClient(app)

                resp = client.post("/telegram/webhook", json=update)

        assert resp.status_code == 200
        # add + remove
        assert mock_bot.set_message_reaction.call_count == 2
        remove_call = mock_bot.set_message_reaction.call_args_list[-1]
        assert remove_call.kwargs["reaction"] == []


class TestReactEmojiPassedToRouter:
    """Tests that Telegram class correctly passes react_emoji to the router."""

    def test_react_emoji_stored_on_instance(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent, react_emoji="\U0001f440")
        assert tg.react_emoji == "\U0001f440"

    def test_react_emoji_defaults_to_none(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        agent = MagicMock()
        tg = Telegram(agent=agent)
        assert tg.react_emoji is None
