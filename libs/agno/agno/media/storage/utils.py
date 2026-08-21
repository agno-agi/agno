import mimetypes
import re
from typing import Optional


def _sanitize_media_id(media_id: str) -> str:
    """Make a media id safe to use as a storage-key path component.

    Everything outside ``[A-Za-z0-9._-]`` becomes an underscore, so no path separator
    survives to traverse out of the storage root or add a prefix in S3.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(media_id))
    return safe.strip("._") or "media"


def build_storage_key(
    media_id: str,
    *,
    prefix: str = "",
    filename: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> str:
    """Build a storage key of the form ``{prefix}{sanitized media_id}{extension}``.

    The extension comes from the original filename when it carries one, else from the
    mime type, so a stored object keeps a suffix that content-type sniffing recognizes.
    """
    media_id = _sanitize_media_id(media_id)
    ext = ""
    if filename and "." in filename:
        # The filename is caller-supplied: strip separators and cap the tail at a filesystem-safe length.
        ext = re.sub(r"[^A-Za-z0-9]", "", filename.rsplit(".", 1)[-1])[:16]
        ext = f".{ext}" if ext else ""
    if not ext and mime_type:
        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            ext = guessed
        else:
            # agno mints types mimetypes has no entry for (audio/wav, video/mov, ...), so fall back to
            # a bare-token subtype; the compound types this would mangle are the ones mimetypes resolves.
            subtype = mime_type.split("/", 1)[1].lower() if "/" in mime_type else ""
            if re.fullmatch(r"[a-z0-9]{1,8}", subtype):
                ext = f".{subtype}"
    return f"{prefix}{media_id}{ext}"
