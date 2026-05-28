import base64
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Union

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_warning

# Common format -> MIME type mappings shared across Gemini model classes
FORMAT_TO_MIME: Dict[str, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "heic": "image/heic",
    "heif": "image/heif",
    "mp3": "audio/mp3",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "mp4": "video/mp4",
    "mov": "video/mov",
    "avi": "video/avi",
    "webm": "video/webm",
    "pdf": "application/pdf",
}


def get_mime_type(media: Union[Image, Audio, Video, File], default: str) -> str:
    """Get the MIME type from a media object, falling back to format-based detection or default."""
    if media.mime_type:
        return media.mime_type

    fmt = getattr(media, "format", None)
    if fmt:
        if fmt.lower() in FORMAT_TO_MIME:
            return FORMAT_TO_MIME[fmt.lower()]
        # For formats not in the map, infer from the default MIME category
        # e.g. default="audio/mp3" + fmt="m4a" -> "audio/m4a"
        category = default.split("/")[0] if "/" in default else "application"
        return f"{category}/{fmt.lower()}"

    filepath = getattr(media, "filepath", None)
    if filepath:
        suffix = Path(str(filepath)).suffix.lower().lstrip(".")
        if suffix in FORMAT_TO_MIME:
            return FORMAT_TO_MIME[suffix]

    return default


def media_to_content_item(
    media: Union[Image, Audio, Video, File], content_type: str, default_mime: str
) -> Optional[Dict[str, Any]]:
    """Convert an Agno media object to a content item dict for the Interactions API.

    Supports four content sources: URL/URI, raw bytes, filepath, and external GeminiFile.
    Returns a dict like {"type": "image", "data": base64_str, "mime_type": "image/jpeg"}.
    """
    mime_type = get_mime_type(media, default_mime)
    item: Dict[str, Any] = {"type": content_type, "mime_type": mime_type}

    # Case 1: URL
    url = getattr(media, "url", None)
    if url:
        # GCS URIs and Gemini File API URIs can be passed directly
        if url.startswith("gs://") or "generativelanguage.googleapis.com" in url:
            item["uri"] = url
            return item
        # For regular HTTP URLs, download and base64 encode
        try:
            import httpx

            headers = {"User-Agent": "Mozilla/5.0 (compatible; agno/1.0)"}
            response = httpx.get(url, follow_redirects=True, headers=headers)
            response.raise_for_status()
            item["data"] = base64.b64encode(response.content).decode("utf-8")
            return item
        except Exception as e:
            log_warning(f"Failed to download {content_type} from URL {url}: {e}")
            item["uri"] = url
            return item

    # Case 2: Raw bytes content
    content_bytes = getattr(media, "content", None)
    if content_bytes and isinstance(content_bytes, bytes):
        item["data"] = base64.b64encode(content_bytes).decode("utf-8")
        return item

    # Case 3: Filepath - read and base64 encode
    filepath = getattr(media, "filepath", None)
    if filepath:
        try:
            path = Path(str(filepath))
            if path.exists() and path.is_file():
                data = path.read_bytes()
                item["data"] = base64.b64encode(data).decode("utf-8")
                return item
            else:
                log_warning(f"File not found: {filepath}")
                return None
        except Exception as e:
            log_warning(f"Failed to read file {filepath}: {e}")
            return None

    # Case 4: For File objects, check 'external' (GeminiFile)
    external = getattr(media, "external", None)
    if external and hasattr(external, "uri"):
        item["uri"] = external.uri
        if hasattr(external, "mime_type") and external.mime_type:
            item["mime_type"] = external.mime_type
        return item

    log_warning(f"No content source found for {content_type} media object")
    return None


class GeminiFinishReason(Enum):
    """Gemini API finish reasons"""

    STOP = "STOP"
    MAX_TOKENS = "MAX_TOKENS"
    SAFETY = "SAFETY"
    RECITATION = "RECITATION"
    MALFORMED_FUNCTION_CALL = "MALFORMED_FUNCTION_CALL"
    OTHER = "OTHER"


# Guidance message used to retry a Gemini invocation after a MALFORMED_FUNCTION_CALL error
MALFORMED_FUNCTION_CALL_GUIDANCE = """The previous function call was malformed. Please try again with a valid function call.

Guidelines:
- Generate the function call JSON directly, do not generate code
- Use the function name exactly as defined (no namespace prefixes like 'default_api.')
- Ensure all required parameters are provided with correct types
"""
