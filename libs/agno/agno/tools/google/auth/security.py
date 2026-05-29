from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.tools.google.auth.config import GoogleAuthConfig


def verify_jwt_state(state: str, secret: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Verify JWT-signed OAuth state parameter.

    Returns:
        (state_data, None) on success
        (None, error_message) on failure
    """
    try:
        import jwt
    except ImportError:
        raise ImportError("PyJWT required for secure state verification. Install using `pip install PyJWT`")

    from agno.utils.oauth_state import verify_state

    try:
        state_data = verify_state(state, secret=secret)
    except jwt.InvalidTokenError as e:
        log_warning(f"Rejected OAuth callback: {e}")
        return None, "Invalid state"

    if not state_data.get("state_id"):
        return None, "Invalid state"

    return state_data, None


def verify_pkce(
    db: "BaseDb",
    user_id: Optional[str],
    state_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Verify PKCE state matches and return code_verifier.

    Returns:
        (code_verifier, None) on success
        (None, error_message) on failure
    """
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


def build_scopes(
    config: "GoogleAuthConfig",
    services: List[str],
) -> Tuple[List[str], Optional[str]]:
    """Build scope list from registered services.

    Returns:
        (scopes, None) on success
        ([], error_message) on failure
    """
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


def exchange_code(
    config: "GoogleAuthConfig",
    code: str,
    code_verifier: str,
    scopes: List[str],
) -> Tuple[Any, Optional[str]]:
    """Exchange authorization code for tokens using PKCE verifier.

    Returns:
        (credentials, None) on success
        (None, error_message) on failure
    """
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
