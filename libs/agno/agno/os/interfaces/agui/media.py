import base64
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ag_ui.core.types import Message as AGUIMessage

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_warning

_VALID_FILE_MIMES = frozenset(File.valid_mime_types())


@dataclass
class AGUIUserInputMedia:
    images: List[Image] = field(default_factory=list)
    audio: List[Audio] = field(default_factory=list)
    videos: List[Video] = field(default_factory=list)
    files: List[File] = field(default_factory=list)


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


def _append_media(media: AGUIUserInputMedia, mime: Optional[str], **kwargs) -> None:
    """Append media object to the appropriate list based on MIME type."""
    if mime and mime.startswith("image/"):
        media.images.append(Image(mime_type=mime, **kwargs))
    elif mime and mime.startswith("audio/"):
        media.audio.append(Audio(mime_type=mime, **kwargs))
    elif mime and mime.startswith("video/"):
        media.videos.append(Video(mime_type=mime, **kwargs))
    else:
        safe_mime = mime if mime in _VALID_FILE_MIMES else None
        media.files.append(File(mime_type=safe_mime, **kwargs))


def extract_agui_user_input_and_media(messages: List[AGUIMessage]) -> Tuple[str, AGUIUserInputMedia]:
    """Extract text and media from the last user message."""
    for msg in reversed(messages):
        if msg.role != "user" or msg.content is None:
            continue

        if isinstance(msg.content, str):
            return msg.content, AGUIUserInputMedia()

        text_parts: List[str] = []
        media = AGUIUserInputMedia()

        for part in msg.content:
            part_type = getattr(part, "type", None)

            if part_type == "text":
                text_parts.append(getattr(part, "text", ""))

            elif part_type == "binary":
                # BinaryInputContent: flat structure with url/data/mime_type/filename
                url = getattr(part, "url", None)
                data = getattr(part, "data", None)
                mime = getattr(part, "mime_type", None)
                filename = getattr(part, "filename", None)

                if url:
                    _append_media(media, mime, url=url, filename=filename)
                elif data:
                    content, data_mime = _decode_base64(data)
                    if content:
                        _append_media(media, mime or data_mime, content=content, filename=filename)

            elif part_type in ("image", "audio", "video", "document"):
                # Typed content: nested source with type/value/mime_type
                source = getattr(part, "source", None)
                if not source:
                    continue

                src_type = getattr(source, "type", None)
                value = getattr(source, "value", None)
                mime = getattr(source, "mime_type", None)

                if src_type == "url" and value:
                    _append_media(media, mime, url=value)
                elif src_type == "data" and value:
                    content, data_mime = _decode_base64(value)
                    if content:
                        _append_media(media, mime or data_mime, content=content)

        return "\n".join(text_parts), media

    return "", AGUIUserInputMedia()


def extract_agui_user_input_and_images(messages: List[AGUIMessage]) -> Tuple[str, List[Image]]:
    """Extract text and images from the last user message."""
    text, media = extract_agui_user_input_and_media(messages)
    return text, media.images


def extract_agui_user_input(messages: List[AGUIMessage]) -> str:
    """Extract only text from the last user message (skips media extraction)."""
    for msg in reversed(messages):
        if msg.role != "user" or msg.content is None:
            continue
        if isinstance(msg.content, str):
            return msg.content
        return "\n".join(getattr(p, "text", "") for p in msg.content if getattr(p, "type", None) == "text")
    return ""
