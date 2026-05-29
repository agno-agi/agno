from html import escape
from typing import TYPE_CHECKING, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from agno.tools.google.auth.security import build_scopes, exchange_code, verify_jwt_state, verify_pkce
from agno.utils.log import log_error, log_info

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.tools.google.auth.config import GoogleAuthConfig


def _error_page(message: str) -> HTMLResponse:
    return HTMLResponse(f"<h1>Error</h1><p>{escape(message)}</p>", status_code=400)


def _success_page(services: List[str], valid_services: Dict[str, List[str]]) -> HTMLResponse:
    safe_services = ", ".join(s for s in services if s in valid_services) or "services"
    return HTMLResponse(
        f"<h1>Connected</h1>"
        f"<p>Google {escape(safe_services)} connected successfully.</p>"
        f"<p>You can close this window.</p>"
    )


def create_oauth_router(
    config: "GoogleAuthConfig",
    db: Optional["BaseDb"] = None,
) -> APIRouter:
    """Create FastAPI router for OAuth callback endpoint.

    The callback flow:
    1. Verify JWT state signature (prevents CSRF)
    2. Verify PKCE state_id matches DB (prevents replay)
    3. Exchange authorization code for tokens
    4. Persist tokens to database

    Args:
        config: GoogleAuthConfig with OAuth credentials
        db: Optional database override (defaults to manager._db)

    Returns:
        FastAPI APIRouter with the callback endpoint
    """
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
        # Check for OAuth error from Google
        if error := request.query_params.get("error"):
            return _error_page(error)

        # Extract authorization code
        code = request.query_params.get("code")
        if not code:
            return _error_page("Missing authorization code")

        # 1. Verify JWT state
        state = request.query_params.get("state", "")
        if not manager._state_secret:
            return _error_page("State secret not configured")
        state_data, err = verify_jwt_state(state, manager._state_secret)
        if err or state_data is None:
            return _error_page(err or "Invalid state")

        user_id = state_data.get("user_id")
        services = state_data.get("services", [])
        state_id = state_data.get("state_id")

        # 2. Verify PKCE
        if not state_id:
            return _error_page("Invalid state: missing state_id")
        code_verifier, err = verify_pkce(resolved_db, user_id, state_id)
        if err or not code_verifier:
            return _error_page(err or "PKCE verification failed")

        # 3. Build scopes and exchange code for tokens
        scopes, err = build_scopes(config, services)
        if err:
            return _error_page(err)

        creds, err = exchange_code(config, code, code_verifier, scopes)
        if err:
            return _error_page(err)

        # 4. Persist tokens
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
