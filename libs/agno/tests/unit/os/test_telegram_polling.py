"""Tests for long-polling mode: TelegramMessageProcessor, TelegramPolling, Telegram(mode='polling')."""

import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Install a lightweight fake telebot so tests work without pyTelegramBotAPI
# ---------------------------------------------------------------------------


def _install_fake_telebot():
    telebot = types.ModuleType("telebot")
    telebot_async = types.ModuleType("telebot.async_telebot")
    telebot_types = types.ModuleType("telebot.types")
    telebot_apihelper = types.ModuleType("telebot.apihelper")

    class AsyncTeleBot:
        def __init__(self, token=None):
            self.token = token

    class TeleBot:
        def __init__(self, token=None):
            self.token = token

    class ApiTelegramException(Exception):
        pass

    class BotCommand:
        def __init__(self, command, description):
            self.command = command
            self.description = description

    telebot.TeleBot = TeleBot
    telebot_async.AsyncTeleBot = AsyncTeleBot
    telebot_types.BotCommand = BotCommand
    telebot_apihelper.ApiTelegramException = ApiTelegramException
    sys.modules.setdefault("telebot", telebot)
    sys.modules.setdefault("telebot.async_telebot", telebot_async)
    sys.modules.setdefault("telebot.types", telebot_types)
    sys.modules.setdefault("telebot.apihelper", telebot_apihelper)


_install_fake_telebot()

from agno.os.interfaces.telegram import Telegram  # noqa: E402
from agno.os.interfaces.telegram.polling import (  # noqa: E402
    TelegramPolling,
    _message_to_dict,
)
from agno.os.interfaces.telegram.processor import (  # noqa: E402
    TelegramMessageProcessor,
    _build_session_scope,
)

PROCESSOR_MODULE = "agno.os.interfaces.telegram.processor"
HELPERS_MODULE = "agno.os.interfaces.telegram.helpers"
STATE_MODULE = "agno.os.interfaces.telegram.state"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text_update(text="Hello", chat_id=12345, user_id=67890, chat_type="private", message_id=100):
    return {
        "message_id": message_id,
        "from": {"id": user_id, "is_bot": False},
        "chat": {"id": chat_id, "type": chat_type},
        "text": text,
    }


def _make_processor(entity=None, entity_type="agent", token="fake-token", **kwargs):
    """Create a TelegramMessageProcessor with mocked bot."""
    if entity is None:
        entity = MagicMock(id="test-entity")
    with patch(f"{PROCESSOR_MODULE}.AsyncTeleBot", return_value=AsyncMock()) as mock_bot_cls:
        processor = TelegramMessageProcessor(
            entity=entity,
            entity_type=entity_type,
            token=token,
            **kwargs,
        )
        processor.bot = mock_bot_cls.return_value
    return processor


# ===================================================================
# _build_session_scope
# ===================================================================


class TestBuildSessionScope:
    def test_dm_scope(self):
        scope = _build_session_scope("my-agent", 12345, None)
        assert scope == "tg:my-agent:12345"

    def test_thread_scope(self):
        scope = _build_session_scope("my-agent", 12345, 99)
        assert scope == "tg:my-agent:12345:99"


# ===================================================================
# TelegramMessageProcessor.__init__
# ===================================================================


class TestProcessorInit:
    def test_invalid_entity_type_raises(self):
        with pytest.raises(ValueError, match="entity_type must be one of"):
            TelegramMessageProcessor(entity=MagicMock(), entity_type="invalid", token="x")

    def test_stores_params(self):
        agent = MagicMock(id="a1")
        with patch(f"{PROCESSOR_MODULE}.AsyncTeleBot", return_value=AsyncMock()):
            p = TelegramMessageProcessor(
                entity=agent,
                entity_type="agent",
                token="tok",
                streaming=False,
                reply_to_mentions_only=False,
            )
        assert p.entity is agent
        assert p.entity_type == "agent"
        assert p.streaming is False
        assert p.reply_to_mentions_only is False

    def test_creates_bot_and_state(self):
        agent = MagicMock(id="a1")
        mock_bot = AsyncMock()
        with patch(f"{PROCESSOR_MODULE}.AsyncTeleBot", return_value=mock_bot):
            p = TelegramMessageProcessor(entity=agent, entity_type="agent", token="tok")
        assert p.bot is mock_bot
        assert p.bot_state is not None
        assert p.bot_state.entity_id == "a1"


