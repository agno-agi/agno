from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTILS_MODULE = "agno.utils.telegram"


@pytest.fixture(autouse=True)
def _mock_telebot():
    """Patch both TeleBot and AsyncTeleBot so _require_telebot() passes."""
    with (
        patch(f"{UTILS_MODULE}.TeleBot") as mock_telebot,
        patch(f"{UTILS_MODULE}.AsyncTeleBot") as mock_async_telebot,
    ):
        mock_telebot.return_value = MagicMock()
        mock_async_telebot.return_value = AsyncMock()
        yield {"TeleBot": mock_telebot, "AsyncTeleBot": mock_async_telebot}


class TestGetBotToken:
    def test_returns_token(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "my-token")
        from agno.utils.telegram import get_bot_token

        assert get_bot_token() == "my-token"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        from agno.utils.telegram import get_bot_token

        with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
            get_bot_token()


class TestSendChatAction:
    def test_sync(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["TeleBot"].return_value

        from agno.utils.telegram import send_chat_action

        send_chat_action(12345, "typing")
        _mock_telebot["TeleBot"].assert_called_with("fake-token")
        mock_bot.send_chat_action.assert_called_once_with(12345, "typing")

    def test_sync_with_custom_token(self, _mock_telebot):
        from agno.utils.telegram import send_chat_action

        send_chat_action(12345, "typing", token="custom-token")
        _mock_telebot["TeleBot"].assert_called_with("custom-token")

    @pytest.mark.asyncio
    async def test_async(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["AsyncTeleBot"].return_value

        from agno.utils.telegram import send_chat_action_async

        await send_chat_action_async(12345, "typing")
        _mock_telebot["AsyncTeleBot"].assert_called_with("fake-token")
        mock_bot.send_chat_action.assert_called_once_with(12345, "typing")


class TestGetFileBytes:
    def test_sync_success(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["TeleBot"].return_value
        mock_file_info = MagicMock()
        mock_file_info.file_path = "photos/file_123.jpg"
        mock_bot.get_file.return_value = mock_file_info
        mock_bot.download_file.return_value = b"image-data"

        from agno.utils.telegram import get_file_bytes

        result = get_file_bytes("file_id_123")
        assert result == b"image-data"
        mock_bot.get_file.assert_called_once_with("file_id_123")
        mock_bot.download_file.assert_called_once_with("photos/file_123.jpg")

    def test_sync_error_returns_none(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["TeleBot"].return_value
        mock_bot.get_file.side_effect = Exception("Network error")

        from agno.utils.telegram import get_file_bytes

        result = get_file_bytes("file_id_123")
        assert result is None

    @pytest.mark.asyncio
    async def test_async_success(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["AsyncTeleBot"].return_value
        mock_file_info = MagicMock()
        mock_file_info.file_path = "photos/file_123.jpg"
        mock_bot.get_file.return_value = mock_file_info
        mock_bot.download_file.return_value = b"image-data"

        from agno.utils.telegram import get_file_bytes_async

        result = await get_file_bytes_async("file_id_123")
        assert result == b"image-data"

    @pytest.mark.asyncio
    async def test_async_error_returns_none(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["AsyncTeleBot"].return_value
        mock_bot.get_file.side_effect = Exception("Network error")

        from agno.utils.telegram import get_file_bytes_async

        result = await get_file_bytes_async("file_id_123")
        assert result is None


class TestSendTextMessage:
    def test_sync(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["TeleBot"].return_value

        from agno.utils.telegram import send_text_message

        send_text_message(12345, "Hello")
        mock_bot.send_message.assert_called_once_with(12345, "Hello")

    @pytest.mark.asyncio
    async def test_async(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["AsyncTeleBot"].return_value

        from agno.utils.telegram import send_text_message_async

        await send_text_message_async(12345, "Hello")
        mock_bot.send_message.assert_called_once_with(12345, "Hello")


class TestSendTextChunked:
    def test_short_message_not_split(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["TeleBot"].return_value

        from agno.utils.telegram import send_text_chunked

        send_text_chunked(12345, "Short message")
        mock_bot.send_message.assert_called_once_with(12345, "Short message")

    def test_long_message_is_split(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["TeleBot"].return_value

        from agno.utils.telegram import send_text_chunked

        long_text = "x" * 8500
        send_text_chunked(12345, long_text)
        # 8500 / 4000 = 3 chunks
        assert mock_bot.send_message.call_count == 3
        first_call = mock_bot.send_message.call_args_list[0]
        assert first_call[0][1].startswith("[1/3]")

    @pytest.mark.asyncio
    async def test_async_short(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["AsyncTeleBot"].return_value

        from agno.utils.telegram import send_text_chunked_async

        await send_text_chunked_async(12345, "Short")
        mock_bot.send_message.assert_called_once_with(12345, "Short")

    @pytest.mark.asyncio
    async def test_async_long(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["AsyncTeleBot"].return_value

        from agno.utils.telegram import send_text_chunked_async

        long_text = "y" * 8500
        await send_text_chunked_async(12345, long_text)
        assert mock_bot.send_message.call_count == 3


class TestSendPhotoMessage:
    def test_sync(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["TeleBot"].return_value

        from agno.utils.telegram import send_photo_message

        send_photo_message(12345, b"photo-bytes", caption="Caption")
        mock_bot.send_photo.assert_called_once_with(12345, b"photo-bytes", caption="Caption")

    @pytest.mark.asyncio
    async def test_async(self, monkeypatch, _mock_telebot):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        mock_bot = _mock_telebot["AsyncTeleBot"].return_value

        from agno.utils.telegram import send_photo_message_async

        await send_photo_message_async(12345, b"photo-bytes", caption="Caption")
        mock_bot.send_photo.assert_called_once_with(12345, b"photo-bytes", caption="Caption")
