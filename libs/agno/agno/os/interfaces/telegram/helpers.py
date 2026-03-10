from typing import TYPE_CHECKING, Any, List, NamedTuple, Optional

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
_TG_MAX_FILE_DOWNLOAD_MB = TG_MAX_FILE_DOWNLOAD_SIZE // _BYTES_PER_MB


class ParsedMessage(NamedTuple):
    text: Optional[str]
    image_file_id: Optional[str]
    audio_file_id: Optional[str]
    video_file_id: Optional[str]
    document_meta: Optional[dict]


def message_mentions_bot(message: dict, bot_username: str) -> bool:
    text = message.get("text", "") or message.get("caption", "")
    entities = message.get("entities", []) or message.get("caption_entities", [])
    # NOTE: Telegram entity offsets are UTF-16 code units; Python slices by
    # code points. Mentions after non-BMP characters (e.g. emoji) may be
    # misparsed. Acceptable trade-off for now.
    for entity in entities:
        if entity.get("type") == "mention":
            offset = entity["offset"]
            length = entity["length"]
            mention = text[offset : offset + length].lstrip("@").lower()
            if mention == bot_username.lower():
                return True
    return False


def parse_inbound_message(message: dict) -> ParsedMessage:
    message_text: Optional[str] = None
    image_file_id: Optional[str] = None
    audio_file_id: Optional[str] = None
    video_file_id: Optional[str] = None
    document_meta: Optional[dict] = None

    if message.get("text"):
        message_text = message["text"]
    elif message.get("photo"):
        image_file_id = message["photo"][-1]["file_id"]
        message_text = message.get("caption", "Describe the image")
    elif message.get("sticker"):
        sticker = message["sticker"]
        is_animated = sticker.get("is_animated", False)
        is_video = sticker.get("is_video", False)
        emoji = sticker.get("emoji", "")
        set_name = sticker.get("set_name", "")

        if is_animated or is_video:
            # Animated (.tgs) and video (.webm) stickers are not valid image
            # formats for model APIs.  Use the JPEG thumbnail instead.
            thumbnail = sticker.get("thumbnail") or sticker.get("thumb")
            if thumbnail:
                image_file_id = thumbnail["file_id"]
        else:
            # Static .webp stickers are natively supported.
            image_file_id = sticker["file_id"]

        desc = "Describe this sticker"
        if emoji:
            desc += f" (emoji: {emoji})"
        if set_name:
            desc += f" from set '{set_name}'"
        message_text = desc
    elif message.get("voice"):
        audio_file_id = message["voice"]["file_id"]
        message_text = message.get("caption", "Transcribe or describe this audio")
    elif message.get("audio"):
        audio_file_id = message["audio"]["file_id"]
        message_text = message.get("caption", "Describe this audio")
    elif message.get("video") or message.get("video_note") or message.get("animation"):
        vid: dict = message.get("video") or message.get("video_note") or message.get("animation")  # type: ignore[assignment]
        video_file_id = vid["file_id"]
        message_text = message.get("caption", "Describe this video")
    elif message.get("document"):
        document_meta = message["document"]
        message_text = message.get("caption", "Process this file")

    return ParsedMessage(message_text, image_file_id, audio_file_id, video_file_id, document_meta)


async def get_file_bytes(bot: "AsyncTeleBot", file_id: str) -> Optional[bytes]:
    try:
        file_info = await bot.get_file(file_id)
        file_size = getattr(file_info, "file_size", None)
        if isinstance(file_size, (int, float)) and file_size > TG_MAX_FILE_DOWNLOAD_SIZE:
            size_mb = file_size / _BYTES_PER_MB
            log_warning(f"File too large to download: {file_id} ({size_mb:.1f} MB)")
            return None
        return await bot.download_file(file_info.file_path)
    except Exception as e:
        log_error(f"Error downloading file: {e}")
        return None


async def download_inbound_media(
    bot: "AsyncTeleBot",
    image_file_id: Optional[str],
    audio_file_id: Optional[str],
    video_file_id: Optional[str],
    document_meta: Optional[dict],
) -> tuple[Optional[List[Image]], Optional[List[Audio]], Optional[List[Video]], Optional[List[File]], Optional[str]]:
    images: Optional[List[Image]] = None
    audio: Optional[List[Audio]] = None
    videos: Optional[List[Video]] = None
    files: Optional[List[File]] = None
    warning: Optional[str] = None

    if image_file_id:
        image_bytes = await get_file_bytes(bot, image_file_id)
        if image_bytes:
            images = [Image(content=image_bytes)]
    if audio_file_id:
        audio_bytes = await get_file_bytes(bot, audio_file_id)
        if audio_bytes:
            audio = [Audio(content=audio_bytes)]
    if video_file_id:
        video_bytes = await get_file_bytes(bot, video_file_id)
        if video_bytes:
            videos = [Video(content=video_bytes)]
    if document_meta:
        doc_name = document_meta.get("file_name", "unknown")
        doc_size = document_meta.get("file_size", 0)
        if doc_size and doc_size > TG_MAX_FILE_DOWNLOAD_SIZE:
            size_mb = doc_size / _BYTES_PER_MB
            log_warning(f"File too large to download: {doc_name} ({size_mb:.1f} MB)")
            warning = (
                f"The file '{doc_name}' ({size_mb:.1f} MB) exceeds the {_TG_MAX_FILE_DOWNLOAD_MB} MB download limit "
                "for Telegram bots. Please send a smaller file."
            )
        else:
            doc_bytes = await get_file_bytes(bot, document_meta["file_id"])
            if doc_bytes:
                doc_mime = document_meta.get("mime_type")
                valid_mimes = File.valid_mime_types()
                if doc_mime and doc_mime not in valid_mimes:
                    log_warning(f"Unsupported file type: {doc_mime} ({doc_name})")
                    warning = (
                        f"Note: The file type '{doc_mime}' ({doc_name}) is not directly supported. "
                        "I'll try my best to process it, but results may vary. "
                        "Supported types: PDF, JSON, DOCX, TXT, HTML, CSS, CSV, XML, RTF, and code files."
                    )
                files = [
                    File(
                        content=doc_bytes,
                        mime_type=doc_mime if doc_mime in valid_mimes else None,
                        filename=doc_name,
                    )
                ]

    return images, audio, videos, files, warning


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
