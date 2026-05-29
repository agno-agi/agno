from html import escape
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from agno.tools.google.auth.tokens import persist_google_token, valid_auth_token_db
from agno.utils.log import log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.tools.google.auth.manager import GoogleAuthManager

# -----------------------------------------------------------------------------
# HTML Response Helpers
# -----------------------------------------------------------------------------


def _error_page(message: str) -> HTMLResponse:
    # escape() prevents XSS — message may come from Google's error param
    return HTMLResponse(f"<h1>Error</h1><p>{escape(message)}</p>", status_code=400)


def _success_page(services: List[str], valid_services: Dict[str, List[str]]) -> HTMLResponse:
    # Filter services against registry to avoid displaying attacker-controlled strings
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
    # Decode JWT state parameter and verify signature + expiry
    # State contains: user_id, services (requested), state_id (PKCE correlation)
    import jwt

    from agno.utils.oauth_state import verify_state

    try:
        state_data = verify_state(state, secret=secret)
    except jwt.InvalidTokenError as e:
        log_warning(f"Rejected OAuth callback: {e}")
        return None, "Invalid state"

    # state_id links this callback to the PKCE verifier stored in DB
    if not state_data.get("state_id"):
        return None, "Invalid state"

    return state_data, None


def _verify_pkce(
    db: "BaseDb",
    user_id: Optional[str],
    state_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    # Retrieve PKCE code_verifier from DB and validate it matches the state_id
    # PKCE (Proof Key for Code Exchange) prevents authorization code interception attacks
    try:
        row = db.get_auth_token("google", user_id, "google")
    except Exception as e:
        log_error(f"Failed to retrieve PKCE state: {e}")
        return None, "Failed to verify OAuth state"

    # state_id must match — prevents attacker from using a different user's PKCE session
    if not row or row.get("pkce_state_id") != state_id:
        return None, "OAuth session expired. Please try again."

    code_verifier = row.get("pkce_verifier")
    if not code_verifier:
        return None, "OAuth session corrupted"

    # No separate TTL check needed — JWT expiry (verified above) already gates this
    return code_verifier, None


def _build_scopes(
    auth_config: "GoogleAuthManager",
    services: List[str],
) -> Tuple[List[str], Optional[str]]:
    # Resolve OAuth scopes from the service registry
    # include_granted_scopes=True → request ALL registered scopes (incremental auth)
    # include_granted_scopes=False → request only scopes for the requested services
    if auth_config._include_granted_scopes:
        scopes = [s for svc_scopes in auth_config._services.values() for s in svc_scopes]
    else:
        scopes = [s for svc in services for s in auth_config._services.get(svc, [])]

    if not scopes:
        log_error(f"No scopes for services={services}")
        return [], "No scopes configured"

    return scopes, None


# -----------------------------------------------------------------------------
# Token Exchange
# -----------------------------------------------------------------------------


def _exchange_code(
    auth_config: "GoogleAuthManager",
    code: str,
    code_verifier: str,
    scopes: List[str],
) -> Tuple[Any, Optional[str]]:
    # Exchange authorization code for access/refresh tokens via Google's token endpoint
    # code_verifier completes the PKCE challenge (proves we initiated the flow)
    from google_auth_oauthlib.flow import Flow

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
        # include_granted_scopes: clear scope so Google returns ALL previously granted scopes
        if auth_config._include_granted_scopes:
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
    auth_config: "GoogleAuthManager",
    db: Optional["BaseDb"] = None,
) -> APIRouter:
    # Validate required config — fail fast at startup, not at callback time
    if not auth_config._state_secret:
        raise RuntimeError("GOOGLE_OAUTH_STATE_SECRET required for OAuth callback")

    # Prefer explicit db param, fallback to manager's db — must be sync (not async)
    resolved_db = valid_auth_token_db(db) or valid_auth_token_db(auth_config._db)
    if not resolved_db:
        raise RuntimeError("create_oauth_router() requires a DB with auth token support")

    router = APIRouter(tags=["Google OAuth"])
    path = auth_config._callback_path or "/google/oauth/callback"

    @router.get(path)
    async def oauth_callback(request: Request) -> HTMLResponse:
        # Google redirects here after user grants/denies consent
        # Query params: code (auth code), state (JWT), error (if denied)
        # --- Handle denial/error from Google ---
        if error := request.query_params.get("error"):
            return _error_page(error)

        code = request.query_params.get("code")
        if not code:
            return _error_page("Missing authorization code")

        # --- Validate JWT state (CSRF protection) ---
        state = request.query_params.get("state", "")
        state_data, err = _verify_jwt_state(state, auth_config._state_secret)
        if err:
            return _error_page(err)

        # Extract claims — user_id ties token to specific user, state_id links to PKCE
        user_id = state_data.get("user_id")
        services = state_data.get("services", [])
        state_id = state_data.get("state_id")

        # --- Verify PKCE (code interception protection) ---
        code_verifier, err = _verify_pkce(resolved_db, user_id, state_id)
        if err:
            return _error_page(err)

        # --- Build scope list from service registry ---
        scopes, err = _build_scopes(auth_config, services)
        if err:
            return _error_page(err)

        # --- Exchange code for tokens ---
        creds, err = _exchange_code(auth_config, code, code_verifier, scopes)
        if err:
            return _error_page(err)

        # --- Persist tokens to DB (clears PKCE state) ---
        if not persist_google_token(
            db=resolved_db,
            creds=creds,
            user_id=user_id,
            services_registry=auth_config._services,
            auth_config=auth_config,
        ):
            log_error(f"Token persistence failed for user={user_id}")
            return _error_page("Failed to save token")

        log_info(f"OAuth complete for user={user_id}, services={services}")
        return _success_page(services, auth_config._services)

    return router
