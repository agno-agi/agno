import asyncio
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
    "fetched_at": 0.0,  # wall clock, for the 24h TTL
    "fetched_monotonic": 0.0,  # monotonic, for the forced-refresh floor
    "jwks_uri": None,
}
_jwks_lock = Lock()
_async_jwks_lock: Optional[asyncio.Lock] = None

# The kid comes from an unverified header, so any caller can invent one and
# force a refresh. Keys fetched seconds ago cannot have rotated, so refuse below
# this age. Monotonic: a backwards wall-clock step would otherwise suppress
# every refresh until the clock caught up.
_MIN_FORCED_REFRESH_SECONDS = 60.0


def dev_bypass_enabled() -> bool:
    """Package-public: TeamsConfig consults it too, since credentials are
    optional in exactly this mode."""
    return os.getenv("MICROSOFT_APP_SKIP_JWT_VALIDATION", "").lower() == "true"


async def _fetch_openid_metadata() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_OPENID_METADATA_URL)
        resp.raise_for_status()
        return resp.json()


async def _fetch_jwks(jwks_uri: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        return resp.json().get("keys", [])


def _cache_is_fresh(now: float) -> bool:
    return bool(_jwks_cache["keys"]) and now - _jwks_cache["fetched_at"] < _JWKS_CACHE_TTL_SECONDS


async def _get_jwks() -> List[Dict[str, Any]]:
    """Return Microsoft's signing keys, refetching once the TTL has passed or
    the caller has cleared ``fetched_at``.

    Double-checked: the lock-free read is safe because no await sits between it
    and the return, and holding the lock across the fetch collapses concurrent
    callers into one round trip.
    """
    global _async_jwks_lock

    now = time.time()
    # Fast path: lock-free cache read
    if _cache_is_fresh(now):
        return _jwks_cache["keys"]

    # A sync lock guards creating the async one: two coroutines racing here would
    # otherwise each build a lock and neither would exclude the other.
    with _jwks_lock:
        if _async_jwks_lock is None:
            _async_jwks_lock = asyncio.Lock()
    lock = _async_jwks_lock

    async with lock:
        # Slow path: re-check, then fetch and write under the lock
        if _cache_is_fresh(time.time()):
            return _jwks_cache["keys"]

        metadata = await _fetch_openid_metadata()
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise RuntimeError("Bot Framework OpenID metadata missing 'jwks_uri'")

        keys = await _fetch_jwks(jwks_uri)
        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = time.time()
        _jwks_cache["fetched_monotonic"] = time.monotonic()
        _jwks_cache["jwks_uri"] = jwks_uri
        return keys


async def _find_key_for_kid(kid: str) -> Optional[Dict[str, Any]]:
    for key in await _get_jwks():
        if key.get("kid") == kid:
            return key
    return None


async def validate_bot_framework_jwt(auth_header: Optional[str], app_id: str) -> bool:
    """Verify a Bot Framework JWT from an inbound `Authorization` header.

    True on success, False on any validation failure, which the router turns
    into a 403. Raises HTTPException(500) for the two configuration errors it can
    tell apart from a bad token: no app id and no bypass, or a missing
    `pyjwt[crypto]`.
    """
    if not app_id:
        # Explicit opt-out: operator must deliberately set this for local dev.
        # With an app id there is a real audience to verify against, so the flag
        # is ignored below and a configured deployment cannot be downgraded.
        if dev_bypass_enabled():
            log_warning("MICROSOFT_APP_SKIP_JWT_VALIDATION=true — Bot Framework JWT check disabled")
            return True
        raise HTTPException(
            status_code=500,
            detail=("MICROSOFT_APP_ID is not set. Set MICROSOFT_APP_SKIP_JWT_VALIDATION=true for local development."),
        )

    if not auth_header or not auth_header.lower().startswith("bearer "):
        return False

    token = auth_header.split(" ", 1)[1].strip()

    try:
        import jwt
    except ImportError:
        raise HTTPException(status_code=500, detail=_MISSING_CRYPTO_DETAIL)

    # pyjwt imports cleanly without cryptography and reports the gap only here.
    # Unchecked, RS256 fails deep inside and the handler below calls it a bad
    # token, sending the operator to debug their registration instead.
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
        jwk = await _find_key_for_kid(kid)
        if not jwk:
            forced = False
            with _jwks_lock:
                if time.monotonic() - _jwks_cache["fetched_monotonic"] > _MIN_FORCED_REFRESH_SECONDS:
                    _jwks_cache["fetched_at"] = 0.0
                    forced = True
            # Without a refresh the second lookup would re-scan the same cached
            # list, so only repeat it when there is something new to find.
            if forced:
                jwk = await _find_key_for_kid(kid)
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
