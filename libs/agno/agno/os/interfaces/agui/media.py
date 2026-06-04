"""AG-UI media extraction utilities."""

import base64
import urllib.request
from typing import List, Optional, Tuple

from ag_ui.core.types import Message as AGUIMessage

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_warning


def extract_agui_media(
    messages: List[AGUIMessage],
) -> Tuple[List[Image], List[Audio], List[Video], List[File]]:
    """Extract media from the last user message.

    Returns (images, audio, videos, files) tuple.
    """
    images: List[Image] = []
    audio: List[Audio] = []
    videos: List[Video] = []
    files: List[File] = []

    for msg in reversed(messages):
        if msg.role != "user" or msg.content is None:
            continue
        if isinstance(msg.content, str):
            return images, audio, videos, files

        for part in msg.content:
            part_type = getattr(part, "type", None)

            # Binary content has flat structure: url/data/mime_type/filename
            if part_type == "binary":
                url = getattr(part, "url", None)
                data = getattr(part, "data", None)
                mime = getattr(part, "mime_type", None)
                filename = getattr(part, "filename", None)

                if url:
                    _append_media(images, audio, videos, files, mime, url=url, filename=filename)
                elif data:
                    content, data_mime = _decode_base64(data)
                    if content:
                        _append_media(images, audio, videos, files, mime or data_mime, content=content, filename=filename)

            # Typed content has nested source: source.type/source.value/source.mime_type
            elif part_type in ("image", "audio", "video", "document"):
                source = getattr(part, "source", None)
                if not source:
                    continue
                src_type = getattr(source, "type", None)
                value = getattr(source, "value", None)
                mime = getattr(source, "mime_type", None)

                if src_type == "url" and value:
                    _append_media(images, audio, videos, files, mime, url=value)
                elif src_type == "data" and value:
                    content, data_mime = _decode_base64(value)
                    if content:
                        _append_media(images, audio, videos, files, mime or data_mime, content=content)

        return images, audio, videos, files

    return images, audio, videos, files


def _decode_base64(value: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Decode base64 (with or without data: URL prefix) to bytes and MIME type."""
    try:
        if value.startswith("data:"):
            resp = urllib.request.urlopen(value)
            return resp.read(), resp.headers.get_content_type()
        return base64.b64decode(value, validate=True), None
    except Exception:
        log_warning("Failed to decode base64 content")
        return None, None


def _append_media(
    images: List[Image],
    audio: List[Audio],
    videos: List[Video],
    files: List[File],
    mime: Optional[str],
    **kwargs,
) -> None:
    """Append media object to the correct list based on MIME type."""
    if mime and mime.startswith("image/"):
        images.append(Image(mime_type=mime, **kwargs))
    elif mime and mime.startswith("audio/"):
        audio.append(Audio(mime_type=mime, **kwargs))
    elif mime and mime.startswith("video/"):
        videos.append(Video(mime_type=mime, **kwargs))
    else:
        safe_mime = mime if mime in File.valid_mime_types() else None
        files.append(File(mime_type=safe_mime, **kwargs))
