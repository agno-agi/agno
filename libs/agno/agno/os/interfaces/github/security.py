import hashlib
import hmac
from typing import Optional


def verify_signature(secret: str, body: bytes, signature_header: Optional[str]) -> bool:
    """True when the delivery was signed with this webhook's secret (X-Hub-Signature-256)."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # Constant-time comparison prevents timing side-channels
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))
