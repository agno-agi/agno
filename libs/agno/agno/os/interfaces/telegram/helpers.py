from typing import TYPE_CHECKING, Any, List, Optional

from agno.media import Audio, File, Image, Video
from agno.os.interfaces.telegram.formatting import markdown_to_telegram_html
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from telebot.async_telebot import AsyncTeleBot

TG_MAX_MESSAGE_LENGTH = 4096
TG_CHUNK_SIZE = 4000
TG_MAX_FILE_DOWNLOAD_SIZE = 20 * 1024 * 1024
_BYTES_PER_MB = 1024 * 1024


def is_bot_mentioned(message: dict, bot_username: str) -> bool:
    text = message.get("text", "") or message.get("caption", "")
    return f"@{bot_username.lower()}" in (text or "").lower()


async def _download_file(bot: "AsyncTeleBot", file_id: str) -> Optional[bytes]:
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


def _extract_media_ids(message: dict) -> tuple[Optional[str], Optional[str], Optional[str], Optional[dict]]:
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


async def extract_message_payload(bot: "AsyncTeleBot", message: dict) -> Optional[dict]:
    text = message.get("text") or message.get("caption")
    image_id, audio_id, video_id, doc_meta = _extract_media_ids(message)

    if text is None and not (image_id or audio_id or video_id or doc_meta):
        return None

    result: dict = {"message": text or ""}

    if image_id:
        data = await _download_file(bot, image_id)
        if data:
            result["images"] = [Image(content=data)]
    if audio_id:
        data = await _download_file(bot, audio_id)
        if data:
            result["audio"] = [Audio(content=data)]
    if video_id:
        data = await _download_file(bot, video_id)
        if data:
            result["videos"] = [Video(content=data)]
    if doc_meta:
        doc_size = doc_meta.get("file_size", 0)
        if doc_size and doc_size > TG_MAX_FILE_DOWNLOAD_SIZE:
            result["warning"] = f"File too large ({doc_size / _BYTES_PER_MB:.1f} MB). Please send a smaller file."
        else:
            data = await _download_file(bot, doc_meta["file_id"])
            if data:
                result["files"] = [File(content=data, filename=doc_meta.get("file_name"))]

    return result


def _chunk_html(html_text: str, max_len: int = TG_CHUNK_SIZE) -> List[str]:
    # Split on paragraph boundaries to avoid cutting mid-tag
    if len(html_text) <= max_len:
        return [html_text]

    chunks: List[str] = []
    remaining = html_text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Find the last paragraph break (\n\n) within the limit
        cut = remaining.rfind("\n\n", 0, max_len)
        if cut <= 0:
            # Fall back to last newline
            cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            # Fall back to last space outside a tag
            cut = remaining.rfind(" ", 0, max_len)
        if cut <= 0:
            # Hard cut as last resort
            cut = max_len

        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    return chunks


async def send_message(
    bot: "AsyncTeleBot",
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
) -> Any:
    # Convert to HTML first, then check length — HTML can be much longer than
    # raw markdown (e.g. `<` → `&lt;` is 4x expansion)
    html_text = markdown_to_telegram_html(text)
    if len(html_text) <= TG_MAX_MESSAGE_LENGTH:
        return await bot.send_message(
            chat_id,
            html_text,
            parse_mode="HTML",
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )
    chunks = _chunk_html(html_text)
    result = None
    for i, chunk in enumerate(chunks, 1):
        reply_id = reply_to_message_id if i == 1 else None
        result = await bot.send_message(
            chat_id,
            chunk,
            parse_mode="HTML",
            reply_to_message_id=reply_id,
            message_thread_id=message_thread_id,
        )
    return result


async def send_response_media(
    bot: "AsyncTeleBot",
    response: Any,
    chat_id: int,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
) -> bool:
    any_media_sent = False

    items: list[tuple[Any, Any]] = []
    for img in getattr(response, "images", None) or []:
        items.append((img, bot.send_photo))
    for aud in getattr(response, "audio", None) or []:
        items.append((aud, bot.send_audio))
    for vid in getattr(response, "videos", None) or []:
        items.append((vid, bot.send_video))
    for doc in getattr(response, "files", None) or []:
        items.append((doc, bot.send_document))

    for item, sender in items:
        data = getattr(item, "url", None) or (item.get_content_bytes() if hasattr(item, "get_content_bytes") else None)
        if not data:
            continue
        try:
            await sender(
                chat_id,
                data,
                reply_to_message_id=reply_to_message_id,
                message_thread_id=message_thread_id,
            )
            any_media_sent = True
            reply_to_message_id = None
        except Exception as e:
            log_error(f"Failed to send media to chat {chat_id}: {e}")

    return any_media_sent
