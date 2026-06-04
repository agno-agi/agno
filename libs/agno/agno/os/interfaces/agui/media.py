import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from ag_ui.core.types import Message as AGUIMessage

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_warning

# MIME types whose Agno `format` differs from the raw subtype (e.g. OpenAI audio expects "mp3")
_MIME_TO_FORMAT: Dict[str, str] = {
    "audio/mpeg": "mp3",
}


def _format_from_mime_type(mime_type: Optional[str]) -> Optional[str]:
    """Return the Agno media `format` for a MIME type (e.g. 'image/png' -> 'png'), or None."""
    if not mime_type or "/" not in mime_type:
        return None
    return _MIME_TO_FORMAT.get(mime_type, mime_type.split("/")[-1])


def _decode_agui_base64_content(value: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Decode an AG-UI base64 value and return bytes plus any data URL MIME type."""
    mime_type = None
    encoded_value = value

    if value.startswith("data:") and "," in value:
        metadata, encoded_value = value.split(",", 1)
        if metadata.startswith("data:"):
            mime_type = metadata[5:].split(";", 1)[0] or None

    try:
        return base64.b64decode(encoded_value, validate=True), mime_type
    except ValueError:
        log_warning("Failed to decode AG-UI data source. Content part will be ignored.")
        return None, mime_type


def _safe_file_mime_type(mime_type: Optional[str]) -> Optional[str]:
    """Return the MIME type only if it is a valid Agno File MIME type, else None."""
    if mime_type in File.valid_mime_types():
        return mime_type
    return None


@dataclass
class AGUIUserInputMedia:
    """Media extracted from an AG-UI user message."""

    images: List[Image] = field(default_factory=list)
    audio: List[Audio] = field(default_factory=list)
    videos: List[Video] = field(default_factory=list)
    files: List[File] = field(default_factory=list)


# AG-UI typed media content type -> (Agno media class, AGUIUserInputMedia field, sanitize MIME)
_AGUI_MEDIA_PARTS: Dict[str, Tuple[type, str, bool]] = {
    "image": (Image, "images", False),
    "audio": (Audio, "audio", False),
    "video": (Video, "videos", False),
    "document": (File, "files", True),
}


_AGUIMedia = TypeVar("_AGUIMedia", Image, Audio, Video, File)


def _extract_agui_media(part: Any, media_cls: Type[_AGUIMedia], sanitize_mime: bool = False) -> Optional[_AGUIMedia]:
    """Convert a typed AG-UI input content part into the given Agno media object."""
    source = getattr(part, "source", None)
    if source is None:
        return None

    source_type = getattr(source, "type", None)
    value = getattr(source, "value", None)
    if not value:
        return None

    mime_type = getattr(source, "mime_type", None)
    content_kwargs: Dict[str, Any]
    if source_type == "url":
        content_kwargs = {"url": value}
    elif source_type == "data":
        content, data_url_mime_type = _decode_agui_base64_content(value)
        if content is None:
            return None
        content_kwargs = {"content": content}
        mime_type = mime_type or data_url_mime_type
    else:
        return None

    extra_kwargs: Dict[str, Any] = {}
    if media_cls is File:
        metadata = getattr(part, "metadata", None)
        filename = metadata.get("filename") if isinstance(metadata, dict) else None
        if filename:
            extra_kwargs["filename"] = filename

    return media_cls(
        format=_format_from_mime_type(mime_type),
        mime_type=_safe_file_mime_type(mime_type) if sanitize_mime else mime_type,
        **extra_kwargs,
        **content_kwargs,
    )


def _extract_agui_binary(part: Any, media: AGUIUserInputMedia) -> None:
    """Route AG-UI binary input content into the matching Agno media bucket."""
    mime_type = getattr(part, "mime_type", None)
    binary_id = getattr(part, "id", None)
    url = getattr(part, "url", None)
    data = getattr(part, "data", None)
    filename = getattr(part, "filename", None)
    content = None
    data_url_mime_type = None

    if data:
        content, data_url_mime_type = _decode_agui_base64_content(data)
        if content is None:
            return

    binary_mime_type = mime_type or data_url_mime_type
    media_format = _format_from_mime_type(binary_mime_type)
    content_kwargs: Dict[str, Any]
    if url:
        content_kwargs = {"url": url}
    elif content is not None:
        content_kwargs = {"content": content}
    else:
        return

    if binary_mime_type and binary_mime_type.startswith("image/"):
        media.images.append(Image(id=binary_id, mime_type=binary_mime_type, format=media_format, **content_kwargs))
    elif binary_mime_type and binary_mime_type.startswith("audio/"):
        media.audio.append(Audio(id=binary_id, mime_type=binary_mime_type, format=media_format, **content_kwargs))
    elif binary_mime_type and binary_mime_type.startswith("video/"):
        media.videos.append(Video(id=binary_id, mime_type=binary_mime_type, format=media_format, **content_kwargs))
    else:
        media.files.append(
            File(
                id=binary_id,
                mime_type=_safe_file_mime_type(binary_mime_type),
                filename=filename,
                format=media_format,
                **content_kwargs,
            )
        )


def extract_agui_user_input_and_media(messages: List[AGUIMessage]) -> Tuple[str, AGUIUserInputMedia]:
    """Extract the last user message text and media parts from AG-UI messages.

    AG-UI frontends send the full conversation history on every request.
    The agent manages its own history via session DB, so we only need the
    latest user message as input — matching the REST API pattern.
    """
    for msg in reversed(messages):
        if msg.role == "user" and msg.content is not None:
            if isinstance(msg.content, str):
                return msg.content, AGUIUserInputMedia()
            if isinstance(msg.content, list):
                text_parts = []
                media = AGUIUserInputMedia()
                for part in msg.content:
                    part_type = getattr(part, "type", None)
                    if part_type == "text" and hasattr(part, "text"):
                        text_parts.append(part.text)
                    elif part_type == "binary":
                        _extract_agui_binary(part, media)
                    elif part_type in _AGUI_MEDIA_PARTS:
                        media_cls, field_name, sanitize = _AGUI_MEDIA_PARTS[part_type]
                        extracted = _extract_agui_media(part, media_cls, sanitize_mime=sanitize)
                        if extracted is not None:
                            getattr(media, field_name).append(extracted)
                return "\n".join(text_parts), media
    return "", AGUIUserInputMedia()


def extract_agui_user_input_and_images(messages: List[AGUIMessage]) -> Tuple[str, List[Image]]:
    """Extract the last user message text and image parts from AG-UI messages."""
    user_input, media = extract_agui_user_input_and_media(messages)
    return user_input, media.images


def extract_agui_user_input(messages: List[AGUIMessage]) -> str:
    """Extract only the text from the last user message."""
    user_input, _ = extract_agui_user_input_and_media(messages)
    return user_input
