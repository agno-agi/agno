"""Bounded byte-only media transport; service filesystem paths never cross the runtime RPC."""

import base64
import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from agno.agents._media import _mime_for, _name_for
from agno.media import File, Image

MAX_MEDIA_BYTES = 512 * 1024
MAX_MEDIA_ITEMS = 16
_MAX_BASE64 = MAX_MEDIA_BYTES * 4 // 3 + 4
_IMAGE_SIGNATURES = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"))


def encode_media(
    *, images: Optional[Sequence[Image]] = None, files: Optional[Sequence[File]] = None
) -> List[Dict[str, Any]]:
    """Validate Image/File inputs and return their runtime wire form.

    Bytes come from inline content or from an explicitly supplied regular local file; remote
    references are rejected. At most 16 attachments and 512 KiB of decoded bytes in total.
    """
    result: List[Dict[str, Any]] = []
    total = 0
    content: Any
    for kind, cls, items in (("image", Image, images), ("file", File, files)):
        for index, item in enumerate(items or []):
            if len(result) >= MAX_MEDIA_ITEMS:
                raise ValueError("Sandbox input accepts at most 16 attachments")
            if not isinstance(item, cls) or item.url or item.media_reference or getattr(item, "external", None):
                raise ValueError("Sandbox attachments require inline bytes or explicit local files")
            if item.filepath:
                fd = os.open(item.filepath, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError("Sandbox local attachments must be regular files")
                    if os.fstat(stream.fileno()).st_size > MAX_MEDIA_BYTES - total:
                        raise ValueError("Sandbox attachments exceed 512 KiB total")
                    content = stream.read(MAX_MEDIA_BYTES - total + 1)
            else:
                content = item.content
                if isinstance(content, str) and kind == "file":
                    content = content.encode()
                if not isinstance(content, bytes):
                    raise ValueError("Sandbox attachment content must be bytes")
            total += len(content)
            if total > MAX_MEDIA_BYTES:
                raise ValueError("Sandbox attachments exceed 512 KiB total")
            if kind == "image":
                # Image has no name field, so name it from its format exactly as the rebuilt image will be.
                item = item.model_copy(
                    update={"filepath": None, "format": item.format or _image_format(item.filepath, content)}
                )
            value = {"kind": kind, "content": base64.b64encode(content).decode(), "name": _name_for(item, kind, index)}
            mime = _mime_for(item)
            if mime is not None:
                value["mime_type"] = mime
            if item.format is not None:
                value["format"] = str(item.format)
            result.append(value)
    validate_media(result)
    return result


def _image_format(filepath: Any, content: bytes) -> Optional[str]:
    """An image's file suffix, else its byte signature, so the harness sees a real image extension."""
    if filepath:
        suffix = Path(str(filepath)).suffix.lstrip(".").lower()
        if suffix:
            return suffix
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return next((fmt for signature, fmt in _IMAGE_SIGNATURES if content.startswith(signature)), None)


def validate_media(value: Any) -> None:
    """Check the wire form; the runtime repeats this so it never trusts the service."""
    if not isinstance(value, list) or len(value) > MAX_MEDIA_ITEMS:
        raise ValueError("Sandbox media must be a list with at most 16 items")
    total = 0
    for item in value:
        if not isinstance(item, dict) or set(item) - {"kind", "content", "name", "mime_type", "format"}:
            raise ValueError("Unsupported sandbox attachment fields")
        if item.get("kind") not in ("image", "file"):
            raise ValueError("Unsupported sandbox attachment kind")
        name = item.get("name")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 120
            or any(char in name for char in ("/", "\\", "\x00"))
            or name in (".", "..")
        ):
            raise ValueError("Attachment name must be a bounded filename")
        for key in ("mime_type", "format"):
            if key in item and (not isinstance(item[key], str) or len(item[key]) > 128):
                raise ValueError("Attachment media metadata must be bounded strings")
        if item["kind"] == "file" and "mime_type" in item and item["mime_type"] not in File.valid_mime_types():
            raise ValueError(
                f"Sandbox file attachments must be documents, not {item['mime_type']}; pass images in images="
            )
        raw = item.get("content")
        if not isinstance(raw, str) or len(raw) > _MAX_BASE64:
            raise ValueError("Sandbox media content must be bounded base64")
        try:
            content = base64.b64decode(raw, validate=True)
        except ValueError as error:
            raise ValueError("Sandbox media content must be base64") from error
        if base64.b64encode(content).decode() != raw:
            raise ValueError("Sandbox media base64 must be canonical")
        total += len(content)
    if total > MAX_MEDIA_BYTES:
        raise ValueError("Sandbox attachments exceed 512 KiB total")


def decode_media(value: Any) -> Dict[str, Any]:
    """Rebuild ``images``/``files`` keyword arguments from the wire form."""
    validate_media(value)
    result: Dict[str, Any] = {}
    for index, item in enumerate(value):
        content = base64.b64decode(item["content"], validate=True)
        # Stable ids keep the persisted input identical when another process rebuilds the same bytes.
        identity = hashlib.sha256((item["kind"] + ":" + str(index) + ":" + item["name"]).encode() + content).hexdigest()
        fields = {key: item[key] for key in ("mime_type", "format") if key in item}
        if item["kind"] == "image":
            result.setdefault("images", []).append(Image(content=content, id=identity, **fields))
        else:
            result.setdefault("files", []).append(File(content=content, filename=item["name"], id=identity, **fields))
    return result
