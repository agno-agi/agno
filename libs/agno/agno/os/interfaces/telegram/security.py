import hmac
import os
from typing import Optional

from agno.utils.log import log_warning

# Cached at import; tests monkeypatch the module attrs directly
_APP_ENV = os.getenv("APP_ENV", "").lower()
_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN")


def _is_dev_mode() -> bool:
    return _APP_ENV == "development"


def get_webhook_secret_token() -> str:
    if not _WEBHOOK_SECRET:
        raise ValueError("TELEGRAM_WEBHOOK_SECRET_TOKEN environment variable is not set in production mode")
    return _WEBHOOK_SECRET


def validate_webhook_secret_token(secret_token_header: Optional[str]) -> bool:
    if _is_dev_mode():
        log_warning("Bypassing secret token validation in development mode")
        return True

    if not secret_token_header:
        return False

    expected = get_webhook_secret_token()
    return hmac.compare_digest(secret_token_header, expected)
