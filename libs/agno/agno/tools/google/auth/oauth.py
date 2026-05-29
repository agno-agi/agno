import json
import secrets
from typing import TYPE_CHECKING, Any, Dict, Optional, Set
from urllib.parse import urlencode

from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.tools.google.auth.config import GoogleAuthConfig


def oauth_google(
    config: "GoogleAuthConfig",
    run_context: Optional[Any] = None,
    agent: Optional[Any] = None,
) -> str:
    """
    Get the Google OAuth URL for the user to authenticate their Google account.

    Automatically requests scopes for ALL registered Google toolkits (Gmail, Calendar,
    Drive, etc.) so the user only needs to authenticate once.

    Args:
        config: The GoogleAuthConfig with OAuth configuration
        run_context: Run context containing user_id
        agent: Agent instance for DB access

    Returns:
        str: JSON string containing the OAuth URL or error message.
    """
    from agno.utils.oauth_state import generate_pkce_pair, store_pkce_state

    if config is None:
        return json.dumps({"error": "GoogleAuthConfig not provided."})

    if not config.manager:
        return json.dumps({"error": "GoogleAuthConfig requires manager= for multi-user OAuth."})

    manager = config.manager

    if not manager._services:
        return json.dumps(
            {"error": "No Google services registered. Add GmailTools, GoogleCalendarTools, etc. to your agent."}
        )

    services = list(manager._services.keys())
    scopes: Set[str] = set()
    for service_scopes in manager._services.values():
        scopes.update(service_scopes)

    if not manager._state_secret:
        return json.dumps(
            {
                "error": "GOOGLE_OAUTH_STATE_SECRET is required for secure OAuth. "
                "Set it via environment variable or GoogleAuthManager(state_secret=...)."
            }
        )

    db = (getattr(agent, "db", None) if agent else None) or manager._db
    if db is None:
        return json.dumps(
            {
                "error": "GoogleAuthManager requires a database for PKCE state storage. "
                "Pass db= to GoogleAuthManager or ensure agent.db is configured."
            }
        )

    code_verifier, code_challenge = generate_pkce_pair()
    state_id = secrets.token_urlsafe(16)

    user_id = getattr(run_context, "user_id", None) if run_context else None
    try:
        from agno.utils.oauth_state import sign_state

        state = sign_state(
            {"user_id": user_id, "services": list(services), "state_id": state_id},
            secret=manager._state_secret,
        )
    except ImportError:
        return json.dumps(
            {
                "error": "PyJWT is required for OAuth state signing. "
                "Install with `pip install PyJWT` or `pip install agno[os]`."
            }
        )

    if not store_pkce_state(
        db=db,
        provider="google",
        user_id=user_id,
        service="google",
        code_verifier=code_verifier,
        state_id=state_id,
    ):
        return json.dumps({"error": "Failed to store PKCE state"})

    if not config.client_id or not config.redirect_uri:
        return json.dumps(
            {"error": "GoogleAuthConfig requires client_id and redirect_uri. Set via constructor or env vars."}
        )

    params: Dict[str, str] = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": " ".join(scopes),
        "response_type": "code",
        "access_type": config.access_type,
        "prompt": config.prompt,
        "include_granted_scopes": "true" if config.include_granted_scopes else "false",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if config.hosted_domain:
        params["hd"] = config.hosted_domain
    if config.login_hint:
        params["login_hint"] = config.login_hint

    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    log_debug(f"Generated PKCE OAuth URL for user={user_id}, state_id={state_id}")

    link_text = f"Connect {', '.join(services)}"
    slack_link = f"<{url}|{link_text}>"

    return json.dumps(
        {
            "oauth_url": url,
            "services": services,
            "slack_link": slack_link,
            "message": f"Please authenticate with Google to access {', '.join(services)}.",
        }
    )
