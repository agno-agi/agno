import hashlib
import hmac
import os
import time
from typing import Optional

from agno.utils.log import log_warning


def get_app_secret() -> str:
    app_secret = os.getenv("WHATSAPP_APP_SECRET")
    if not app_secret:
        raise ValueError("WHATSAPP_APP_SECRET environment variable is not set")
    return app_secret


def validate_webhook_signature(
    payload: bytes, signature_header: Optional[str], timestamp: Optional[int] = None
) -> bool:
    """Validate the webhook payload using SHA256 signature.

    Args:
        payload: The raw request payload bytes
        signature_header: The X-Hub-Signature-256 header value
        timestamp: Optional Unix timestamp from the message for replay protection

    Returns:
        bool: True if signature is valid and timestamp is within 5-minute window
    """
    if timestamp is not None:
        if abs(time.time() - timestamp) > 300:
            log_warning("Rejecting webhook: timestamp too old (possible replay attack)")
            return False

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    app_secret = get_app_secret()
    expected_signature = signature_header.split("sha256=")[1]

    hmac_obj = hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256)
    calculated_signature = hmac_obj.hexdigest()

    return hmac.compare_digest(calculated_signature, expected_signature)
