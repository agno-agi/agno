import base64
import urllib.request
from typing import List, Optional, Tuple

from ag_ui.core.types import Message as AGUIMessage

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_warning


def _decode_base64(value: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Decode base64 (with or without data: prefix) to bytes and MIME type."""
    try:
        if value.startswith("data:"):
            resp = urllib.request.urlopen(value)
            return resp.read(), resp.headers.get_content_type()
        return base64.b64decode(value, validate=True), None
    except Exception:
        log_warning("Failed to decode base64 content")
        return None, None


def extract_agui_user_input_and_media(
    messages: List[AGUIMessage],
) -> Tuple[str, List[Image], List[Audio], List[Video], List[File]]:
    """Extract text and media from the last user message.

    Returns (text, images, audio, videos, files) - same pattern as Slack helpers.
    """
    images: List[Image] = []
    audio: List[Audio] = []
    videos: List[Video] = []
    files: List[File] = []

    for msg in reversed(messages):
        if msg.role != "user" or msg.content is None:
            continue

        if isinstance(msg.content, str):
            return msg.content, images, audio, videos, files

        text_parts: List[str] = []

        for part in msg.content:
            part_type = getattr(part, "type", None)

            if part_type == "text":
                text_parts.append(getattr(part, "text", ""))

            elif part_type == "binary":
                url = getattr(part, "url", None)
                data = getattr(part, "data", None)
                mime = getattr(part, "mime_type", None)
                filename = getattr(part, "filename", None)

                content = None
                if not url and data:
                    content, data_mime = _decode_base64(data)
                    mime = mime or data_mime

                kwargs = {"url": url} if url else {"content": content} if content else None
                if kwargs:
                    _append_by_mime(mime, kwargs, filename, images, audio, videos, files)

            elif part_type in ("image", "audio", "video", "document"):
                source = getattr(part, "source", None)
                if not source:
                    continue

                src_type = getattr(source, "type", None)
                value = getattr(source, "value", None)
                mime = getattr(source, "mime_type", None)

                if src_type == "url" and value:
                    _append_by_mime(mime, {"url": value}, None, images, audio, videos, files)
                elif src_type == "data" and value:
                    content, data_mime = _decode_base64(value)
                    if content:
                        _append_by_mime(mime or data_mime, {"content": content}, None, images, audio, videos, files)

        return "\n".join(text_parts), images, audio, videos, files

    return "", images, audio, videos, files


def _append_by_mime(
    mime: Optional[str],
    kwargs: dict,
    filename: Optional[str],
    images: List[Image],
    audio: List[Audio],
    videos: List[Video],
    files: List[File],
) -> None:
    """Route media to the correct list based on MIME type."""
    if mime and mime.startswith("image/"):
        images.append(Image(mime_type=mime, **kwargs))
    elif mime and mime.startswith("audio/"):
        audio.append(Audio(mime_type=mime, **kwargs))
    elif mime and mime.startswith("video/"):
        videos.append(Video(mime_type=mime, **kwargs))
    else:
        # File validates MIME - pass None if invalid to avoid raising
        safe_mime = mime if mime in File.valid_mime_types() else None
        files.append(File(mime_type=safe_mime, filename=filename, **kwargs))


def extract_agui_user_input_and_images(messages: List[AGUIMessage]) -> Tuple[str, List[Image]]:
    """Extract text and images from the last user message."""
    text, images, _, _, _ = extract_agui_user_input_and_media(messages)
    return text, images


def extract_agui_user_input(messages: List[AGUIMessage]) -> str:
    """Extract only text from the last user message (skips media extraction)."""
    for msg in reversed(messages):
        if msg.role != "user" or msg.content is None:
            continue
        if isinstance(msg.content, str):
            return msg.content
        return "\n".join(getattr(p, "text", "") for p in msg.content if getattr(p, "type", None) == "text")
    return ""
