from typing import TYPE_CHECKING, Any, List, Optional

from agno.media import Audio, File, Image, Video
from agno.os.interfaces.telegram.formatting import markdown_to_telegram_html
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from telebot.async_telebot import AsyncTeleBot

TG_MAX_MESSAGE_LENGTH = 4096
TG_CHUNK_SIZE = 4000
TG_MAX_CAPTION_LENGTH = 1024
TG_MAX_FILE_DOWNLOAD_SIZE = 20 * 1024 * 1024  # 20 MB — Telegram API download limit
_BYTES_PER_MB = 1024 * 1024


def is_bot_mentioned(message: dict, bot_username: str) -> bool:
    text = message.get("text", "") or message.get("caption", "")
    return f"@{bot_username.lower()}" in (text or "").lower()


async def _download(bot: "AsyncTeleBot", file_id: str) -> Optional[bytes]:
    try:
        file_info = await bot.get_file(file_id)
        file_size = getattr(file_info, "file_size", None)
        if isinstance(file_size, (int, float)) and file_size > TG_MAX_FILE_DOWNLOAD_SIZE:
            log_warning(f"File too large to download ({file_size / _BYTES_PER_MB:.1f} MB)")
            return None
        return await bot.download_file(file_info.file_path)
    except Exception as e:
        log_error(f"Error downloading file: {e}")
        return None


def _get_file_id(message: dict) -> tuple[Optional[str], Optional[str], Optional[str], Optional[dict]]:
    """Extract file IDs from a Telegram message. Returns (image, audio, video, document_meta)."""
    if message.get("photo"):
        return message["photo"][-1]["file_id"], None, None, None
    if message.get("sticker"):
        sticker = message["sticker"]
        if sticker.get("is_animated") or sticker.get("is_video"):
            thumb = sticker.get("thumbnail") or sticker.get("thumb")
            return (thumb["file_id"] if thumb else None), None, None, None
        return sticker["file_id"], None, None, None
    if message.get("voice"):
        return None, message["voice"]["file_id"], None, None
    if message.get("audio"):
        return None, message["audio"]["file_id"], None, None
    vid = message.get("video") or message.get("video_note") or message.get("animation")
    if vid:
        return None, None, vid["file_id"], None
    if message.get("document"):
        return None, None, None, message["document"]
    return None, None, None, None


async def extract_message(bot: "AsyncTeleBot", message: dict) -> Optional[dict]:
    """Extract text and media from a Telegram message. Returns arun-ready kwargs dict or None."""
    text = message.get("text") or message.get("caption")
    image_id, audio_id, video_id, doc_meta = _get_file_id(message)

    if text is None and not (image_id or audio_id or video_id or doc_meta):
        return None

    result: dict = {"message": text or ""}

    if image_id:
        data = await _download(bot, image_id)
        if data:
            result["images"] = [Image(content=data)]
    if audio_id:
        data = await _download(bot, audio_id)
        if data:
            result["audio"] = [Audio(content=data)]
    if video_id:
        data = await _download(bot, video_id)
        if data:
            result["videos"] = [Video(content=data)]
    if doc_meta:
        doc_size = doc_meta.get("file_size", 0)
        if doc_size and doc_size > TG_MAX_FILE_DOWNLOAD_SIZE:
            result["warning"] = f"File too large ({doc_size / _BYTES_PER_MB:.1f} MB). Please send a smaller file."
        else:
            data = await _download(bot, doc_meta["file_id"])
            if data:
                result["files"] = [File(content=data, filename=doc_meta.get("file_name"))]

    return result


async def send_html(
    bot: "AsyncTeleBot",
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
) -> Any:
    try:
        return await bot.send_message(
            chat_id,
            markdown_to_telegram_html(text),
            parse_mode="HTML",
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )
    except Exception:
        return await bot.send_message(
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )


async def edit_html(bot: "AsyncTeleBot", text: str, chat_id: int, message_id: int) -> Any:
    try:
        return await bot.edit_message_text(markdown_to_telegram_html(text), chat_id, message_id, parse_mode="HTML")
    except Exception:
        return await bot.edit_message_text(text, chat_id, message_id)


async def send_chunked(
    bot: "AsyncTeleBot",
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
) -> None:
    if len(text) <= TG_MAX_MESSAGE_LENGTH:
        await send_html(
            bot, chat_id, text, reply_to_message_id=reply_to_message_id, message_thread_id=message_thread_id
        )
        return
    chunks: List[str] = [text[i : i + TG_CHUNK_SIZE] for i in range(0, len(text), TG_CHUNK_SIZE)]
    for i, chunk in enumerate(chunks, 1):
        reply_id = reply_to_message_id if i == 1 else None
        await send_html(
            bot,
            chat_id,
            f"[{i}/{len(chunks)}] {chunk}",
            reply_to_message_id=reply_id,
            message_thread_id=message_thread_id,
        )


async def send_response_media(
    bot: "AsyncTeleBot",
    response: Any,
    chat_id: int,
    reply_to: Optional[int],
    message_thread_id: Optional[int] = None,
) -> bool:
    any_media_sent = False
    content = getattr(response, "content", None)
    raw_caption = str(content)[:TG_MAX_CAPTION_LENGTH] if content else None

    media_senders = [
        ("images", bot.send_photo),
        ("audio", bot.send_audio),
        ("videos", bot.send_video),
        ("files", bot.send_document),
    ]
    for attr, sender in media_senders:
        items = getattr(response, attr, None)
        if not items:
            continue
        for item in items:
            try:
                data = getattr(item, "url", None)
                if not data:
                    get_bytes = getattr(item, "get_content_bytes", None)
                    data = get_bytes() if callable(get_bytes) else None
                if data:
                    caption = markdown_to_telegram_html(raw_caption) if raw_caption else None
                    send_kwargs: dict = dict(
                        caption=caption,
                        reply_to_message_id=reply_to,
                        message_thread_id=message_thread_id,
                        parse_mode="HTML" if caption else None,
                    )
                    try:
                        await sender(chat_id, data, **send_kwargs)  # type: ignore[operator]
                    except Exception:
                        send_kwargs["caption"] = raw_caption
                        send_kwargs["parse_mode"] = None
                        await sender(chat_id, data, **send_kwargs)  # type: ignore[operator]
                    any_media_sent = True
                    # Clear caption and reply_to after first successful send
                    raw_caption = None
                    reply_to = None
            except Exception as e:
                log_error(f"Failed to send {attr.rstrip('s')} to chat {chat_id}: {e}")

    return any_media_sent
