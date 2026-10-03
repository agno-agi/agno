"""Origin checks and authentication for voice pipe WebSockets.

A voice connection is authenticated before any speech provider connection opens
or the agent runs, so rejected callers never spend provider credentials.
"""

import asyncio
import hmac
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import WebSocket, WebSocketDisconnect

from agno.os.auth import verify_websocket_service_account
from agno.os.middleware.jwt import is_reserved_principal, resolve_expected_audience
from agno.os.scopes import AgentOSScope, get_default_scope_mappings, get_required_scopes_for_route, has_required_scopes
from agno.os.service_accounts import TOKEN_PREFIX as SERVICE_ACCOUNT_TOKEN_PREFIX
from agno.os.settings import AgnoAPISettings
from agno.os.utils import resolve_ws_jwt_config

if TYPE_CHECKING:
    from agno.voice.pipe import VoicePipe

AUTH_TIMEOUT = 10.0
MAX_AUTH_MESSAGE_CHARS = 8192


class VoiceAccessError(Exception):
    """The connection may not continue; the message is sent to the client."""


def origin_allowed(websocket: WebSocket, allowed_origins: List[str]) -> bool:
    origins = websocket.headers.getlist("origin")
    if not origins:
        return True  # Non-browser clients do not have an Origin header.
    if len(origins) != 1:
        return False
    origin = origins[0]
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return False
    if parsed.netloc.lower() == websocket.headers.get("host", "").lower():
        return True
    # A wildcard CORS setting must not let arbitrary websites spend the server's
    # speech credentials. Only explicitly named origins can open cross-site calls.
    return origin in allowed_origins


async def authenticate(websocket: WebSocket, pipe: "VoicePipe", settings: AgnoAPISettings) -> Optional[str]:
    """Authenticate the caller and return their user ID, or None when auth is off."""
    config = resolve_ws_jwt_config(websocket.app)
    jwt_required = bool(config.get("auth_required"))
    if jwt_required and config.get("validator") is None:
        raise VoiceAccessError("JWT authentication is misconfigured on the server")
    required = jwt_required or config.get("validator") is not None or bool(settings.os_security_key)

    token = await _read_token(websocket, required)
    if token is None:
        return None
    identity = await _identify(websocket, token, config, settings)
    _check_agent_access(identity, pipe, config)

    user_id = identity.get("user_id")
    await websocket.send_json({"event": "authenticated", "user_id": user_id})
    return user_id


async def _read_token(websocket: WebSocket, required: bool) -> Optional[str]:
    """Read a bearer token from the upgrade header, or ask for it as the first message.

    Browsers cannot set WebSocket upgrade headers, so they authenticate with an
    ``authenticate`` action after the server sends ``auth_required``.
    """
    authorization = websocket.headers.get("authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise VoiceAccessError("A bearer token is required")
        return token
    if not required:
        return None

    await websocket.send_json({"event": "auth_required"})
    try:
        message = await asyncio.wait_for(websocket.receive(), timeout=AUTH_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise VoiceAccessError("Authentication timed out") from exc
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    raw = message.get("text")
    if not isinstance(raw, str) or len(raw) > MAX_AUTH_MESSAGE_CHARS:
        raise VoiceAccessError("Send an authenticate action with a valid token")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise VoiceAccessError("Invalid authentication message") from exc
    if not isinstance(payload, dict) or payload.get("action") != "authenticate":
        raise VoiceAccessError("Send an authenticate action with a valid token")
    supplied = payload.get("token")
    if not isinstance(supplied, str) or not supplied:
        raise VoiceAccessError("A bearer token is required")
    return supplied


async def _identify(
    websocket: WebSocket, token: str, config: Dict[str, Any], settings: AgnoAPISettings
) -> Dict[str, Any]:
    """Resolve a token to an identity with ``user_id`` and, when known, ``scopes``."""
    if token.startswith(SERVICE_ACCOUNT_TOKEN_PREFIX):
        verification = await verify_websocket_service_account(
            token, websocket.app, client_key=websocket.client.host if websocket.client else None
        )
        account = verification.account if verification is not None and verification.ok else None
        if account is None:
            raise VoiceAccessError("Invalid or expired service account token")
        return {"user_id": account.principal, "scopes": list(account.scopes)}

    validator = config.get("validator")
    if validator is not None:
        try:
            audience = resolve_expected_audience(
                verify_audience=config.get("verify_audience", False),
                audience=config.get("audience"),
                os_id=getattr(websocket.app.state, "agent_os_id", None),
            )
            identity = validator.extract_claims(validator.validate_token(token, audience))
        except Exception as exc:
            raise VoiceAccessError("Invalid or expired token") from exc
        if is_reserved_principal(identity.get("user_id")):
            raise VoiceAccessError("Invalid token subject")
        return identity

    if settings.os_security_key:
        if not hmac.compare_digest(token, settings.os_security_key):
            raise VoiceAccessError("Invalid token")
        return {}

    # Supplied credentials must never turn into anonymous access on failure.
    raise VoiceAccessError("Authentication is not configured for this token")


def _check_agent_access(identity: Dict[str, Any], pipe: "VoicePipe", config: Dict[str, Any]) -> None:
    """A scoped identity needs the same permission as running the pipe's agent."""
    if "scopes" not in identity:
        return
    required_scopes = get_required_scopes_for_route(get_default_scope_mappings(), "POST", "/agents/_/runs")
    if not has_required_scopes(
        identity.get("scopes", []),
        required_scopes,
        resource_type="agents",
        resource_id=pipe.agent.id,
        admin_scope=config.get("admin_scope") or AgentOSScope.ADMIN.value,
    ):
        raise VoiceAccessError("Insufficient permissions to run this agent")
    if config.get("user_isolation") and not identity.get("user_id"):
        raise VoiceAccessError("Authenticated request is missing a user identity")
