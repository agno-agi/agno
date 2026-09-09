import hashlib
import hmac
import os
from typing import Optional

from fastapi import HTTPException

from agno.utils.log import log_warning


def validate_webhook_signature(payload: bytes, signature_header: Optional[str]) -> bool:
    app_secret = os.getenv("WHATSAPP_APP_SECRET")
    if not app_secret:
        # Explicit opt-out: operator must deliberately set this for local dev
        if os.getenv("WHATSAPP_SKIP_SIGNATURE_VALIDATION", "").lower() == "true":
            log_warning("WHATSAPP_SKIP_SIGNATURE_VALIDATION=true — signature check disabled")
            return True
        raise HTTPException(
            status_code=500,
            detail="WHATSAPP_APP_SECRET not set. Set WHATSAPP_SKIP_SIGNATURE_VALIDATION=true for local development.",
        )

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    # Header format: "sha256=<hex>"; strip prefix to compare digests
    expected_signature = signature_header.removeprefix("sha256=")

    hmac_obj = hmac.new(app_secret.encode(), payload, hashlib.sha256)
    calculated_signature = hmac_obj.hexdigest()

    # Constant-time comparison prevents timing side-channels
    return hmac.compare_digest(calculated_signature, expected_signature)


def verify_token_matches(provided_token: Optional[str], expected_token: str) -> bool:
    """Compare the webhook verification token against the configured one in constant time.

    ``hub.verify_token`` is supplied by the caller on an unauthenticated endpoint, so a
    plain ``==`` short-circuits on the first differing byte and lets the token be
    recovered one character at a time from response timing. The values are encoded first
    because ``hmac.compare_digest`` rejects non-ASCII ``str`` input: query params are
    caller-controlled text and the expected token comes from the environment, so either
    side can carry non-ASCII characters.
    """
    if not provided_token:
        return False
    return hmac.compare_digest(
        provided_token.encode("utf-8", "surrogateescape"), expected_token.encode("utf-8", "surrogateescape")
    )
