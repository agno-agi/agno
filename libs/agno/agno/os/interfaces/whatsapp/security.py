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
