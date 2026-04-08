import os
import time
from typing import Any, Optional

from agno.os.interfaces.shared import is_dev_mode
from agno.utils.log import log_warning

# Public key is fixed per app — cache VerifyKey to avoid re-parsing on every request
_verify_key_cache: dict[str, Any] = {}


def _get_verify_key(key_hex: str) -> Any:
    cached = _verify_key_cache.get(key_hex)
    if cached is not None:
        return cached
    try:
        from nacl.signing import VerifyKey
    except ImportError as e:
        raise ImportError("PyNaCl is not installed. Install it via `pip install PyNaCl`.") from e
    vk = VerifyKey(bytes.fromhex(key_hex))
    _verify_key_cache[key_hex] = vk
    return vk


def verify_discord_signature(
    body: bytes,
    signature: str,
    timestamp: str,
    *,
    public_key: Optional[str] = None,
) -> bool:
    if is_dev_mode():
        log_warning("Bypassing Discord signature validation in development mode")
        return True

    if not signature or not timestamp:
        return False

    key = public_key or os.getenv("DISCORD_PUBLIC_KEY")
    if not key:
        raise ValueError("DISCORD_PUBLIC_KEY is not set. Set the env var or pass public_key.")

    # Reject stale requests to block replay attacks (5-minute window)
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False

    try:
        verify_key = _get_verify_key(key)
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except Exception:
        return False
