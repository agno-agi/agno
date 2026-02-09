import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeApiTelegramException(Exception):
    def __init__(self, function_name, result, result_code):
        self.function_name = function_name
        self.result = result
        self.result_code = result_code
        super().__init__(
            f"A request to the Telegram API was unsuccessful. Error code: {result_code}. Description: {result}"
        )


@pytest.fixture(autouse=True)
def _mock_telebot():
    """Mock telebot imports so tests run without pyTelegramBotAPI installed."""
    with (
        patch("agno.tools.telegram.TeleBot") as mock_telebot,
        patch("agno.tools.telegram.AsyncTeleBot") as mock_async_telebot,
        patch("agno.tools.telegram.ApiTelegramException", _FakeApiTelegramException),
    ):
        mock_telebot.return_value = MagicMock()
        mock_async_telebot.return_value = AsyncMock()
        yield {"TeleBot": mock_telebot, "AsyncTeleBot": mock_async_telebot}


class TestTelegramToolsInit:
    def test_sync_mode_registers_sync_tools(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        assert "send_message" in tools.functions
        assert "send_photo" in tools.functions
        assert "send_document" in tools.functions
        assert len(tools.async_functions) == 0

    def test_async_mode_registers_async_tools(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        assert "send_message_async" in tools.async_functions
        assert "send_photo_async" in tools.async_functions
        assert "send_document_async" in tools.async_functions
        assert len(tools.functions) == 0

    def test_token_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "env-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        assert tools.token == "env-token"

    def test_token_from_param(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, token="param-token")
        assert tools.token == "param-token"

    def test_param_token_overrides_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "env-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, token="param-token")
        assert tools.token == "param-token"

    def test_missing_token_raises(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        from agno.tools.telegram import TelegramTools

        with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
            TelegramTools(chat_id=12345)

    def test_chat_id_optional_with_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "99999")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools()
        assert tools.chat_id == "99999"

    def test_chat_id_from_param(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        assert tools.chat_id == 12345

    def test_new_media_tools_registered_by_default(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        for name in ("send_video", "send_audio", "send_animation", "send_sticker"):
            assert name in tools.functions

    def test_new_media_tools_async(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        for name in ("send_video_async", "send_audio_async", "send_animation_async", "send_sticker_async"):
            assert name in tools.async_functions

    def test_edit_delete_disabled_by_default(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        assert "edit_message" not in tools.functions
        assert "delete_message" not in tools.functions

    def test_edit_delete_enabled(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, enable_edit_message=True, enable_delete_message=True)
        assert "edit_message" in tools.functions
        assert "delete_message" in tools.functions

    def test_all_flag_enables_everything(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, all=True)
        expected = (
            "send_message",
            "send_photo",
            "send_document",
            "send_video",
            "send_audio",
            "send_animation",
            "send_sticker",
            "edit_message",
            "delete_message",
        )
        for name in expected:
            assert name in tools.functions

    def test_no_tools_when_all_disabled(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(
            chat_id=12345,
            enable_send_message=False,
            enable_send_photo=False,
            enable_send_document=False,
            enable_send_video=False,
            enable_send_audio=False,
            enable_send_animation=False,
            enable_send_sticker=False,
        )
        assert len(tools.functions) == 0

    def test_selective_enable(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(
            chat_id=12345, enable_send_message=True, enable_send_photo=False, enable_send_document=False
        )
        assert "send_message" in tools.functions
        assert "send_photo" not in tools.functions
        assert "send_document" not in tools.functions

    def test_sync_mode_creates_only_telebot(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=False)
        assert hasattr(tools, "bot")
        assert not hasattr(tools, "async_bot")

    def test_async_mode_creates_only_async_telebot(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        assert hasattr(tools, "async_bot")
        assert not hasattr(tools, "bot")


class TestResolveChatId:
    def test_uses_per_call_chat_id(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=11111)
        assert tools._resolve_chat_id(22222) == 22222

    def test_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=11111)
        assert tools._resolve_chat_id() == 11111

    def test_raises_when_no_chat_id(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools()
        with pytest.raises(ValueError, match="chat_id is required"):
            tools._resolve_chat_id()


class TestSendMessageSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        mock_result = MagicMock()
        mock_result.message_id = 101
        tools.bot.send_message = MagicMock(return_value=mock_result)

        result = tools.send_message("Hello")
        tools.bot.send_message.assert_called_once_with(12345, "Hello")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 101

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        tools.bot.send_message = MagicMock(side_effect=_FakeApiTelegramException("sendMessage", "Bad Request", 400))

        result = tools.send_message("Hello")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]

    def test_per_call_chat_id(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=11111)
        tools.bot.send_message = MagicMock(return_value=MagicMock(message_id=999))

        tools.send_message("Hello", chat_id=22222)
        tools.bot.send_message.assert_called_once_with(22222, "Hello")


class TestSendMessageAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        mock_result = MagicMock()
        mock_result.message_id = 102
        tools.async_bot.send_message = AsyncMock(return_value=mock_result)

        result = await tools.send_message_async("Hello async")
        tools.async_bot.send_message.assert_called_once_with(12345, "Hello async")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 102

    @pytest.mark.asyncio
    async def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        tools.async_bot.send_message = AsyncMock(
            side_effect=_FakeApiTelegramException("sendMessage", "Bad Request", 400)
        )

        result = await tools.send_message_async("Hello")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestSendPhotoSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        mock_result = MagicMock()
        mock_result.message_id = 103
        tools.bot.send_photo = MagicMock(return_value=mock_result)

        result = tools.send_photo(b"image-bytes", caption="A photo")
        tools.bot.send_photo.assert_called_once_with(12345, b"image-bytes", caption="A photo")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 103


class TestSendPhotoAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        mock_result = MagicMock()
        mock_result.message_id = 104
        tools.async_bot.send_photo = AsyncMock(return_value=mock_result)

        result = await tools.send_photo_async(b"image-bytes", caption="A photo")
        tools.async_bot.send_photo.assert_called_once_with(12345, b"image-bytes", caption="A photo")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 104


class TestSendDocumentSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        mock_result = MagicMock()
        mock_result.message_id = 105
        tools.bot.send_document = MagicMock(return_value=mock_result)

        result = tools.send_document(b"doc-bytes", "report.pdf")
        tools.bot.send_document.assert_called_once_with(12345, ("report.pdf", b"doc-bytes"), caption=None)
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 105


class TestSendDocumentAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        mock_result = MagicMock()
        mock_result.message_id = 106
        tools.async_bot.send_document = AsyncMock(return_value=mock_result)

        result = await tools.send_document_async(b"doc-bytes", "report.pdf", caption="Report")
        tools.async_bot.send_document.assert_called_once_with(12345, ("report.pdf", b"doc-bytes"), caption="Report")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 106


class TestSendVideoSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        mock_result = MagicMock()
        mock_result.message_id = 107
        tools.bot.send_video = MagicMock(return_value=mock_result)

        result = tools.send_video(b"video-bytes", caption="A video")
        tools.bot.send_video.assert_called_once_with(12345, b"video-bytes", caption="A video")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 107

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        tools.bot.send_video = MagicMock(side_effect=_FakeApiTelegramException("sendVideo", "Bad Request", 400))

        result = tools.send_video(b"video-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestSendVideoAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        mock_result = MagicMock()
        mock_result.message_id = 108
        tools.async_bot.send_video = AsyncMock(return_value=mock_result)

        result = await tools.send_video_async(b"video-bytes", caption="A video")
        tools.async_bot.send_video.assert_called_once_with(12345, b"video-bytes", caption="A video")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 108


class TestSendAudioSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        mock_result = MagicMock()
        mock_result.message_id = 109
        tools.bot.send_audio = MagicMock(return_value=mock_result)

        result = tools.send_audio(b"audio-bytes", caption="A song", title="Song Title")
        tools.bot.send_audio.assert_called_once_with(12345, b"audio-bytes", caption="A song", title="Song Title")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 109

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        tools.bot.send_audio = MagicMock(side_effect=_FakeApiTelegramException("sendAudio", "Bad Request", 400))

        result = tools.send_audio(b"audio-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestSendAudioAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        mock_result = MagicMock()
        mock_result.message_id = 110
        tools.async_bot.send_audio = AsyncMock(return_value=mock_result)

        result = await tools.send_audio_async(b"audio-bytes", caption="A song", title="Song Title")
        tools.async_bot.send_audio.assert_called_once_with(12345, b"audio-bytes", caption="A song", title="Song Title")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 110


class TestSendAnimationSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        mock_result = MagicMock()
        mock_result.message_id = 111
        tools.bot.send_animation = MagicMock(return_value=mock_result)

        result = tools.send_animation(b"gif-bytes", caption="A GIF")
        tools.bot.send_animation.assert_called_once_with(12345, b"gif-bytes", caption="A GIF")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 111

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        tools.bot.send_animation = MagicMock(side_effect=_FakeApiTelegramException("sendAnimation", "Bad Request", 400))

        result = tools.send_animation(b"gif-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestSendAnimationAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        mock_result = MagicMock()
        mock_result.message_id = 112
        tools.async_bot.send_animation = AsyncMock(return_value=mock_result)

        result = await tools.send_animation_async(b"gif-bytes", caption="A GIF")
        tools.async_bot.send_animation.assert_called_once_with(12345, b"gif-bytes", caption="A GIF")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 112


class TestSendStickerSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        mock_result = MagicMock()
        mock_result.message_id = 113
        tools.bot.send_sticker = MagicMock(return_value=mock_result)

        result = tools.send_sticker(b"sticker-bytes")
        tools.bot.send_sticker.assert_called_once_with(12345, b"sticker-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 113

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345)
        tools.bot.send_sticker = MagicMock(side_effect=_FakeApiTelegramException("sendSticker", "Bad Request", 400))

        result = tools.send_sticker(b"sticker-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestSendStickerAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True)
        mock_result = MagicMock()
        mock_result.message_id = 114
        tools.async_bot.send_sticker = AsyncMock(return_value=mock_result)

        result = await tools.send_sticker_async(b"sticker-bytes")
        tools.async_bot.send_sticker.assert_called_once_with(12345, b"sticker-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 114


class TestEditMessageSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, enable_edit_message=True)
        mock_result = MagicMock()
        mock_result.message_id = 42
        tools.bot.edit_message_text = MagicMock(return_value=mock_result)

        result = tools.edit_message("Updated text", message_id=42)
        tools.bot.edit_message_text.assert_called_once_with("Updated text", chat_id=12345, message_id=42)
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 42

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, enable_edit_message=True)
        tools.bot.edit_message_text = MagicMock(
            side_effect=_FakeApiTelegramException("editMessageText", "Bad Request", 400)
        )

        result = tools.edit_message("Updated text", message_id=42)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]

    def test_per_call_chat_id(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=11111, enable_edit_message=True)
        tools.bot.edit_message_text = MagicMock(return_value=MagicMock(message_id=42))

        tools.edit_message("Updated text", message_id=42, chat_id=22222)
        tools.bot.edit_message_text.assert_called_once_with("Updated text", chat_id=22222, message_id=42)


class TestEditMessageAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True, enable_edit_message=True)
        mock_result = MagicMock()
        mock_result.message_id = 42
        tools.async_bot.edit_message_text = AsyncMock(return_value=mock_result)

        result = await tools.edit_message_async("Updated text", message_id=42)
        tools.async_bot.edit_message_text.assert_called_once_with("Updated text", chat_id=12345, message_id=42)
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 42


class TestDeleteMessageSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, enable_delete_message=True)
        tools.bot.delete_message = MagicMock(return_value=True)

        result = tools.delete_message(message_id=42)
        tools.bot.delete_message.assert_called_once_with(12345, 42)
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["deleted"] is True

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, enable_delete_message=True)
        tools.bot.delete_message = MagicMock(side_effect=_FakeApiTelegramException("deleteMessage", "Bad Request", 400))

        result = tools.delete_message(message_id=42)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]

    def test_per_call_chat_id(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=11111, enable_delete_message=True)
        tools.bot.delete_message = MagicMock(return_value=True)

        tools.delete_message(message_id=42, chat_id=22222)
        tools.bot.delete_message.assert_called_once_with(22222, 42)


class TestDeleteMessageAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id=12345, async_mode=True, enable_delete_message=True)
        tools.async_bot.delete_message = AsyncMock(return_value=True)

        result = await tools.delete_message_async(message_id=42)
        tools.async_bot.delete_message.assert_called_once_with(12345, 42)
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["deleted"] is True
