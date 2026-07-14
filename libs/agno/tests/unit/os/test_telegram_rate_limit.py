"""Tests for Telegram 429 rate-limit handling during streaming edits."""

import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


def _install_fake_telebot():
    telebot = types.ModuleType("telebot")
    telebot_async = types.ModuleType("telebot.async_telebot")

    class AsyncTeleBot:
        def __init__(self, token=None):
            self.token = token

    class TeleBot:
        def __init__(self, token=None):
            self.token = token

    telebot.TeleBot = TeleBot
    telebot_async.AsyncTeleBot = AsyncTeleBot
    sys.modules.setdefault("telebot", telebot)
    sys.modules.setdefault("telebot.async_telebot", telebot_async)


_install_fake_telebot()

from agno.os.interfaces.telegram.state import StreamState  # noqa: E402


def _make_state() -> StreamState:
    return StreamState(
        bot=MagicMock(),
        chat_id=123,
        reply_to=None,
        message_thread_id=None,
        entity_type="agent",
        error_message="Error occurred",
    )


def _make_429(retry_after: int) -> Exception:
    """Build a fake ApiTelegramException matching pyTelegramBotAPI's attribute shape."""
    exc = Exception(f"Too Many Requests: retry after {retry_after}")
    exc.error_code = 429  # type: ignore[attr-defined]
    exc.result_json = {"ok": False, "error_code": 429, "parameters": {"retry_after": retry_after}}  # type: ignore[attr-defined]
    return exc


def _make_non_429(error_code: int, description: str) -> Exception:
    exc = Exception(f"Error code: {error_code}. Description: {description}")
    exc.error_code = error_code  # type: ignore[attr-defined]
    exc.result_json = {"ok": False, "error_code": error_code, "description": description}  # type: ignore[attr-defined]
    return exc


@pytest.mark.asyncio
async def test_edit_sets_deadline_on_429():
    state = _make_state()
    state.sent_message_id = 42
    state.bot.edit_message_text = AsyncMock(side_effect=_make_429(25))

    await state._edit("<p>hello</p>")

    assert state._rate_limited_until > time.monotonic() + 20
    assert state._rate_limited_until < time.monotonic() + 30


@pytest.mark.asyncio
async def test_edit_ignores_non_429_error():
    state = _make_state()
    state.sent_message_id = 42
    state.bot.edit_message_text = AsyncMock(side_effect=_make_non_429(400, "Bad Request: message is too long"))

    await state._edit("<p>hello</p>")

    assert state._rate_limited_until == 0.0


@pytest.mark.asyncio
async def test_edit_ignores_message_not_modified():
    state = _make_state()
    state.sent_message_id = 42
    state.bot.edit_message_text = AsyncMock(side_effect=_make_non_429(400, "Bad Request: message is not modified"))

    await state._edit("<p>hello</p>")

    assert state._rate_limited_until == 0.0


@pytest.mark.asyncio
async def test_send_or_edit_skips_when_deadline_active():
    state = _make_state()
    state.sent_message_id = 42
    state._rate_limited_until = time.monotonic() + 60

    await state.send_or_edit("<p>hello</p>")

    state.bot.edit_message_text.assert_not_called()
    state.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_or_edit_resumes_after_deadline_expires():
    state = _make_state()
    state._rate_limited_until = time.monotonic() - 1

    msg_mock = MagicMock()
    msg_mock.message_id = 99
    state.bot.send_message = AsyncMock(return_value=msg_mock)

    await state.send_or_edit("<p>hello</p>")

    state.bot.send_message.assert_called_once()
    assert state.sent_message_id == 99


@pytest.mark.asyncio
async def test_finalize_waits_for_deadline():
    state = _make_state()
    state.accumulated_content = "Hello world"
    state.sent_message_id = 42
    state._rate_limited_until = time.monotonic() + 0.1
    state.bot.edit_message_text = AsyncMock()

    start = time.monotonic()
    await state.finalize()
    elapsed = time.monotonic() - start

    assert elapsed >= 0.05
    state.bot.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_proceeds_immediately_without_deadline():
    state = _make_state()
    state.accumulated_content = "Hello world"
    state.sent_message_id = 42
    state.bot.edit_message_text = AsyncMock()

    start = time.monotonic()
    await state.finalize()
    elapsed = time.monotonic() - start

    assert elapsed < 0.05
    state.bot.edit_message_text.assert_called_once()
