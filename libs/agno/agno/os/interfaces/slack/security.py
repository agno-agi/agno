import hashlib
import hmac
import time
from os import getenv
from typing import Optional

from fastapi import HTTPException

from agno.utils.log import log_error

try:
    SLACK_SIGNING_SECRET = getenv("SLACK_SIGNING_SECRET")
except Exception as e:
    log_error(f"Slack signin secret missing: {e}")


def verify_slack_signature(
    body: bytes, timestamp: str, slack_signature: str, signing_secret: Optional[str] = None
) -> bool:
    secret = signing_secret if signing_secret is not None else SLACK_SIGNING_SECRET
    if not secret:
        raise HTTPException(status_code=500, detail="SLACK_SIGNING_SECRET is not set")

    # Ensure the request timestamp is recent (e.g., to prevent replay attacks)
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    my_signature = "v0=" + hmac.new(secret.encode("utf-8"), sig_basestring.encode("utf-8"), hashlib.sha256).hexdigest()

    return hmac.compare_digest(my_signature, slack_signature)
