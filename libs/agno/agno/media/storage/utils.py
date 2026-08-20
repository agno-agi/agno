import mimetypes
import re
from typing import Optional


def sanitize_media_id(media_id: str) -> str:
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
    Object stores take the whole key as the prefix; the local backend passes no prefix
    because it nests under ``base_path`` instead.
    """
    media_id = sanitize_media_id(media_id)
    ext = ""
    if filename and "." in filename:
        # Sanitized like the media id: the filename is caller-supplied, so a raw suffix
        # puts separators into the key and a long tail overruns the filesystem name limit.
        ext = re.sub(r"[^A-Za-z0-9]", "", filename.rsplit(".", 1)[-1])[:16]
        ext = f".{ext}" if ext else ""
    if not ext and mime_type:
        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            ext = guessed
    return f"{prefix}{media_id}{ext}"
