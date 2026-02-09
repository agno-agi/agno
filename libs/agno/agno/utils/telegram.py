import os
from typing import Any, List, Optional

from agno.utils.log import log_debug, log_error

TeleBot: Any = None
AsyncTeleBot: Any = None

try:
    from telebot import TeleBot  # type: ignore[no-redef]
    from telebot.async_telebot import AsyncTeleBot  # type: ignore[no-redef]
except ImportError:
    pass


def _require_telebot() -> None:
    if TeleBot is None:
        raise ImportError(
            "`telegram` utils require the `pyTelegramBotAPI` package. "
            "Run `pip install pyTelegramBotAPI` or `pip install 'agno[telegram]'` to install it."
        )


def get_bot_token() -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set")
    return token


def send_chat_action(chat_id: int, action: str, token: Optional[str] = None) -> None:
    _require_telebot()
    bot = TeleBot(token or get_bot_token())
    bot.send_chat_action(chat_id, action)


def get_file_bytes(file_id: str, token: Optional[str] = None) -> Optional[bytes]:
    _require_telebot()
    try:
        bot = TeleBot(token or get_bot_token())
        file_info = bot.get_file(file_id)
        return bot.download_file(file_info.file_path)
    except Exception as e:
        log_error(f"Error downloading file: {e}")
        return None


def send_text_message(chat_id: int, text: str, token: Optional[str] = None) -> None:
    _require_telebot()
    bot = TeleBot(token or get_bot_token())
    bot.send_message(chat_id, text)


def send_text_chunked(chat_id: int, text: str, max_chars: int = 4000, token: Optional[str] = None) -> None:
    _require_telebot()
    if len(text) <= 4096:
        send_text_message(chat_id, text, token=token)
        return

    chunks: List[str] = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    bot = TeleBot(token or get_bot_token())
    for i, chunk in enumerate(chunks, 1):
        bot.send_message(chat_id, f"[{i}/{len(chunks)}] {chunk}")


def send_photo_message(
    chat_id: int, photo_bytes: bytes, caption: Optional[str] = None, token: Optional[str] = None
) -> None:
    _require_telebot()
    bot = TeleBot(token or get_bot_token())
    bot.send_photo(chat_id, photo_bytes, caption=caption)


async def send_chat_action_async(chat_id: int, action: str, token: Optional[str] = None) -> None:
    _require_telebot()
    bot = AsyncTeleBot(token or get_bot_token())
    await bot.send_chat_action(chat_id, action)


async def get_file_bytes_async(file_id: str, token: Optional[str] = None) -> Optional[bytes]:
    _require_telebot()
    try:
        bot = AsyncTeleBot(token or get_bot_token())
        file_info = await bot.get_file(file_id)
        return await bot.download_file(file_info.file_path)
    except Exception as e:
        log_error(f"Error downloading file: {e}")
        return None


async def send_text_message_async(chat_id: int, text: str, token: Optional[str] = None) -> None:
    _require_telebot()
    bot = AsyncTeleBot(token or get_bot_token())
    await bot.send_message(chat_id, text)


async def send_text_chunked_async(chat_id: int, text: str, max_chars: int = 4000, token: Optional[str] = None) -> None:
    _require_telebot()
    if len(text) <= 4096:
        await send_text_message_async(chat_id, text, token=token)
        return

    chunks: List[str] = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    bot = AsyncTeleBot(token or get_bot_token())
    for i, chunk in enumerate(chunks, 1):
        await bot.send_message(chat_id, f"[{i}/{len(chunks)}] {chunk}")


async def send_photo_message_async(
    chat_id: int, photo_bytes: bytes, caption: Optional[str] = None, token: Optional[str] = None
) -> None:
    _require_telebot()
    bot = AsyncTeleBot(token or get_bot_token())
    log_debug(f"Sending photo to chat_id={chat_id}, caption={caption[:50] if caption else None}")
    await bot.send_photo(chat_id, photo_bytes, caption=caption)
