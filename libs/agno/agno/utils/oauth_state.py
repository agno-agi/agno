import hashlib
import hmac
import time
from typing import Any, Dict


def sign_state(payload: Dict[str, Any], secret: str, ttl_seconds: int = 600) -> str:
    """Return an HS256-signed JWT carrying payload with iat and exp claims."""
    import jwt

    now = int(time.time())
    return jwt.encode(
        {**payload, "iat": now, "exp": now + ttl_seconds},
        _derive_key(secret),
        algorithm="HS256",
    )


def verify_state(token: str, secret: str, leeway_seconds: int = 60) -> Dict[str, Any]:
    """Verify and decode a token from sign_state. Raises jwt.InvalidTokenError on failure."""
    import jwt

    return jwt.decode(
        token,
        _derive_key(secret),
        algorithms=["HS256"],
        leeway=leeway_seconds,
    )


def decode_state_insecure(token: str) -> Dict[str, Any]:
    """Decode without signature verification. For debugging only."""
    import jwt

    return jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])


def _derive_key(secret: str) -> bytes:
    return hmac.new(secret.encode(), b"agno-state-token", hashlib.sha256).digest()
