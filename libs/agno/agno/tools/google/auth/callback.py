"""OAuth callback router for Google authentication."""

import time
from html import escape
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from agno.tools.google.auth.tokens import persist_google_token, valid_auth_token_db
from agno.utils.log import log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.tools.google.auth.auth_config import GoogleAuthManager


def create_oauth_router(
    auth_config: "GoogleAuthManager",
    db: Optional["BaseDb"] = None,
) -> APIRouter:
    """Create FastAPI router with Google OAuth callback endpoint."""
    import jwt
    from google_auth_oauthlib.flow import Flow

    from agno.utils.oauth_state import verify_state

    if not auth_config._state_secret:
        raise RuntimeError("GOOGLE_OAUTH_STATE_SECRET required for OAuth callback")

    resolved_db = valid_auth_token_db(db) or valid_auth_token_db(auth_config._db)
    if not resolved_db:
        raise RuntimeError("create_oauth_router() requires a DB with auth token support")

    router = APIRouter(tags=["Google OAuth"])
    path = auth_config._callback_path or "/google/oauth/callback"

    @router.get(path)
    async def oauth_callback(request: Request) -> HTMLResponse:
        error = request.query_params.get("error")
        if error:
            return HTMLResponse(f"<h1>Error</h1><p>{escape(error)}</p>", status_code=400)

        code = request.query_params.get("code")
        state = request.query_params.get("state", "")
        if not code:
            return HTMLResponse("<h1>Error</h1><p>Missing authorization code</p>", status_code=400)

        # Verify JWT state
        try:
            state_data = verify_state(state, secret=auth_config._state_secret)
        except jwt.InvalidTokenError as e:
            log_warning(f"Rejected OAuth callback: {e}")
            return HTMLResponse("<h1>Error</h1><p>Invalid state</p>", status_code=400)

        user_id = state_data.get("user_id")
        services = state_data.get("services", [])
        state_id = state_data.get("state_id")

        if not state_id:
            return HTMLResponse("<h1>Error</h1><p>Invalid state</p>", status_code=400)

        # Verify PKCE
        try:
            row = resolved_db.get_auth_token("google", user_id, "google")
        except Exception as e:
            log_error(f"Failed to retrieve PKCE state: {e}")
            return HTMLResponse("<h1>Error</h1><p>Failed to verify OAuth state</p>", status_code=400)

        if not row or row.get("pkce_state_id") != state_id:
            return HTMLResponse("<h1>Error</h1><p>OAuth session expired. Please try again.</p>", status_code=400)

        code_verifier = row.get("pkce_verifier")
        if not code_verifier:
            return HTMLResponse("<h1>Error</h1><p>OAuth session corrupted</p>", status_code=400)

        pkce_expires_at = row.get("pkce_expires_at")
        if pkce_expires_at is not None and int(time.time()) > pkce_expires_at:
            return HTMLResponse("<h1>Error</h1><p>OAuth session expired</p>", status_code=400)

        # Build scopes
        if auth_config._include_granted_scopes:
            scopes = [s for svc_scopes in auth_config._services.values() for s in svc_scopes]
        else:
            scopes = [s for svc in services for s in auth_config._services.get(svc, [])]

        if not scopes:
            log_error(f"No scopes for services={services}")
            return HTMLResponse("<h1>Error</h1><p>No scopes configured</p>", status_code=400)

        # Exchange code for tokens
        try:
            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": auth_config.client_id,
                        "client_secret": auth_config.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [auth_config.redirect_uri],
                    }
                },
                scopes=scopes,
                redirect_uri=auth_config.redirect_uri,
            )
            if auth_config._include_granted_scopes:
                flow.oauth2session.scope = None
            flow.fetch_token(code=code, code_verifier=code_verifier)
        except Exception as e:
            log_error(f"Token exchange failed: {e}")
            return HTMLResponse("<h1>Error</h1><p>Token exchange failed</p>", status_code=400)

        # Persist
        if not persist_google_token(
            db=resolved_db,
            creds=flow.credentials,
            user_id=user_id,
            services_registry=auth_config._services,
            auth_config=auth_config,
        ):
            log_error(f"Token persistence failed for user={user_id}")
            return HTMLResponse("<h1>Error</h1><p>Failed to save token</p>", status_code=400)

        log_info(f"OAuth complete for user={user_id}, services={services}")
        safe_services = ", ".join(s for s in services if s in auth_config._services) or "services"
        return HTMLResponse(
            f"<h1>Connected</h1>"
            f"<p>Google {escape(safe_services)} connected successfully.</p>"
            f"<p>You can close this window.</p>"
        )

    return router
