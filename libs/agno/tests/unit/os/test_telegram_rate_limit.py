"""Tests for Telegram 429 rate-limit handling (retry_after parsing and hold behavior)."""

import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

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

from agno.os.interfaces.telegram.state import StreamState, _RETRY_AFTER_RE  # noqa: E402


# ---------------------------------------------------------------------------
# Regex parsing
# ---------------------------------------------------------------------------


class TestRetryAfterRegex:
    """Tests for the _RETRY_AFTER_RE regex that extracts retry_after from error messages."""

    def test_parses_standard_429_message(self):
        msg = "Error code: 429. Description: Too Many Requests: retry after 33"
        match = _RETRY_AFTER_RE.search(msg)
        assert match is not None
        assert match.group(1) == "33"

    def test_parses_case_insensitive(self):
        msg = "Too Many Requests: Retry After 15"
        match = _RETRY_AFTER_RE.search(msg)
        assert match is not None
        assert match.group(1) == "15"

    def test_parses_lowercase(self):
        msg = "retry after 5"
        match = _RETRY_AFTER_RE.search(msg)
        assert match is not None
        assert match.group(1) == "5"

    def test_no_match_on_unrelated_error(self):
        msg = "Error code: 400. Description: Bad Request: TOPIC_CLOSED"
        match = _RETRY_AFTER_RE.search(msg)
        assert match is None

    def test_no_match_on_message_not_modified(self):
        msg = "Bad Request: message is not modified"
        match = _RETRY_AFTER_RE.search(msg)
        assert match is None


# ---------------------------------------------------------------------------
# StreamState rate-limit hold
# ---------------------------------------------------------------------------


class TestStreamStateRateLimit:
    """Tests for StreamState._rate_limited_until hold behavior."""

    def _make_state(self) -> StreamState:
        bot = MagicMock()
        return StreamState(
            bot=bot,
            chat_id=123,
            reply_to=None,
            message_thread_id=None,
            entity_type="agent",
            error_message="Error occurred",
        )

    def test_initial_hold_is_zero(self):
        state = self._make_state()
        assert state._rate_limited_until == 0.0

    def test_send_or_edit_skips_when_rate_limited(self):
        """send_or_edit should return immediately without calling _send_new or _edit."""
        state = self._make_state()
        state._rate_limited_until = time.monotonic() + 60  # hold for 60s
        state.sent_message_id = 42  # simulate existing message

        # Should be a no-op — no exception, no bot calls
        import asyncio

        asyncio.get_event_loop().run_until_complete(state.send_or_edit("<p>hello</p>"))

        # bot.edit_message_text should NOT have been called
        state.bot.edit_message_text.assert_not_called()
        state.bot.send_message.assert_not_called()

    def test_edit_skips_when_rate_limited(self):
        """_edit should return immediately when in a rate-limit hold."""
        state = self._make_state()
        state.sent_message_id = 42
        state._rate_limited_until = time.monotonic() + 30

        import asyncio

        asyncio.get_event_loop().run_until_complete(state._edit("<p>hello</p>"))

        state.bot.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_parses_429_and_sets_hold(self):
        """_edit should parse retry_after from a 429 and set the hold."""
        state = self._make_state()
        state.sent_message_id = 42

        exc = Exception("Error code: 429. Description: Too Many Requests: retry after 25")
        state.bot.edit_message_text = AsyncMock(side_effect=exc)

        assert state._rate_limited_until == 0.0

        await state._edit("<p>hello</p>")

        # Hold should be set to ~now + 25
        assert state._rate_limited_until > time.monotonic() + 20
        assert state._rate_limited_until < time.monotonic() + 30

    @pytest.mark.asyncio
    async def test_edit_ignores_non_429_error(self):
        """_edit should not set a hold for non-429 errors."""
        state = self._make_state()
        state.sent_message_id = 42

        exc = Exception("Error code: 400. Description: Bad Request: message is too long")
        state.bot.edit_message_text = AsyncMock(side_effect=exc)

        await state._edit("<p>hello</p>")

        assert state._rate_limited_until == 0.0

    @pytest.mark.asyncio
    async def test_edit_ignores_message_not_modified(self):
        """_edit should silently return for 'message is not modified' errors."""
        state = self._make_state()
        state.sent_message_id = 42

        exc = Exception("Bad Request: message is not modified")
        state.bot.edit_message_text = AsyncMock(side_effect=exc)

        await state._edit("<p>hello</p>")

        # No hold set
        assert state._rate_limited_until == 0.0

    @pytest.mark.asyncio
    async def test_send_or_edit_works_after_hold_expires(self):
        """After the hold expires, send_or_edit should function normally."""
        state = self._make_state()
        # Set a hold that already expired
        state._rate_limited_until = time.monotonic() - 1

        msg_mock = MagicMock()
        msg_mock.message_id = 99
        state.bot.send_message = AsyncMock(return_value=msg_mock)

        await state.send_or_edit("<p>hello</p>")

        state.bot.send_message.assert_called_once()
        assert state.sent_message_id == 99
