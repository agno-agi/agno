from html import escape
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from agno.utils.log import log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.tools.google.auth.manager import GoogleAuthConfig

# -----------------------------------------------------------------------------
# HTML Response Helpers
# -----------------------------------------------------------------------------


def _error_page(message: str) -> HTMLResponse:
    return HTMLResponse(f"<h1>Error</h1><p>{escape(message)}</p>", status_code=400)


def _success_page(services: List[str], valid_services: Dict[str, List[str]]) -> HTMLResponse:
    safe_services = ", ".join(s for s in services if s in valid_services) or "services"
    return HTMLResponse(
        f"<h1>Connected</h1>"
        f"<p>Google {escape(safe_services)} connected successfully.</p>"
        f"<p>You can close this window.</p>"
    )


# -----------------------------------------------------------------------------
# Validation Helpers — each returns (value, None) on success or (None, error)
# -----------------------------------------------------------------------------


def _verify_jwt_state(state: str, secret: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    import jwt

    from agno.utils.oauth_state import verify_state

    try:
        state_data = verify_state(state, secret=secret)
    except jwt.InvalidTokenError as e:
        log_warning(f"Rejected OAuth callback: {e}")
        return None, "Invalid state"

    if not state_data.get("state_id"):
        return None, "Invalid state"

    return state_data, None


def _verify_pkce(
    db: "BaseDb",
    user_id: Optional[str],
    state_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    try:
        row = db.get_auth_token("google", user_id, "google")
    except Exception as e:
        log_error(f"Failed to retrieve PKCE state: {e}")
        return None, "Failed to verify OAuth state"

    if not row or row.get("pkce_state_id") != state_id:
        return None, "OAuth session expired. Please try again."

    code_verifier = row.get("pkce_verifier")
    if not code_verifier:
        return None, "OAuth session corrupted"

    return code_verifier, None


def _build_scopes(
    config: "GoogleAuthConfig",
    services: List[str],
) -> Tuple[List[str], Optional[str]]:
    if not config.manager:
        return [], "No manager configured"

    services_registry = config.manager._services
    if config.include_granted_scopes:
        scopes = [s for svc_scopes in services_registry.values() for s in svc_scopes]
    else:
        scopes = [s for svc in services for s in services_registry.get(svc, [])]

    if not scopes:
        log_error(f"No scopes for services={services}")
        return [], "No scopes configured"

    return scopes, None


# -----------------------------------------------------------------------------
# Token Exchange
# -----------------------------------------------------------------------------


def _exchange_code(
    config: "GoogleAuthConfig",
    code: str,
    code_verifier: str,
    scopes: List[str],
) -> Tuple[Any, Optional[str]]:
    from google_auth_oauthlib.flow import Flow

    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [config.redirect_uri],
                }
            },
            scopes=scopes,
            redirect_uri=config.redirect_uri,
        )
        if config.include_granted_scopes:
            flow.oauth2session.scope = None
        flow.fetch_token(code=code, code_verifier=code_verifier)
        return flow.credentials, None
    except Exception as e:
        log_error(f"Token exchange failed: {e}")
        return None, "Token exchange failed"


# -----------------------------------------------------------------------------
# Router Factory — creates FastAPI endpoint for OAuth redirect handling
# -----------------------------------------------------------------------------


def create_oauth_router(
    config: "GoogleAuthConfig",
    db: Optional["BaseDb"] = None,
) -> APIRouter:
    if not config.manager:
        raise RuntimeError("create_oauth_router() requires GoogleAuthConfig with manager= set")

    manager = config.manager
    if not manager._state_secret:
        raise RuntimeError("GOOGLE_OAUTH_STATE_SECRET required for OAuth callback")

    resolved_db = db or manager._db
    if not resolved_db:
        raise RuntimeError("create_oauth_router() requires a DB with auth token support")

    router = APIRouter(tags=["Google OAuth"])
    path = manager._callback_path or "/google/oauth/callback"

    @router.get(path)
    async def oauth_callback(request: Request) -> HTMLResponse:
        if error := request.query_params.get("error"):
            return _error_page(error)

        code = request.query_params.get("code")
        if not code:
            return _error_page("Missing authorization code")

        state = request.query_params.get("state", "")
        if not manager._state_secret:
            return _error_page("State secret not configured")
        state_data, err = _verify_jwt_state(state, manager._state_secret)
        if err or state_data is None:
            return _error_page(err or "Invalid state")

        user_id = state_data.get("user_id")
        services = state_data.get("services", [])
        state_id = state_data.get("state_id")

        if not state_id:
            return _error_page("Invalid state: missing state_id")
        code_verifier, err = _verify_pkce(resolved_db, user_id, state_id)
        if err or not code_verifier:
            return _error_page(err or "PKCE verification failed")

        scopes, err = _build_scopes(config, services)
        if err:
            return _error_page(err)

        creds, err = _exchange_code(config, code, code_verifier, scopes)
        if err:
            return _error_page(err)

        if not manager.persist_token(
            db=resolved_db,
            creds=creds,
            user_id=user_id,
            services_registry=manager._services,
        ):
            log_error(f"Token persistence failed for user={user_id}")
            return _error_page("Failed to save token")

        log_info(f"OAuth complete for user={user_id}, services={services}")
        return _success_page(services, manager._services)

    return router
