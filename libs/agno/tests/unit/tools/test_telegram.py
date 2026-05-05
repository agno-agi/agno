import json
from unittest.mock import MagicMock, patch

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
    with (
        patch("agno.tools.telegram.TeleBot") as mock_telebot,
        patch("agno.tools.telegram.ApiTelegramException", _FakeApiTelegramException),
    ):
        mock_telebot.return_value = MagicMock()
        yield {"TeleBot": mock_telebot}


class TestTelegramToolsInit:
    def test_default_registers_send_message_only(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        assert "send_message" in tools.functions
        assert "send_photo" not in tools.functions

    def test_token_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "env-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        assert tools.token == "env-token"

    def test_token_from_param(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345", token="param-token")
        assert tools.token == "param-token"

    def test_param_token_overrides_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "env-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345", token="param-token")
        assert tools.token == "param-token"

    def test_missing_token_raises(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        from agno.tools.telegram import TelegramTools

        with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
            TelegramTools(chat_id="12345")

    def test_chat_id_optional_with_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "99999")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools()
        assert tools.chat_id == "99999"

    def test_chat_id_from_param(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        assert tools.chat_id == "12345"

    def test_media_tools_disabled_by_default(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        for name in ("send_photo", "send_document", "send_video", "send_audio", "send_animation", "send_sticker"):
            assert name not in tools.functions

    def test_media_tools_enabled_explicitly(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(
            chat_id="12345",
            enable_send_photo=True,
            enable_send_video=True,
            enable_send_audio=True,
            enable_send_document=True,
            enable_send_animation=True,
            enable_send_sticker=True,
        )
        for name in ("send_photo", "send_document", "send_video", "send_audio", "send_animation", "send_sticker"):
            assert name in tools.functions

    def test_edit_delete_disabled_by_default(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        assert "edit_message" not in tools.functions
        assert "delete_message" not in tools.functions

    def test_edit_delete_enabled(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345", enable_edit_message=True, enable_delete_message=True)
        assert "edit_message" in tools.functions
        assert "delete_message" in tools.functions

    def test_all_flag_enables_everything(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345", all=True)
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

        tools = TelegramTools(chat_id="12345", enable_send_message=False)
        assert len(tools.functions) == 0

    def test_selective_enable(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345", enable_send_photo=True, enable_send_document=True)
        assert "send_message" in tools.functions
        assert "send_photo" in tools.functions
        assert "send_document" in tools.functions
        assert "send_video" not in tools.functions

    def test_creates_telebot_instance(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        assert hasattr(tools, "bot")


class TestChatIdProperty:
    def test_returns_constructor_value(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="11111")
        assert tools._chat_id == "11111"

    def test_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "99999")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools()
        assert tools._chat_id == "99999"

    def test_raises_when_no_chat_id(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools()
        with pytest.raises(ValueError, match="chat_id is required"):
            _ = tools._chat_id


class TestSendMessage:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        mock_result = MagicMock()
        mock_result.message_id = 101
        tools.bot.send_message = MagicMock(return_value=mock_result)

        result = tools.send_message("Hello")
        tools.bot.send_message.assert_called_once_with("12345", "Hello")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 101

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        tools.bot.send_message = MagicMock(side_effect=_FakeApiTelegramException("sendMessage", "Bad Request", 400))

        result = tools.send_message("Hello")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestSendPhoto:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        mock_result = MagicMock()
        mock_result.message_id = 103
        tools.bot.send_photo = MagicMock(return_value=mock_result)

        result = tools.send_photo(b"image-bytes", caption="A photo")
        tools.bot.send_photo.assert_called_once_with("12345", b"image-bytes", caption="A photo")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 103


class TestSendDocument:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        mock_result = MagicMock()
        mock_result.message_id = 105
        tools.bot.send_document = MagicMock(return_value=mock_result)

        result = tools.send_document(b"doc-bytes", "report.pdf")
        tools.bot.send_document.assert_called_once_with("12345", ("report.pdf", b"doc-bytes"), caption=None)
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 105


class TestSendVideo:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        mock_result = MagicMock()
        mock_result.message_id = 107
        tools.bot.send_video = MagicMock(return_value=mock_result)

        result = tools.send_video(b"video-bytes", caption="A video")
        tools.bot.send_video.assert_called_once_with("12345", b"video-bytes", caption="A video")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 107

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        tools.bot.send_video = MagicMock(side_effect=_FakeApiTelegramException("sendVideo", "Bad Request", 400))

        result = tools.send_video(b"video-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestSendAudio:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        mock_result = MagicMock()
        mock_result.message_id = 109
        tools.bot.send_audio = MagicMock(return_value=mock_result)

        result = tools.send_audio(b"audio-bytes", caption="A song", title="Song Title")
        tools.bot.send_audio.assert_called_once_with("12345", b"audio-bytes", caption="A song", title="Song Title")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 109

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        tools.bot.send_audio = MagicMock(side_effect=_FakeApiTelegramException("sendAudio", "Bad Request", 400))

        result = tools.send_audio(b"audio-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestSendAnimation:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        mock_result = MagicMock()
        mock_result.message_id = 111
        tools.bot.send_animation = MagicMock(return_value=mock_result)

        result = tools.send_animation(b"gif-bytes", caption="A GIF")
        tools.bot.send_animation.assert_called_once_with("12345", b"gif-bytes", caption="A GIF")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 111

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        tools.bot.send_animation = MagicMock(side_effect=_FakeApiTelegramException("sendAnimation", "Bad Request", 400))

        result = tools.send_animation(b"gif-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestSendSticker:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        mock_result = MagicMock()
        mock_result.message_id = 113
        tools.bot.send_sticker = MagicMock(return_value=mock_result)

        result = tools.send_sticker(b"sticker-bytes")
        tools.bot.send_sticker.assert_called_once_with("12345", b"sticker-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 113

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345")
        tools.bot.send_sticker = MagicMock(side_effect=_FakeApiTelegramException("sendSticker", "Bad Request", 400))

        result = tools.send_sticker(b"sticker-bytes")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestEditMessage:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345", enable_edit_message=True)
        mock_result = MagicMock()
        mock_result.message_id = 42
        tools.bot.edit_message_text = MagicMock(return_value=mock_result)

        result = tools.edit_message("Updated text", message_id=42)
        tools.bot.edit_message_text.assert_called_once_with("Updated text", chat_id="12345", message_id=42)
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["message_id"] == 42

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345", enable_edit_message=True)
        tools.bot.edit_message_text = MagicMock(
            side_effect=_FakeApiTelegramException("editMessageText", "Bad Request", 400)
        )

        result = tools.edit_message("Updated text", message_id=42)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]


class TestDeleteMessage:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345", enable_delete_message=True)
        tools.bot.delete_message = MagicMock(return_value=True)

        result = tools.delete_message(message_id=42)
        tools.bot.delete_message.assert_called_once_with("12345", 42)
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["deleted"] is True

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        from agno.tools.telegram import TelegramTools

        tools = TelegramTools(chat_id="12345", enable_delete_message=True)
        tools.bot.delete_message = MagicMock(side_effect=_FakeApiTelegramException("deleteMessage", "Bad Request", 400))

        result = tools.delete_message(message_id=42)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Bad Request" in parsed["message"]
