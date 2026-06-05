from typing import Any, Dict, List, Optional, Tuple

from agno.utils.log import log_error, log_warning


def sign_state(payload: Dict[str, Any], secret: str, ttl_seconds: int = 600) -> str:
    """Sign OAuth state payload using JWT.

    Re-exports from oauth_state for convenience.
    """
    from agno.utils.oauth_state import sign_state as _sign_state

    return _sign_state(payload, secret, ttl_seconds)


def verify_state(token: str, secret: str, leeway_seconds: int = 60) -> Dict[str, Any]:
    """Verify and decode OAuth state token.

    Re-exports from oauth_state for convenience.
    """
    from agno.utils.oauth_state import verify_state as _verify_state

    return _verify_state(token, secret, leeway_seconds)


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

    try:
        state_data = verify_state(state, secret=secret)
    except jwt.InvalidTokenError as e:
        log_warning(f"Rejected OAuth callback: {e}")
        return None, "Invalid state"

    if not state_data.get("state_id"):
        return None, "Invalid state"

    return state_data, None


def exchange_code(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
    scopes: List[str],
    include_granted_scopes: bool = False,
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
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri],
                }
            },
            scopes=scopes,
            redirect_uri=redirect_uri,
        )
        if include_granted_scopes:
            flow.oauth2session.scope = None
        flow.fetch_token(code=code, code_verifier=code_verifier)
        return flow.credentials, None
    except Exception as e:
        log_error(f"Token exchange failed: {e}")
        return None, "Token exchange failed"
