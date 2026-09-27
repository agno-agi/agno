import re
from typing import Any, Dict, Optional

_UNSAFE_HEADER_CHARS = re.compile(r"[^\t\x20-\x7e]")

# DeleteObjects accepts at most 1000 keys per call.
S3_DELETE_BATCH_SIZE = 1000

# SigV4 signs for at most seven days, and boto3 does not check.
S3_MAX_PRESIGNED_EXPIRY = 7 * 24 * 60 * 60


def sanitize_s3_metadata(items: Dict[str, Any], *, max_bytes: int = 1800) -> Dict[str, str]:
    """Coerce metadata to ASCII-only string values that S3 accepts.

    S3 user metadata travels as HTTP headers, so it must be ASCII, free of control characters,
    and small (~2KB total) — one value carrying a newline fails the whole upload. Entries that
    cannot be encoded, carry a control character, or would exceed the size budget are dropped;
    the full metadata is preserved on the MediaReference.
    """
    safe: Dict[str, str] = {}
    total = 0
    for k, v in items.items():
        try:
            # Lowercased because S3 does: two keys differing only in case break the signature.
            key = str(k).encode("ascii").decode("ascii").lower()
            val = str(v).encode("ascii").decode("ascii")
        except UnicodeEncodeError:
            continue
        if _UNSAFE_HEADER_CHARS.search(key) or _UNSAFE_HEADER_CHARS.search(val):
            continue
        total += len(key) + len(val)
        if total > max_bytes:
            break
        safe[key] = val
    return safe


def raise_if_acl_unsupported(error: Exception, bucket: Optional[str]) -> None:
    """Re-raise S3's ACL rejection as an actionable configuration error.

    The offload layer downgrades an upload failure to a warning, so this message is all the
    user ever sees.
    """
    from botocore.exceptions import ClientError

    if (
        isinstance(error, ClientError)
        and error.response.get("Error", {}).get("Code") == "AccessControlListNotSupported"
    ):
        raise ValueError(
            f"Bucket '{bucket}' does not allow ACLs. Drop the acl argument; get_url() returns presigned URLs."
        ) from error
