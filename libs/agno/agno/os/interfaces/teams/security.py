import os
import time
from threading import Lock
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

from agno.utils.log import log_warning

_OPENID_METADATA_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
_EXPECTED_ISSUER = "https://api.botframework.com"

_JWKS_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h

_jwks_cache: Dict[str, Any] = {
    "keys": None,  # list[dict]
    "fetched_at": 0.0,
    "jwks_uri": None,
    "valid_token_issuers": None,  # list[str]
}
_jwks_lock = Lock()


def _skip_validation_enabled() -> bool:
    return os.getenv("MICROSOFT_APP_SKIP_JWT_VALIDATION", "").lower() == "true"


def _fetch_openid_metadata() -> Dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        resp = client.get(_OPENID_METADATA_URL)
        resp.raise_for_status()
        return resp.json()


def _fetch_jwks(jwks_uri: str) -> List[Dict[str, Any]]:
    with httpx.Client(timeout=10) as client:
        resp = client.get(jwks_uri)
        resp.raise_for_status()
        return resp.json().get("keys", [])


def _get_jwks() -> List[Dict[str, Any]]:
    now = time.time()
    with _jwks_lock:
        if _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < _JWKS_CACHE_TTL_SECONDS:
            return _jwks_cache["keys"]

        metadata = _fetch_openid_metadata()
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise RuntimeError("Bot Framework OpenID metadata missing 'jwks_uri'")

        keys = _fetch_jwks(jwks_uri)
        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = now
        _jwks_cache["jwks_uri"] = jwks_uri
        _jwks_cache["valid_token_issuers"] = metadata.get("issuer")
        return keys


def _find_key_for_kid(kid: str) -> Optional[Dict[str, Any]]:
    for key in _get_jwks():
        if key.get("kid") == kid:
            return key
    return None


def validate_bot_framework_jwt(auth_header: Optional[str], app_id: str) -> bool:
    """Verify a Bot Framework JWT from an inbound webhook `Authorization` header.

    Returns True on success; raises HTTPException(403) on failure.

    Set `MICROSOFT_APP_SKIP_JWT_VALIDATION=true` to bypass for local development —
    a warning is logged so it's obvious in logs.
    """
    if _skip_validation_enabled():
        log_warning("MICROSOFT_APP_SKIP_JWT_VALIDATION=true — Bot Framework JWT check disabled")
        return True

    if not auth_header or not auth_header.lower().startswith("bearer "):
        return False

    token = auth_header.split(" ", 1)[1].strip()

    try:
        import jwt
        from jwt import PyJWKClient  # noqa: F401  (imported to surface missing 'cryptography' extra early)
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail=(
                "`pyjwt[crypto]` not installed. Install with `pip install 'pyjwt[crypto]'` "
                "or set MICROSOFT_APP_SKIP_JWT_VALIDATION=true for local development."
            ),
        )

    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as e:
        log_warning(f"Malformed JWT header: {e}")
        return False

    kid = unverified_header.get("kid")
    if not kid:
        log_warning("JWT missing 'kid'")
        return False

    try:
        jwk = _find_key_for_kid(kid)
        if not jwk:
            with _jwks_lock:
                _jwks_cache["fetched_at"] = 0.0
            jwk = _find_key_for_kid(kid)
        if not jwk:
            log_warning(f"No matching JWK for kid={kid}")
            return False

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)  # type: ignore[attr-defined]

        jwt.decode(
            token,
            key=public_key,  # type: ignore[arg-type]
            algorithms=["RS256"],
            audience=app_id,
            issuer=_EXPECTED_ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
        return True
    except Exception as e:
        log_warning(f"Bot Framework JWT validation failed: {e}")
        return False
