import re
from typing import TYPE_CHECKING, Any, List, NamedTuple, Optional

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from telebot.async_telebot import AsyncTeleBot

TG_MAX_MESSAGE_LENGTH = 4096
TG_CHUNK_SIZE = 4000
TG_MAX_CAPTION_LENGTH = 1024
TG_GROUP_CHAT_TYPES = {"group", "supergroup"}
TG_MAX_FILE_DOWNLOAD_SIZE = 20 * 1024 * 1024  # 20 MB — Telegram API download limit
_BYTES_PER_MB = 1024 * 1024
_TG_MAX_FILE_DOWNLOAD_MB = TG_MAX_FILE_DOWNLOAD_SIZE // _BYTES_PER_MB


class ParsedMessage(NamedTuple):
    text: Optional[str]
    image_file_id: Optional[str]
    audio_file_id: Optional[str]
    video_file_id: Optional[str]
    document_meta: Optional[dict]


# ---------------------------------------------------------------------------
# Markdown -> Telegram HTML conversion
# ---------------------------------------------------------------------------


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_to_telegram_html(text: str) -> str:
    lines = text.split("\n")
    result: list[str] = []
    in_code_block = False
    code_block_lines: list[str] = []
    code_lang = ""

    for line in lines:
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = line.strip().removeprefix("```").strip()
                code_block_lines = []
            else:
                in_code_block = False
                code_content = _escape_html("\n".join(code_block_lines))
                if code_lang:
                    result.append(f'<pre><code class="language-{_escape_html(code_lang)}">{code_content}</code></pre>')
                else:
                    result.append(f"<pre>{code_content}</pre>")
            continue
        if in_code_block:
            code_block_lines.append(line)
            continue

        line = _convert_inline_markdown(line)
        result.append(line)

    # Handle unclosed code block
    if in_code_block:
        code_content = _escape_html("\n".join(code_block_lines))
        result.append(f"<pre>{code_content}</pre>")

    return "\n".join(result)


# Handles one level of nested parens in URLs (e.g. Wikipedia links)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(((?:[^()]*|\([^()]*\))*)\)")


def _escape_html_attr(url: str) -> str:
    # Minimal escaping for href attributes: &, ", <, >
    return url.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _convert_inline_markdown(line: str) -> str:
    heading_match = re.match(r"^(#{1,6})\s+(.*)", line)
    if heading_match:
        return f"<b>{_format_line_with_links(heading_match.group(2))}</b>"
    return _format_line_with_links(line)


def _format_line_with_links(line: str) -> str:
    # Extract links BEFORE HTML-escaping to preserve raw URLs
    placeholders: list[str] = []

    def _replace_link(m: re.Match) -> str:
        display = _escape_html(m.group(1))
        display = _apply_inline_formatting(display)
        url = _escape_html_attr(m.group(2))
        tag = f'<a href="{url}">{display}</a>'
        idx = len(placeholders)
        placeholders.append(tag)
        return f"\x00LINK{idx}\x00"

    line = _LINK_RE.sub(_replace_link, line)
    line = _escape_html(line)
    line = _apply_inline_formatting(line)
    for i, tag in enumerate(placeholders):
        line = line.replace(f"\x00LINK{i}\x00", tag)
    return line


def _apply_inline_formatting(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    return text


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------


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
        image_file_id = message["sticker"]["file_id"]
        message_text = "Describe this sticker"
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


# ---------------------------------------------------------------------------
# File download helpers (require bot instance)
# ---------------------------------------------------------------------------


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
                if doc_mime and doc_mime not in File.valid_mime_types():
                    log_warning(f"Unsupported file type: {doc_mime} ({doc_name})")
                    warning = (
                        f"Note: The file type '{doc_mime}' ({doc_name}) is not directly supported. "
                        "I'll try my best to process it, but results may vary. "
                        "Supported types: PDF, JSON, DOCX, TXT, HTML, CSS, CSV, XML, RTF, and code files."
                    )
                files = [
                    File(
                        content=doc_bytes,
                        mime_type=doc_mime if doc_mime in File.valid_mime_types() else None,
                        filename=doc_name,
                    )
                ]

    return images, audio, videos, files, warning


# ---------------------------------------------------------------------------
# Outbound message helpers (require bot instance)
# ---------------------------------------------------------------------------


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
