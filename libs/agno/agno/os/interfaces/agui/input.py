import base64
import json
import urllib.request
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Tuple

from ag_ui.core.types import Message as AGUIMessage
from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_warning


def extract_user_input(messages: List[AGUIMessage]) -> str:
    """Extract the last user message content from AG-UI messages.

    AG-UI frontends send the full conversation history on every request.
    The agent manages its own history via session DB, so we only need the
    latest user message as input — matching the REST API pattern.
    """
    for msg in reversed(messages):
        if msg.role == "user" and msg.content is not None:
            if isinstance(msg.content, str):
                return msg.content
            if isinstance(msg.content, list):
                text_parts = []
                for part in msg.content:
                    if hasattr(part, "type") and part.type == "text" and hasattr(part, "text"):
                        text_parts.append(part.text)
                if text_parts:
                    return "\n".join(text_parts)
    return ""


def extract_media(
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


def validate_state(state: Any, thread_id: str) -> Optional[Dict[str, Any]]:
    """Validate the given AGUI state is of the expected type (dict)."""
    if state is None:
        return None

    if isinstance(state, dict):
        return state

    if isinstance(state, BaseModel):
        try:
            return state.model_dump()
        except Exception:
            pass

    if is_dataclass(state):
        try:
            return asdict(state)  # type: ignore
        except Exception:
            pass

    if hasattr(state, "to_dict") and callable(getattr(state, "to_dict")):
        try:
            result = state.to_dict()  # type: ignore
            if isinstance(result, dict):
                return result
        except Exception:
            pass

    log_warning(f"AGUI state must be a dict, got {type(state).__name__}. State will be ignored. Thread: {thread_id}")
    return None


def extract_context(context: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
    """Convert AG-UI context to dicts, decoding JSON string values."""
    if not context:
        return None

    entries = []
    for i, item in enumerate(context, start=1):
        value = item.value
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
        entries.append({
            "description": item.description or f"context_{i}",
            "value": value,
        })
    return entries or None


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
