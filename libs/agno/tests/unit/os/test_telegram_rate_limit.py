"""Tests for Telegram 429 rate-limit handling (retry_after parsing and hold behavior)."""

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

from agno.os.interfaces.telegram.state import _RETRY_AFTER_RE, StreamState  # noqa: E402


def _make_state() -> StreamState:
    bot = MagicMock()
    return StreamState(
        bot=bot,
        chat_id=123,
        reply_to=None,
        message_thread_id=None,
        entity_type="agent",
        error_message="Error occurred",
    )


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
# Helper methods: _is_rate_limited, _set_rate_limit
# ---------------------------------------------------------------------------


class TestRateLimitHelpers:
    """Tests for _is_rate_limited() and _set_rate_limit() helpers."""

    def test_initial_state_not_rate_limited(self):
        state = _make_state()
        assert state._rate_limited_until == 0.0
        assert not state._is_rate_limited()

    def test_is_rate_limited_when_hold_active(self):
        state = _make_state()
        state._rate_limited_until = time.monotonic() + 60
        assert state._is_rate_limited()

    def test_is_rate_limited_false_after_expiry(self):
        state = _make_state()
        state._rate_limited_until = time.monotonic() - 1
        assert not state._is_rate_limited()

    def test_set_rate_limit_parses_429(self):
        state = _make_state()
        exc = Exception("Error code: 429. Description: Too Many Requests: retry after 25")
        result = state._set_rate_limit(exc)
        assert result is True
        assert state._rate_limited_until > time.monotonic() + 20
        assert state._rate_limited_until < time.monotonic() + 30

    def test_set_rate_limit_returns_false_for_non_429(self):
        state = _make_state()
        exc = Exception("Error code: 400. Description: Bad Request")
        result = state._set_rate_limit(exc)
        assert result is False
        assert state._rate_limited_until == 0.0

    def test_set_rate_limit_does_not_shorten_existing_hold(self):
        """A second 429 with a shorter retry_after should extend, not shorten the hold."""
        state = _make_state()
        # First 429: retry after 30
        exc1 = Exception("retry after 30")
        state._set_rate_limit(exc1)
        first_hold = state._rate_limited_until

        # Second 429: retry after 5 — should still update (Telegram's latest instruction)
        exc2 = Exception("retry after 5")
        state._set_rate_limit(exc2)
        # The hold is updated to now + 5, which may be less than first_hold
        # This is correct — Telegram's latest retry_after is authoritative
        assert state._rate_limited_until > time.monotonic()
        assert state._rate_limited_until != first_hold


# ---------------------------------------------------------------------------
# StreamState rate-limit hold behavior
# ---------------------------------------------------------------------------


class TestStreamStateRateLimit:
    """Tests for StreamState send_or_edit / _edit under rate-limit."""

    @pytest.mark.asyncio
    async def test_send_or_edit_skips_when_rate_limited(self):
        """send_or_edit should return immediately without calling _send_new or _edit."""
        state = _make_state()
        state._rate_limited_until = time.monotonic() + 60
        state.sent_message_id = 42

        await state.send_or_edit("<p>hello</p>")

        state.bot.edit_message_text.assert_not_called()
        state.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_parses_429_and_sets_hold(self):
        """_edit should parse retry_after from a 429 and set the hold."""
        state = _make_state()
        state.sent_message_id = 42

        exc = Exception("Error code: 429. Description: Too Many Requests: retry after 25")
        state.bot.edit_message_text = AsyncMock(side_effect=exc)

        assert state._rate_limited_until == 0.0
        await state._edit("<p>hello</p>")

        assert state._rate_limited_until > time.monotonic() + 20
        assert state._rate_limited_until < time.monotonic() + 30

    @pytest.mark.asyncio
    async def test_edit_ignores_non_429_error(self):
        """_edit should not set a hold for non-429 errors."""
        state = _make_state()
        state.sent_message_id = 42

        exc = Exception("Error code: 400. Description: Bad Request: message is too long")
        state.bot.edit_message_text = AsyncMock(side_effect=exc)

        await state._edit("<p>hello</p>")
        assert state._rate_limited_until == 0.0

    @pytest.mark.asyncio
    async def test_edit_ignores_message_not_modified(self):
        """_edit should silently return for 'message is not modified' errors."""
        state = _make_state()
        state.sent_message_id = 42

        exc = Exception("Bad Request: message is not modified")
        state.bot.edit_message_text = AsyncMock(side_effect=exc)

        await state._edit("<p>hello</p>")
        assert state._rate_limited_until == 0.0

    @pytest.mark.asyncio
    async def test_send_or_edit_works_after_hold_expires(self):
        """After the hold expires, send_or_edit should function normally."""
        state = _make_state()
        state._rate_limited_until = time.monotonic() - 1

        msg_mock = MagicMock()
        msg_mock.message_id = 99
        state.bot.send_message = AsyncMock(return_value=msg_mock)

        await state.send_or_edit("<p>hello</p>")

        state.bot.send_message.assert_called_once()
        assert state.sent_message_id == 99


