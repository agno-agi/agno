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
    expires_at: int,
    scopes: Optional[list] = None,
) -> bool:
    """Store PKCE state for OAuth flow, preserving existing token_data.

    Uses get_auth_token + upsert_auth_token to keep OAuth utilities
    provider-agnostic while preserving credentials during re-auth flows.
    """
    if db is None:
        return False

    try:
        existing = db.get_auth_token(provider, user_id, service)
    except NotImplementedError:
        log_debug("DB does not support auth token storage")
        return False
    except Exception as e:
        log_error(f"Failed to load existing auth token for PKCE state: {e}")
        return False

    token_data = (existing or {}).get("token_data") or {}
    existing_scopes = (existing or {}).get("granted_scopes")

    token: Dict[str, Any] = {
        "provider": provider,
        "user_id": user_id,
        "service": service,
        "token_data": token_data,
        "granted_scopes": scopes if scopes is not None else existing_scopes,
        "pkce_verifier": code_verifier,
        "pkce_state_id": state_id,
        "pkce_expires_at": expires_at,
    }

    try:
        return db.upsert_auth_token(token) is not None
    except NotImplementedError:
        log_debug("DB does not support auth token storage")
        return False
    except Exception as e:
        log_error(f"Failed to store PKCE state: {e}")
        return False
