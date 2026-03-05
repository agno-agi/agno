import hashlib
import hmac
import os
import time
from typing import Optional

from agno.utils.log import log_warning


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
    app_secret = os.getenv("WHATSAPP_APP_SECRET")
    if not app_secret:
        # Explicit opt-out: skip validation when secret is not configured
        log_warning("WHATSAPP_APP_SECRET not set — signature validation disabled (DO NOT use in production)")
        return True

    if timestamp is not None:
        if abs(time.time() - timestamp) > 300:
            log_warning("Rejecting webhook: timestamp too old (possible replay attack)")
            return False

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_signature = signature_header.removeprefix("sha256=")

    hmac_obj = hmac.new(app_secret.encode(), payload, hashlib.sha256)
    calculated_signature = hmac_obj.hexdigest()

    return hmac.compare_digest(calculated_signature, expected_signature)


def extract_earliest_timestamp(body: dict) -> Optional[int]:
    timestamps = []
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                ts = msg.get("timestamp")
                if ts:
                    try:
                        timestamps.append(int(ts))
                    except (ValueError, TypeError):
                        pass
    return min(timestamps) if timestamps else None
