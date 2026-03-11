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

# Binary formats that should stay as File objects, not inlined as text
_BINARY_MIME_TYPES = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


class MessageContent(NamedTuple):
    text: str
    images: Optional[List[Image]]
    audio: Optional[List[Audio]]
    videos: Optional[List[Video]]
    files: Optional[List[File]]
    warning: Optional[str]


def is_bot_mentioned(message: dict, bot_username: str) -> bool:
    text = message.get("text", "") or message.get("caption", "")
    return f"@{bot_username.lower()}" in (text or "").lower()


async def _download(bot: "AsyncTeleBot", file_id: str) -> Optional[bytes]:
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


def _inline_text_files(text: str, files: Optional[List[File]]) -> tuple[str, Optional[List[File]]]:
    if not files:
        return text, files
    kept: List[File] = []
    for f in files:
        if f.mime_type and f.mime_type in _BINARY_MIME_TYPES:
            kept.append(f)
        elif f.content:
            try:
                decoded = f.content.decode("utf-8", errors="replace") if isinstance(f.content, bytes) else str(f.content)
                label = f.filename or "file"
                text += f"\n\n--- {label} ---\n{decoded}"
            except Exception:
                kept.append(f)
        else:
            kept.append(f)
    return text, kept or None


async def extract_message_content(bot: "AsyncTeleBot", message: dict) -> Optional[MessageContent]:
    text: Optional[str] = None
    image_file_id: Optional[str] = None
    audio_file_id: Optional[str] = None
    video_file_id: Optional[str] = None
    document_meta: Optional[dict] = None

    if message.get("text"):
        text = message["text"]
    elif message.get("photo"):
        image_file_id = message["photo"][-1]["file_id"]
        text = message.get("caption")
    elif message.get("sticker"):
        sticker = message["sticker"]
        if sticker.get("is_animated") or sticker.get("is_video"):
            # Animated/video stickers aren't valid image formats — use thumbnail
            thumbnail = sticker.get("thumbnail") or sticker.get("thumb")
            if thumbnail:
                image_file_id = thumbnail["file_id"]
        else:
            image_file_id = sticker["file_id"]
    elif message.get("voice"):
        audio_file_id = message["voice"]["file_id"]
        text = message.get("caption")
    elif message.get("audio"):
        audio_file_id = message["audio"]["file_id"]
        text = message.get("caption")
    elif message.get("video") or message.get("video_note") or message.get("animation"):
        vid: dict = message.get("video") or message.get("video_note") or message.get("animation")  # type: ignore[assignment]
        video_file_id = vid["file_id"]
        text = message.get("caption")
    elif message.get("document"):
        document_meta = message["document"]
        text = message.get("caption")

    has_media = image_file_id or audio_file_id or video_file_id or document_meta
    if text is None and not has_media:
        return None

    # Download media
    images: Optional[List[Image]] = None
    audio: Optional[List[Audio]] = None
    videos: Optional[List[Video]] = None
    files: Optional[List[File]] = None
    warning: Optional[str] = None

    if image_file_id:
        data = await _download(bot, image_file_id)
        if data:
            images = [Image(content=data)]
    if audio_file_id:
        data = await _download(bot, audio_file_id)
        if data:
            audio = [Audio(content=data)]
    if video_file_id:
        data = await _download(bot, video_file_id)
        if data:
            videos = [Video(content=data)]
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
            data = await _download(bot, document_meta["file_id"])
            if data:
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
                        content=data,
                        mime_type=doc_mime if doc_mime in valid_mimes else None,
                        filename=doc_name,
                    )
                ]

    # Inline text-based files into message text
    msg_text = text or ""
    msg_text, files = _inline_text_files(msg_text, files)

    return MessageContent(msg_text, images, audio, videos, files, warning)


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
