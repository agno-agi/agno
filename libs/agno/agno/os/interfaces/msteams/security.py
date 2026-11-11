import asyncio
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException

from agno.utils.log import log_warning

try:
    import jwt
    from jwt import PyJWKClient
except ImportError as e:
    raise ImportError("`pyjwt[crypto]` not installed. Please install using `pip install 'agno[msteams]'`.") from e

_OPENID_METADATA_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
_EXPECTED_ISSUER = "https://api.botframework.com"
_MISSING_CRYPTO_DETAIL = "`pyjwt[crypto]` not installed. Please install using `pip install 'agno[msteams]'`."


class _BotFrameworkJWKClient(PyJWKClient):
    def fetch_data(self) -> Any:
        # get_signing_key holds PyJWT's lock and runs off the event loop.
        if self.uri == _OPENID_METADATA_URL:
            self.uri = _fetch_openid_metadata()["jwks_uri"]
        data = super().fetch_data()
        self.endorsements = {key["kid"]: key.get("endorsements") for key in data.get("keys", []) if key.get("kid")}
        return data


_jwk_client = _BotFrameworkJWKClient(_OPENID_METADATA_URL, timeout=10)


def dev_bypass_enabled() -> bool:
    """Allow credential-free local development only when explicitly enabled."""
    return os.getenv("MICROSOFT_APP_SKIP_JWT_VALIDATION", "").lower() == "true"


def _fetch_openid_metadata() -> Dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        resp = client.get(_OPENID_METADATA_URL)
        resp.raise_for_status()
        return resp.json()


async def validate_bot_framework_jwt(
    auth_header: Optional[str], app_id: str, service_url: Optional[str], channel_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Return verified claims, or None for an invalid Bot Framework activity."""
    if not app_id:
        if dev_bypass_enabled():
            return {}
        raise HTTPException(status_code=500, detail="MICROSOFT_APP_ID is not set.")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    if not jwt.algorithms.has_crypto:
        raise HTTPException(status_code=500, detail=_MISSING_CRYPTO_DETAIL)

    token = auth_header.split(" ", 1)[1].strip()
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        if not kid:
            return None
        client = _jwk_client
        signing_key = await asyncio.to_thread(client.get_signing_key, kid)
        claims = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=["RS256"],
            audience=app_id,
            issuer=_EXPECTED_ISSUER,
            leeway=300,
            options={"require": ["exp", "iss", "aud", "serviceurl"]},
        )
        if not service_url or claims["serviceurl"] != service_url:
            return None
        endorsements = client.endorsements.get(kid)
        if channel_id and endorsements and channel_id not in endorsements:
            return None
        return claims
    except Exception as e:
        log_warning(f"Bot Framework JWT validation failed: {str(e)}")
        return None
