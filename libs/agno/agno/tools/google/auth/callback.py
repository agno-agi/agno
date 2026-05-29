from html import escape
from typing import TYPE_CHECKING, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from agno.tools.google.auth.security import build_scopes, exchange_code, verify_jwt_state, verify_pkce
from agno.utils.log import log_error, log_info

if TYPE_CHECKING:
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


def create_oauth_router(config: "GoogleAuthConfig") -> APIRouter:
    if not config.manager:
        raise RuntimeError("create_oauth_router() requires GoogleAuthConfig with manager= set")

    manager = config.manager
    if not manager._state_secret:
        raise RuntimeError("GOOGLE_OAUTH_STATE_SECRET required for OAuth callback")
    if not manager._db:
        raise RuntimeError("GoogleAuthManager requires db= for OAuth callback")

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
        oauth_state, err = verify_jwt_state(state, manager._state_secret)
        if err or oauth_state is None:
            return _error_page(err or "Invalid state")

        # Extract claims from JWT signed during OAuth URL generation
        user_id = oauth_state.get("user_id")
        services = oauth_state.get("services", [])
        pkce_session_id = oauth_state.get("state_id")

        # 2. Verify PKCE — prevents intercepted auth codes from being exchanged
        if not pkce_session_id:
            return _error_page("Invalid state: missing state_id")
        # Retrieve secret stored during OAuth URL generation
        code_verifier, err = verify_pkce(manager._db, user_id, pkce_session_id)
        if err or not code_verifier:
            return _error_page(err or "PKCE verification failed")

        # 3. Build scopes for token request
        scopes, err = build_scopes(config, services)
        if err:
            return _error_page(err)

        # 4. Exchange auth code + PKCE verifier for access/refresh tokens
        creds, err = exchange_code(config, code, code_verifier, scopes)
        if err:
            return _error_page(err)

        # 5. Persist tokens to DB
        if not manager.persist_token(creds=creds, user_id=user_id):
            log_error(f"Token persistence failed for user={user_id}")
            return _error_page("Failed to save token")

        log_info(f"OAuth complete for user={user_id}, services={services}")
        return _success_page(services, manager._services)

    return router
