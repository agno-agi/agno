"""Voice pipe WebSocket transport with AgentOS authentication and agent permissions."""

import asyncio
import hmac
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.routing import Match

from agno.os.auth import verify_websocket_service_account
from agno.os.middleware.jwt import is_reserved_principal, resolve_expected_audience
from agno.os.scopes import AgentOSScope, get_default_scope_mappings, get_required_scopes_for_route, has_required_scopes
from agno.os.service_accounts import TOKEN_PREFIX as SERVICE_ACCOUNT_TOKEN_PREFIX
from agno.os.settings import AgnoAPISettings
from agno.os.utils import resolve_ws_jwt_config
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.os.app import AgentOS
    from agno.voice.pipe import VoicePipe


_AUTH_TIMEOUT = 10.0


class _VoiceAccessError(Exception):
    pass


def _origin_allowed(websocket: WebSocket, allowed_origins: List[str]) -> bool:
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


async def _authenticate(websocket: WebSocket, pipe: "VoicePipe", settings: AgnoAPISettings) -> Optional[str]:
    """Authenticate before opening provider connections or running an agent."""
    config = resolve_ws_jwt_config(websocket.app)
    validator = config.get("validator")
    jwt_required = bool(config.get("auth_required"))
    required = jwt_required or validator is not None or bool(settings.os_security_key)
    if jwt_required and validator is None:
        raise _VoiceAccessError("JWT authentication is misconfigured on the server")

    authorization = websocket.headers.get("authorization")
    token: Optional[str] = None
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise _VoiceAccessError("A bearer token is required")
    elif required:
        await websocket.send_json({"event": "auth_required"})
        try:
            message = await asyncio.wait_for(websocket.receive(), timeout=_AUTH_TIMEOUT)
        except asyncio.TimeoutError as exc:
            raise _VoiceAccessError("Authentication timed out") from exc
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        raw = message.get("text")
        if not isinstance(raw, str) or len(raw) > 8192:
            raise _VoiceAccessError("Send an authenticate action with a valid token")
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise _VoiceAccessError("Invalid authentication message") from exc
        if not isinstance(payload, dict) or payload.get("action") != "authenticate":
            raise _VoiceAccessError("Send an authenticate action with a valid token")
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise _VoiceAccessError("A bearer token is required")

    if token is None:
        return None

    identity: Dict[str, Any] = {}
    if token.startswith(SERVICE_ACCOUNT_TOKEN_PREFIX):
        verification = await verify_websocket_service_account(
            token, websocket.app, client_key=websocket.client.host if websocket.client else None
        )
        account = verification.account if verification is not None and verification.ok else None
        if account is None:
            raise _VoiceAccessError("Invalid or expired service account token")
        identity = {"user_id": account.principal, "scopes": list(account.scopes)}
    elif validator is not None:
        try:
            audience = resolve_expected_audience(
                verify_audience=config.get("verify_audience", False),
                audience=config.get("audience"),
                os_id=getattr(websocket.app.state, "agent_os_id", None),
            )
            identity = validator.extract_claims(validator.validate_token(token, audience))
        except Exception as exc:
            raise _VoiceAccessError("Invalid or expired token") from exc
        if is_reserved_principal(identity.get("user_id")):
            raise _VoiceAccessError("Invalid token subject")
    elif settings.os_security_key:
        if not hmac.compare_digest(token, settings.os_security_key):
            raise _VoiceAccessError("Invalid token")
    else:
        # Supplied credentials must never turn into anonymous access on failure.
        raise _VoiceAccessError("Authentication is not configured for this token")

    if "scopes" in identity:
        required_scopes = get_required_scopes_for_route(get_default_scope_mappings(), "POST", "/agents/_/runs")
        if not has_required_scopes(
            identity.get("scopes", []),
            required_scopes,
            resource_type="agents",
            resource_id=pipe.agent.id,
            admin_scope=config.get("admin_scope") or AgentOSScope.ADMIN.value,
        ):
            raise _VoiceAccessError("Insufficient permissions to run this agent")
        if config.get("user_isolation") and not identity.get("user_id"):
            raise _VoiceAccessError("Authenticated request is missing a user identity")

    user_id = identity.get("user_id")
    await websocket.send_json({"event": "authenticated", "user_id": user_id})
    return user_id


def get_voice_router(os: "AgentOS", settings: AgnoAPISettings) -> APIRouter:
    """Expose each live socket at its canonical WebSocket route, /voice/{id}/pipe."""
    router = APIRouter(tags=["Voice"])
    pipes = {pipe.id: pipe for pipe in os.live_sockets}

    # A pre-existing base-app route must never shadow the authenticated socket.
    if os.base_app is not None:
        for pipe_id in pipes:
            path = f"/voice/{pipe_id}/pipe"
            scope = {"type": "websocket", "path": path, "root_path": "", "app": os.base_app}
            if any(route.matches(scope)[0] == Match.FULL for route in os.base_app.routes):
                raise ValueError(f"Voice route conflicts with an existing base-app route: {path}")

    @router.websocket("/voice/{pipe_id}/pipe", name="voice_pipe")
    async def voice_socket(websocket: WebSocket, pipe_id: str):
        if not _origin_allowed(websocket, os.cors_allowed_origins):
            await websocket.close(code=1008)
            return
        pipe = pipes.get(pipe_id)
        if pipe is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            user_id = await _authenticate(websocket, pipe, settings)
            # Each connection owns a fresh session. Client-controlled IDs must not
            # reopen someone else's agent history or change run attribution.
            await pipe._serve(websocket, user_id=user_id, session_id=str(uuid4()))
        except _VoiceAccessError as exc:
            await websocket.send_json({"event": "auth_error", "error": str(exc)})
            await websocket.close(code=1008)
        except WebSocketDisconnect:
            pass
        except Exception:
            log_error("Voice connection failed", exc_info=True)
            try:
                await websocket.send_json({"event": "error", "error": "Voice connection failed"})
                await websocket.close(code=1011)
            except (RuntimeError, WebSocketDisconnect):
                pass

    return router
