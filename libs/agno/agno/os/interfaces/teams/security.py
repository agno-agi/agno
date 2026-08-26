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

_MISSING_CRYPTO_DETAIL = (
    "`pyjwt[crypto]` not installed. Please install using `pip install 'pyjwt[crypto]'`, "
    "or set MICROSOFT_APP_SKIP_JWT_VALIDATION=true for local development."
)

_jwks_cache: Dict[str, Any] = {
    "keys": None,  # list[dict]
    "fetched_at": 0.0,
    "jwks_uri": None,
}
_jwks_lock = Lock()


def dev_bypass_enabled() -> bool:
    """True when the operator explicitly opted out of JWT validation for local dev.

    Public within the package: TeamsConfig consults it too, because credentials
    are optional in exactly this mode.
    """
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
        return keys


def _find_key_for_kid(kid: str) -> Optional[Dict[str, Any]]:
    for key in _get_jwks():
        if key.get("kid") == kid:
            return key
    return None


def validate_bot_framework_jwt(auth_header: Optional[str], app_id: str) -> bool:
    """Verify a Bot Framework JWT from an inbound webhook `Authorization` header.

    Returns True on success, False on any validation failure. The router converts
    False to a 403 response. Raises HTTPException(500) only if `pyjwt[crypto]` is
    not installed (a configuration error, not a validation failure).

    `MICROSOFT_APP_SKIP_JWT_VALIDATION=true` bypasses the check for local
    development, and only when no app id is configured — a deployment with
    credentials cannot be downgraded by an env var.
    """
    if not app_id:
        # Explicit opt-out: operator must deliberately set this for local dev.
        # Gated on the absence of credentials the way whatsapp/security.py gates
        # on a missing WHATSAPP_APP_SECRET; with an app id there is a real
        # audience to verify against, so the flag is ignored below.
        if dev_bypass_enabled():
            log_warning("MICROSOFT_APP_SKIP_JWT_VALIDATION=true — Bot Framework JWT check disabled")
            return True
        raise HTTPException(
            status_code=500,
            detail=(
                "MICROSOFT_APP_ID is not set. Set MICROSOFT_APP_SKIP_JWT_VALIDATION=true "
                "for local development."
            ),
        )

    if not auth_header or not auth_header.lower().startswith("bearer "):
        return False

    token = auth_header.split(" ", 1)[1].strip()

    try:
        import jwt
    except ImportError:
        raise HTTPException(status_code=500, detail=_MISSING_CRYPTO_DETAIL)

    # pyjwt imports cleanly without cryptography -- it guards its own crypto
    # imports -- and reports the gap only here. Left unchecked, RS256 fails deep
    # inside and the broad handler below reports it as a bad token, sending the
    # operator to debug their bot registration instead of their install.
    if not getattr(jwt.algorithms, "has_crypto", False):
        raise HTTPException(status_code=500, detail=_MISSING_CRYPTO_DETAIL)

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