# ===================================================================
# TelegramMessageProcessor.process_message
# ===================================================================


class TestProcessorProcessMessage:
    @pytest.mark.asyncio
    async def test_text_message_calls_agent_arun(self):
        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Hello!"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.videos = None
        mock_response.audio = None
        mock_response.files = None

        agent = AsyncMock(id="a1")
        agent.arun = AsyncMock(return_value=mock_response)

        processor = _make_processor(entity=agent, entity_type="agent", streaming=False)

        with patch(f"{PROCESSOR_MODULE}.extract_message_payload", return_value={"message": "Hi"}):
            await processor.process_message(_text_update("Hi"))

        agent.arun.assert_called_once()

    @pytest.mark.asyncio
    async def test_bot_message_ignored(self):
        agent = AsyncMock(id="a1")
        processor = _make_processor(entity=agent, entity_type="agent", streaming=False)

        msg = _text_update()
        msg["from"]["is_bot"] = True
        await processor.process_message(msg)

        agent.arun.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_chat_id_returns_early(self):
        agent = AsyncMock(id="a1")
        processor = _make_processor(entity=agent, entity_type="agent", streaming=False)

        await processor.process_message({"message_id": 1, "from": {"id": 1}, "chat": {}})

        agent.arun.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_command(self):
        agent = AsyncMock(id="a1")
        processor = _make_processor(entity=agent, entity_type="agent", start_message="Welcome!")

        msg = _text_update("/start")

        with patch(f"{PROCESSOR_MODULE}.send_message", new_callable=AsyncMock) as mock_send:
            await processor.process_message(msg)
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][1] == 12345
            assert "Welcome!" in call_args[0][2]

        agent.arun.assert_not_called()

    @pytest.mark.asyncio
    async def test_help_command(self):
        agent = AsyncMock(id="a1")
        processor = _make_processor(entity=agent, entity_type="agent", help_message="Help text")

        with patch(f"{PROCESSOR_MODULE}.send_message", new_callable=AsyncMock) as mock_send:
            await processor.process_message(_text_update("/help"))
            mock_send.assert_called_once()

        agent.arun.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_sends_error_message(self):
        agent = AsyncMock(id="a1")
        agent.arun = AsyncMock(side_effect=RuntimeError("boom"))
        processor = _make_processor(entity=agent, entity_type="agent", streaming=False, error_message="Oops")

        with patch(f"{PROCESSOR_MODULE}.extract_message_payload", return_value={"message": "Hi"}):
            with patch(f"{PROCESSOR_MODULE}.send_message", new_callable=AsyncMock) as mock_send:
                await processor.process_message(_text_update("Hi"))
                # Should have sent error message
                mock_send.assert_called()

    @pytest.mark.asyncio
    async def test_group_without_mention_skipped(self):
        agent = AsyncMock(id="a1")
        processor = _make_processor(entity=agent, entity_type="agent", reply_to_mentions_only=True)

        msg = _text_update("Hello", chat_type="supergroup")

        with patch(f"{PROCESSOR_MODULE}.is_bot_mentioned", return_value=False):
            await processor.process_message(msg)

        agent.arun.assert_not_called()

    @pytest.mark.asyncio
    async def test_group_with_mention_processed(self):
        mock_response = MagicMock()
        mock_response.status = "COMPLETED"
        mock_response.content = "Reply"
        mock_response.reasoning_content = None
        mock_response.images = None
        mock_response.videos = None
        mock_response.audio = None
        mock_response.files = None

        agent = AsyncMock(id="a1")
        agent.arun = AsyncMock(return_value=mock_response)

        processor = _make_processor(entity=agent, entity_type="agent", streaming=False, reply_to_mentions_only=True)
        processor.bot_state.bot_username = "testbot"
        processor.bot_state.bot_id = 42

        msg = _text_update("@testbot hello", chat_type="supergroup", message_id=200)

        with patch(f"{PROCESSOR_MODULE}.is_bot_mentioned", return_value=True):
            with patch(f"{PROCESSOR_MODULE}.extract_message_payload", return_value={"message": "@testbot hello"}):
                with patch(f"{PROCESSOR_MODULE}.send_response_media", new_callable=AsyncMock):
                    await processor.process_message(msg)

        agent.arun.assert_called_once()


