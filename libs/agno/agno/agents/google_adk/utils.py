"""Utility functions for the Google ADK adapter."""

import mimetypes
from typing import Any, Dict, List, Optional

from agno.media.media import abytes_and_mime_from_url

_DEFAULT_MIME = {
    "images": "image/png",
    "audio": "audio/wav",
    "videos": "video/mp4",
    "files": "application/octet-stream",
}

# URI schemes Gemini can read directly; anything else is downloaded and sent inline.
_NATIVE_URI_PREFIXES = ("gs://", "https://generativelanguage.googleapis.com/")


def _mime_for(item: Any) -> Optional[str]:
    """The media type the caller set or one its format or file name implies; None when neither says."""
    mime = getattr(item, "mime_type", None)
    if mime:
        return str(mime)
    fmt = getattr(item, "format", None)
    if fmt:
        guessed, _ = mimetypes.guess_type(f"file.{str(fmt).lower().lstrip('.')}")
        if guessed:
            return guessed
    for attr in ("filepath", "filename", "url"):
        name = getattr(item, attr, None)
        if name:
            guessed, _ = mimetypes.guess_type(str(name))
            if guessed:
                return guessed
    return None


async def abuild_media_parts(media: Optional[Dict[str, List[Any]]]) -> List[Any]:
    """Convert Agno media objects into Gemini parts for the ADK user message.

    Bytes and local files go inline. A file uploaded through the Gemini Files API (File.external)
    and Google-hosted URIs (Cloud Storage, the Files API) are referenced by URI; other URLs are
    downloaded and sent inline, since the Gemini API does not fetch arbitrary web URLs, and the
    served Content-Type stands in when the URL itself does not say what the file is. Downloads
    and file reads are awaited so they do not block the event loop serving other runs.
    """
    from google.genai import types

    parts: List[Any] = []
    for kind, items in (media or {}).items():
        for item in items or []:
            external = getattr(item, "external", None)
            external_uri = getattr(external, "uri", None)
            external_mime = getattr(external, "mime_type", None)
            if external_uri and external_mime:
                parts.append(types.Part.from_uri(file_uri=str(external_uri), mime_type=str(external_mime)))
                continue
            mime = _mime_for(item)
            url = getattr(item, "url", None)
            remote_only = bool(url) and not getattr(item, "content", None) and not getattr(item, "filepath", None)
            if remote_only and str(url).startswith(_NATIVE_URI_PREFIXES):
                parts.append(types.Part.from_uri(file_uri=str(url), mime_type=mime or _DEFAULT_MIME[kind]))
                continue
            if remote_only and mime is None:
                data, served = await abytes_and_mime_from_url(str(url))
                mime = (served or "").split(";")[0].strip() or None
            else:
                data = await item.aget_content_bytes()
            if not data:
                raise ValueError(f"Could not read the {kind[:-1] if kind != 'audio' else 'audio'} input {item!r}")
            parts.append(types.Part.from_bytes(data=data, mime_type=mime or _DEFAULT_MIME[kind]))
    return parts
