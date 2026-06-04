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

    # 1. Find the last user message
    for msg in reversed(messages):
        if msg.role != "user" or msg.content is None:
            continue

        # String content has no media
        if isinstance(msg.content, str):
            return images, audio, videos, files

        # 2. Process each content part
        for part in msg.content:
            if not hasattr(part, "type"):
                continue

            # 3. Extract content bytes and MIME type based on part structure
            content: Optional[bytes] = None
            url: Optional[str] = None
            mime: Optional[str] = None
            filename: Optional[str] = None

            if part.type == "binary":
                # BinaryInputContent: flat structure (deprecated but still used)
                mime = getattr(part, "mime_type", None)
                filename = getattr(part, "filename", None)
                url = getattr(part, "url", None)
                data = getattr(part, "data", None)
                if not url and data:
                    content = _decode_base64(data)

            elif part.type in ("image", "audio", "video", "document"):
                # Typed content: nested source structure
                source = getattr(part, "source", None)
                if source and hasattr(source, "type"):
                    mime = getattr(source, "mime_type", None)
                    value = getattr(source, "value", None)
                    if source.type == "url" and value:
                        url = value
                    elif source.type == "data" and value:
                        content = _decode_base64(value)

            # 4. Create Agno media object and append to correct list
            # Route by part.type first (typed content), fall back to MIME (binary content)
            if url or content:
                if part.type == "image" or (mime and mime.startswith("image/")):
                    images.append(Image(url=url, content=content, mime_type=mime))
                elif part.type == "audio" or (mime and mime.startswith("audio/")):
                    audio.append(Audio(url=url, content=content, mime_type=mime))
                elif part.type == "video" or (mime and mime.startswith("video/")):
                    videos.append(Video(url=url, content=content, mime_type=mime))
                else:
                    # File validates MIME — pass None for unsupported types to avoid raising
                    safe_mime = mime if mime in File.valid_mime_types() else None
                    files.append(File(url=url, content=content, mime_type=safe_mime, filename=filename))

        return images, audio, videos, files

    return images, audio, videos, files


def _decode_base64(value: str) -> Optional[bytes]:
    """Decode base64 string to bytes. Handles data: URLs and raw base64."""
    try:
        # data: URLs embed MIME and base64 together, urllib handles them
        if value.startswith("data:"):
            return urllib.request.urlopen(value).read()
        return base64.b64decode(value, validate=True)
    except Exception:
        log_warning("Failed to decode base64 content")
        return None