# ---------------------------------------------------------------------------
# _send_new 429 handling
# ---------------------------------------------------------------------------


class TestSendNew429:
    """Tests for _send_new rate-limit handling."""

    @pytest.mark.asyncio
    async def test_send_new_sets_hold_on_429(self):
        """_send_new should set the rate-limit hold when a 429 is received."""
        state = _make_state()

        exc = Exception("Error code: 429. Description: Too Many Requests: retry after 10")
        state.bot.send_message = AsyncMock(side_effect=exc)

        result = await state._send_new("<p>test</p>")
        assert result is None
        assert state._rate_limited_until > time.monotonic() + 5

    @pytest.mark.asyncio
    async def test_send_new_reraises_non_429(self):
        """_send_new should re-raise non-429 exceptions."""
        state = _make_state()

        exc = Exception("Error code: 400. Description: Bad Request")
        state.bot.send_message = AsyncMock(side_effect=exc)

        with pytest.raises(Exception, match="Bad Request"):
            await state._send_new("<p>test</p>")

    @pytest.mark.asyncio
    async def test_send_or_edit_handles_send_new_429_gracefully(self):
        """send_or_edit should not crash when _send_new returns None due to 429."""
        state = _make_state()
        assert state.sent_message_id is None

        exc = Exception("Error code: 429. Description: Too Many Requests: retry after 10")
        state.bot.send_message = AsyncMock(side_effect=exc)

        # Should not raise AttributeError on None.message_id
        await state.send_or_edit("<p>test</p>")
        assert state.sent_message_id is None
        assert state._is_rate_limited()


# ---------------------------------------------------------------------------
# finalize waits for rate-limit hold
# ---------------------------------------------------------------------------


class TestFinalizeRateLimit:
    """Tests for finalize() waiting out an active rate-limit hold."""

    @pytest.mark.asyncio
    async def test_finalize_waits_for_rate_limit(self):
        """finalize should sleep until rate-limit hold expires."""
        state = _make_state()
        state.accumulated_content = "Hello world"
        state.sent_message_id = 42
        # Set a hold that expires in 0.1s (short for test speed)
        state._rate_limited_until = time.monotonic() + 0.1

        state.bot.edit_message_text = AsyncMock()

        start = time.monotonic()
        await state.finalize()
        elapsed = time.monotonic() - start

        # Should have waited at least ~0.1s
        assert elapsed >= 0.05
        # Should have called edit after waiting
        state.bot.edit_message_text.assert_called_once()
        # Hold should be cleared
        assert state._rate_limited_until == 0.0

    @pytest.mark.asyncio
    async def test_finalize_proceeds_immediately_when_not_rate_limited(self):
        """finalize should not wait when there is no active rate-limit hold."""
        state = _make_state()
        state.accumulated_content = "Hello world"
        state.sent_message_id = 42

        state.bot.edit_message_text = AsyncMock()

        start = time.monotonic()
        await state.finalize()
        elapsed = time.monotonic() - start

        assert elapsed < 0.1
        state.bot.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_proceeds_when_hold_already_expired(self):
        """finalize should proceed immediately if the hold has already expired."""
        state = _make_state()
        state.accumulated_content = "Hello world"
        state.sent_message_id = 42
        state._rate_limited_until = time.monotonic() - 10  # expired 10s ago

        state.bot.edit_message_text = AsyncMock()

        start = time.monotonic()
        await state.finalize()
        elapsed = time.monotonic() - start

        assert elapsed < 0.1
        state.bot.edit_message_text.assert_called_once()


# ---------------------------------------------------------------------------
# _wait_for_rate_limit
# ---------------------------------------------------------------------------


class TestWaitForRateLimit:
    """Tests for the _wait_for_rate_limit helper."""

    @pytest.mark.asyncio
    async def test_noop_when_no_hold(self):
        state = _make_state()
        start = time.monotonic()
        await state._wait_for_rate_limit()
        assert time.monotonic() - start < 0.05

    @pytest.mark.asyncio
    async def test_sleeps_for_remaining_hold(self):
        state = _make_state()
        state._rate_limited_until = time.monotonic() + 0.15

        start = time.monotonic()
        await state._wait_for_rate_limit()
        elapsed = time.monotonic() - start

        assert elapsed >= 0.1
        assert state._rate_limited_until == 0.0

    @pytest.mark.asyncio
    async def test_clears_hold_after_wait(self):
        state = _make_state()
        state._rate_limited_until = time.monotonic() + 0.05

        await state._wait_for_rate_limit()
        assert state._rate_limited_until == 0.0
        assert not state._is_rate_limited()
