"""Sign and verify short-lived self-issued JWT state tokens (HS256).

For OAuth redirect flows (Google, GitHub, etc.) and any round-trip-through-
third-party scenario where tamper-proof identity needs to survive an external
redirect. Opposite direction from ``agno.os.middleware.jwt.JWTValidator``,
which validates *incoming* third-party JWTs.

PyJWT is lazy-imported inside the functions so this module can live on the
hot import path without pulling ``agno[os]`` extras into core installs.
"""

import hashlib
import hmac
import time
from typing import Any, Dict


def sign_state(payload: Dict[str, Any], secret: str, ttl_seconds: int = 600) -> str:
    """Return an HS256-signed JWT carrying ``payload`` + ``iat`` + ``exp``."""
    import jwt

    now = int(time.time())
    return jwt.encode(
        {**payload, "iat": now, "exp": now + ttl_seconds},
        _derive_key(secret),
        algorithm="HS256",
    )


def verify_state(token: str, secret: str, leeway_seconds: int = 60) -> Dict[str, Any]:
    """Verify a token produced by ``sign_state``. Raises ``jwt.InvalidTokenError`` on failure."""
    import jwt

    return jwt.decode(
        token,
        _derive_key(secret),
        algorithms=["HS256"],
        leeway=leeway_seconds,
    )


def decode_state_insecure(token: str) -> Dict[str, Any]:
    """Decode a state JWT WITHOUT signature verification. INSECURE - dev only."""
    import jwt

    return jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])


def _derive_key(secret: str) -> bytes:
    """HMAC-SHA256 derive a deterministic 32-byte subkey from the shared secret."""
    return hmac.new(secret.encode(), b"agno-state-token", hashlib.sha256).digest()
