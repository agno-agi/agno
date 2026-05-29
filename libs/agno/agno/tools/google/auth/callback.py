from html import escape
from typing import TYPE_CHECKING, Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from agno.tools.google.auth.tokens import persist_google_token, valid_auth_token_db
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.oauth_state import verify_state

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.tools.google.auth.manager import GoogleAuthManager


def handle_oauth_callback(
    manager: "GoogleAuthManager",
    code: str,
    state: str,
    db: "BaseDb",
) -> Dict[str, Any]:
    """Exchange OAuth authorization code for credentials and persist to DB."""
    try:
        import jwt
    except ImportError:
        return {
            "error": "PyJWT is required for OAuth state verification. "
            "Install with `pip install PyJWT` or `pip install agno[os]`."
        }

    if not manager._state_secret:
        return {
            "error": "GOOGLE_OAUTH_STATE_SECRET not configured. "
            "OAuth callback cannot verify state without a signing secret."
        }

    # 1. Verify JWT state (CSRF protection)
    try:
        state_data = verify_state(state, secret=manager._state_secret)
    except jwt.InvalidTokenError as e:
        log_warning(f"Rejected OAuth callback: {e}")
        return {"error": f"Invalid state: {e}"}

    user_id = state_data.get("user_id")
    services = state_data.get("services", [])
    state_id = state_data.get("state_id")

    if not state_id:
        log_warning("OAuth callback missing state_id — possible replay of pre-PKCE token")
        return {"error": "Invalid state: missing state_id"}

    # 2. Retrieve PKCE state from DB (stored at oauth_google call time)
    try:
        row = db.get_auth_token("google", user_id, "google")
    except Exception as e:
        log_error(f"Failed to retrieve PKCE state: {e}")
        return {"error": "Failed to verify OAuth state"}

    if not row:
        log_warning(f"No PKCE state found for user={user_id}")
        return {"error": "OAuth session expired or invalid. Please try again."}

    stored_state_id = row.get("pkce_state_id")
    code_verifier = row.get("pkce_verifier")
    pkce_expires_at = row.get("pkce_expires_at")

    # 3. Validate PKCE: state_id must match, verifier must exist, not expired
    if not stored_state_id or stored_state_id != state_id:
        log_warning(f"PKCE state_id mismatch for user={user_id}: expected {stored_state_id}, got {state_id}")
        return {"error": "OAuth session expired or invalid. Please try again."}

    if not code_verifier:
        log_warning(f"Missing code_verifier for user={user_id}")
        return {"error": "OAuth session corrupted. Please try again."}

    import time

    if pkce_expires_at and int(time.time()) > pkce_expires_at:
        log_warning(f"PKCE state expired for user={user_id}")
        return {"error": "OAuth session expired. Please try again."}

    # 4. Exchange authorization code for tokens
    try:
        from google_auth_oauthlib.flow import Flow

        # Build scope list from registry
        if manager._include_granted_scopes:
            scopes: list = []
            for svc_scopes in manager._services.values():
                scopes.extend(svc_scopes)
        else:
            scopes = []
            for svc in services:
                scopes.extend(manager._services.get(svc, []))

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": manager.client_id,
                    "client_secret": manager.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [manager.redirect_uri],
                }
            },
            scopes=scopes,
            redirect_uri=manager.redirect_uri,
        )

        # Prevent Google from auto-constraining scopes
        if manager._include_granted_scopes:
            flow.oauth2session.scope = None

        # PKCE: code_verifier proves we're the same client that started the flow
        flow.fetch_token(code=code, code_verifier=code_verifier)
        creds = flow.credentials

    except Exception as e:
        log_error(f"OAuth token exchange failed: {e}")
        return {"error": f"Token exchange failed: {e}"}

    # 5. Persist tokens to DB (replaces PKCE row with actual credentials)
    stored = persist_google_token(
        db=db,
        creds=creds,
        user_id=user_id,
        services_registry=manager._services,
        auth_config=manager,
    )
    if not stored:
        log_error(f"Token obtained but DB persistence failed for user={user_id}")
        return {"error": "Token obtained but could not be saved to database"}

    log_info(f"OAuth complete for user={user_id}, services={services}")
    return {"status": "ok", "user_id": user_id, "services": services}


def create_oauth_router(
    manager: "GoogleAuthManager",
    db: Optional["BaseDb"] = None,
) -> APIRouter:
    """Create FastAPI router with /google/oauth/callback endpoint."""
    # Validate config early — fail at startup, not at callback time
    if not manager._state_secret:
        raise RuntimeError(
            "GOOGLE_OAUTH_STATE_SECRET is required for OAuth callback security. "
            "Set it via environment variable or GoogleAuthManager(state_secret=...)."
        )

    resolved_db = valid_auth_token_db(db) or valid_auth_token_db(manager._db)
    if resolved_db is None:
        raise RuntimeError(
            "create_oauth_router() requires a DB with auth token support. "
            "Pass db= or set GoogleAuthManager(db=...)."
        )

    # Mark as server mode — toolkits will block browser OAuth fallback
    manager._callback_configured = True

    router = APIRouter(tags=["Google OAuth"])

    # Capture in closure — available when callback is hit later
    callback_path: str = manager._callback_path or "/google/oauth/callback"
    callback_db = resolved_db
    google_auth = manager

    @router.get(callback_path)
    async def oauth_callback(request: Request) -> HTMLResponse:
        """Handle Google OAuth redirect with authorization code."""
        # Google redirects here with ?code=...&state=... or ?error=...
        error = request.query_params.get("error")
        if error:
            desc = escape(request.query_params.get("error_description", error))
            return HTMLResponse(f"<h1>Error</h1><p>{desc}</p>", status_code=400)

        code = request.query_params.get("code")
        state = request.query_params.get("state", "")
        if not code:
            return HTMLResponse("<h1>Error</h1><p>Missing authorization code.</p>", status_code=400)

        result = handle_oauth_callback(google_auth, code, state, db=callback_db)
        if "error" in result:
            safe_error = escape(str(result["error"]))
            return HTMLResponse(f"<h1>Error</h1><p>{safe_error}</p>", status_code=400)

        # Whitelist services for XSS safety
        known = set(google_auth._services)
        safe_services = [s for s in result.get("services", []) if s in known]
        services_str = escape(", ".join(safe_services)) if safe_services else "services"
        return HTMLResponse(
            f"<h1>Connected</h1>"
            f"<p>Google {services_str} connected successfully.</p>"
            f"<p>You can close this window and return to the chat.</p>"
        )

    return router
