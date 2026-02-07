import hmac
import os
from typing import Optional

from agno.utils.log import log_warning


def is_development_mode() -> bool:
    return os.getenv("APP_ENV", "development").lower() == "development"


def get_webhook_secret_token() -> str:
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN")
    if not secret:
        raise ValueError("TELEGRAM_WEBHOOK_SECRET_TOKEN environment variable is not set in production mode")
    return secret


def validate_webhook_secret_token(secret_token_header: Optional[str]) -> bool:
    if is_development_mode():
        log_warning("Bypassing secret token validation in development mode")
        return True

    if not secret_token_header:
        return False

    expected = get_webhook_secret_token()
    return hmac.compare_digest(secret_token_header, expected)