# ===================================================================
# TelegramPolling
# ===================================================================


class TestTelegramPolling:
    @pytest.mark.asyncio
    async def test_start_processes_updates(self):
        processor = _make_processor()

        # Create a fake update object
        update = MagicMock()
        update.update_id = 42
        message = MagicMock()
        message.chat = MagicMock()
        message.chat.id = 12345
        message.chat.type = "private"
        message.from_user = MagicMock()
        message.from_user.id = 67890
        message.from_user.is_bot = False
        message.message_id = 100
        message.text = "Hello"
        message.json = lambda: json.dumps(
            {
                "message_id": 100,
                "from": {"id": 67890, "is_bot": False},
                "chat": {"id": 12345, "type": "private"},
                "text": "Hello",
            }
        )
        # Remove edited_message
        del update.edited_message
        update.message = message

        # First call returns updates, second call triggers stop
        call_count = 0

        async def fake_get_updates(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [update]
            poller.stop()
            return []

        processor.bot.get_updates = fake_get_updates
        processor.process_message = AsyncMock()

        poller = TelegramPolling(processor)
        await poller.start()

        # Give background task time to run
        await asyncio.sleep(0.1)
        processor.process_message.assert_called_once()
        called_msg = processor.process_message.call_args[0][0]
        assert called_msg["text"] == "Hello"
        assert called_msg["chat"]["id"] == 12345

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        processor = _make_processor()
        poller = TelegramPolling(processor)
        assert poller._running is False
        poller._running = True
        poller.stop()
        assert poller._running is False

    @pytest.mark.asyncio
    async def test_polling_error_retries(self):
        processor = _make_processor()
        call_count = 0

        async def fake_get_updates(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("network error")
            poller.stop()
            return []

        processor.bot.get_updates = fake_get_updates

        poller = TelegramPolling(processor)
        await poller.start()

        # Should have retried after error
        assert call_count == 2


# ===================================================================
# _message_to_dict
# ===================================================================


class TestMessageToDict:
    def test_uses_json_method(self):
        msg = MagicMock()
        msg.json = lambda: json.dumps({"message_id": 1, "chat": {"id": 123}})
        result = _message_to_dict(msg)
        assert result["message_id"] == 1
        assert result["chat"]["id"] == 123

    def test_fallback_manual_conversion(self):
        msg = MagicMock(spec=[])
        del msg.json
        msg.chat = MagicMock()
        msg.chat.id = 99
        msg.chat.type = "private"
        msg.from_user = MagicMock()
        msg.from_user.id = 42
        msg.from_user.is_bot = False
        msg.message_id = 7
        msg.text = "hello"

        result = _message_to_dict(msg)
        assert result["chat"]["id"] == 99
        assert result["message_id"] == 7
        assert result["text"] == "hello"


# ===================================================================
# Telegram class — mode="polling"
# ===================================================================


class TestTelegramPollingMode:
    def test_mode_param_stored(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tg = Telegram(agent=MagicMock(), mode="polling")
        assert tg.mode == "polling"

    def test_get_router_raises_in_polling_mode(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tg = Telegram(agent=MagicMock(), mode="polling")
        with pytest.raises(RuntimeError, match="polling mode"):
            tg.get_router()

    def test_get_router_works_in_webhook_mode(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tg = Telegram(agent=MagicMock(), mode="webhook")
        router = tg.get_router()
        assert router is not None
        routes = [r.path for r in router.routes]
        assert "/telegram/status" in routes
        assert "/telegram/webhook" in routes

    @pytest.mark.asyncio
    async def test_start_polling_raises_in_webhook_mode(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tg = Telegram(agent=MagicMock(), mode="webhook")
        with pytest.raises(RuntimeError, match="webhook mode"):
            await tg.start_polling()

    def test_defaults_to_webhook(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tg = Telegram(agent=MagicMock())
        assert tg.mode == "webhook"

    def test_prefix_and_tags_preserved(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tg = Telegram(agent=MagicMock(), mode="polling", prefix="/bot", tags=["Custom"])
        assert tg.prefix == "/bot"
        assert tg.tags == ["Custom"]


# ===================================================================
# Shutdown hygiene, quoted_responses, __init__ order, processor<->router parity
# ===================================================================


class TestPollingShutdown:
    @pytest.mark.asyncio
    async def test_start_closes_bot_session_on_exit(self):
        processor = _make_processor()
        processor.bot.close_session = AsyncMock()
        poller = TelegramPolling(processor)

        async def fake_get_updates(**kwargs):
            poller.stop()
            return []

        processor.bot.get_updates = fake_get_updates
        await poller.start()
        processor.bot.close_session.assert_awaited_once()


def _completed_response():
    return MagicMock(
        status="COMPLETED",
        content="ok",
        reasoning_content=None,
        images=None,
        videos=None,
        audio=None,
        files=None,
    )


class TestQuotedResponses:
    @pytest.mark.asyncio
    async def test_quoted_responses_quotes_reply_in_dm(self):
        agent = AsyncMock(id="a1")
        agent.arun = AsyncMock(return_value=_completed_response())
        processor = _make_processor(entity=agent, entity_type="agent", streaming=False, quoted_responses=True)
        msg = _text_update("Hi", message_id=777)  # private chat
        with patch(f"{PROCESSOR_MODULE}.extract_message_payload", return_value={"message": "Hi"}):
            with patch(f"{PROCESSOR_MODULE}.send_response_media", new_callable=AsyncMock):
                with patch(f"{PROCESSOR_MODULE}.send_message", new_callable=AsyncMock) as mock_send:
                    await processor.process_message(msg)
        assert mock_send.called
        assert any(c.kwargs.get("reply_to_message_id") == 777 for c in mock_send.call_args_list)

    @pytest.mark.asyncio
    async def test_no_quoted_reply_in_dm_by_default(self):
        agent = AsyncMock(id="a1")
        agent.arun = AsyncMock(return_value=_completed_response())
        processor = _make_processor(entity=agent, entity_type="agent", streaming=False)
        msg = _text_update("Hi", message_id=777)  # private chat
        with patch(f"{PROCESSOR_MODULE}.extract_message_payload", return_value={"message": "Hi"}):
            with patch(f"{PROCESSOR_MODULE}.send_response_media", new_callable=AsyncMock):
                with patch(f"{PROCESSOR_MODULE}.send_message", new_callable=AsyncMock) as mock_send:
                    await processor.process_message(msg)
        assert mock_send.called
        assert all(c.kwargs.get("reply_to_message_id") is None for c in mock_send.call_args_list)

    def test_processor_and_webhook_both_accept_quoted_responses(self):
        import inspect

        from agno.os.interfaces.telegram.router import attach_routes

        webhook_params = set(inspect.signature(attach_routes).parameters)
        processor_params = set(inspect.signature(TelegramMessageProcessor.__init__).parameters)
        assert "quoted_responses" in webhook_params
        assert "quoted_responses" in processor_params

    def test_get_processor_threads_quoted_responses(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "123456:fake")
        with patch(f"{PROCESSOR_MODULE}.AsyncTeleBot", return_value=AsyncMock()):
            tg = Telegram(agent=MagicMock(id="t"), mode="polling", quoted_responses=True)
            processor = tg._get_processor()
        assert processor.quoted_responses is True


class TestTelegramInitAndShutdown:
    def test_init_positional_args_match_webhook_order(self):
        # main's positional order: agent, team, workflow, prefix, tags, token, ...
        tg = Telegram(MagicMock(), None, None, "/bot", ["Tag"], "tok")
        assert tg.prefix == "/bot"
        assert tg.tags == ["Tag"]
        assert tg.token == "tok"
        assert tg.mode == "webhook"

    def test_run_polling_swallows_keyboard_interrupt(self, monkeypatch):
        tg = Telegram(agent=MagicMock(), mode="polling", token="123456:fake")
        monkeypatch.setattr(tg, "start_polling", MagicMock())
        monkeypatch.setattr("asyncio.run", MagicMock(side_effect=KeyboardInterrupt()))
        tg.run_polling()  # KeyboardInterrupt is caught and logged, not propagated
