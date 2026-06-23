import base64
import hashlib
import hmac
import secrets
import time
from typing import Any, Dict, Optional

from agno.utils.log import log_debug, log_error


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


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256).

    Returns:
        (code_verifier, code_challenge) tuple.

    code_verifier: 64-char random string (A-Z, a-z, 0-9, -._~)
    code_challenge: Base64URL(SHA256(code_verifier)), no padding
    """
    code_verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def store_pkce_state(
    db: Any,
    provider: str,
    user_id: Optional[str],
    service: str,
    code_verifier: str,
    state_id: str,
) -> bool:
    """Store PKCE state for OAuth flow, preserving existing token_data and granted_scopes.

    Passes token_data={} and granted_scopes=[] to signal upsert_auth_token
    to preserve existing values on conflict, avoiding read-modify-write races.
    Requested scopes live in the OAuth URL and signed JWT, not in the PKCE row.
    """
    if db is None:
        return False

    token: Dict[str, Any] = {
        "provider": provider,
        "user_id": user_id,
        "service": service,
        "token_data": {},  # Empty = preserve existing on conflict
        "granted_scopes": [],  # Empty = preserve existing on conflict
        "pkce_verifier": code_verifier,
        "pkce_state_id": state_id,
    }

    try:
        return db.upsert_auth_token(token) is not None
    except NotImplementedError:
        log_debug("DB does not support auth token storage")
        return False
    except Exception as e:
        log_error(f"Failed to store PKCE state: {e}")
        return False
