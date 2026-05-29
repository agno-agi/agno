"""oauth_google tool — generates OAuth URL for multi-user authentication."""

import json
import secrets
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Set
from urllib.parse import urlencode

from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.tools.google.auth.manager import GoogleAuthManager


def oauth_google(
    auth_config: "GoogleAuthManager",
    run_context: Optional[Any] = None,
    agent: Optional[Any] = None,
) -> str:
    """
    Get the Google OAuth URL for the user to authenticate their Google account.

    Automatically requests scopes for ALL registered Google toolkits (Gmail, Calendar,
    Drive, etc.) so the user only needs to authenticate once.

    Args:
        auth_config: The GoogleAuthManager with OAuth configuration
        run_context: Run context containing user_id
        agent: Agent instance for DB access

    Returns:
        str: JSON string containing the OAuth URL or error message.
    """
    from agno.tools.google.auth import valid_auth_token_db as _valid_oauth_db
    from agno.utils.oauth_state import generate_pkce_pair, store_pkce_state

    if auth_config is None:
        return json.dumps({"error": "GoogleAuthManager not configured."})

    if not auth_config._services:
        return json.dumps(
            {"error": "No Google services registered. Add GmailTools, GoogleCalendarTools, etc. to your agent."}
        )

    services = list(auth_config._services.keys())
    scopes: Set[str] = set()
    for service_scopes in auth_config._services.values():
        scopes.update(service_scopes)

    if not auth_config._state_secret:
        return json.dumps(
            {
                "error": "GOOGLE_OAUTH_STATE_SECRET is required for secure OAuth. "
                "Set it via environment variable or GoogleAuthManager(state_secret=...)."
            }
        )

    # Resolve DB for PKCE state storage
    db = _valid_oauth_db(getattr(agent, "db", None) if agent else None) or _valid_oauth_db(auth_config._db)
    if db is None:
        return json.dumps(
            {
                "error": "GoogleAuthManager requires a database for PKCE state storage. "
                "Pass db= to GoogleAuthManager or ensure agent.db is configured."
            }
        )

    # PKCE: generate code_verifier and code_challenge
    code_verifier, code_challenge = generate_pkce_pair()
    state_id = secrets.token_urlsafe(16)

    # Signed JWT carries user_id + state_id through Google redirect
    user_id = getattr(run_context, "user_id", None) if run_context else None
    try:
        from agno.utils.oauth_state import sign_state

        state = sign_state(
            {"user_id": user_id, "services": list(services), "state_id": state_id},
            secret=auth_config._state_secret,
            ttl_seconds=auth_config._state_ttl_seconds,
        )
    except ImportError:
        return json.dumps(
            {
                "error": "PyJWT is required for OAuth state signing. "
                "Install with `pip install PyJWT` or `pip install agno[os]`."
            }
        )

    # Store PKCE state in DB
    expires_at = int(time.time()) + auth_config._state_ttl_seconds
    if not store_pkce_state(
        db=db,
        provider="google",
        user_id=user_id,
        service="google",
        code_verifier=code_verifier,
        state_id=state_id,
        expires_at=expires_at,
    ):
        return json.dumps({"error": "Failed to store PKCE state"})

    if not auth_config.client_id or not auth_config.redirect_uri:
        return json.dumps(
            {"error": "GoogleAuthManager requires client_id and redirect_uri. Set via constructor or env vars."}
        )

    params: Dict[str, str] = {
        "client_id": auth_config.client_id,
        "redirect_uri": auth_config.redirect_uri,
        "scope": " ".join(scopes),
        "response_type": "code",
        "access_type": auth_config._access_type,
        "prompt": auth_config._prompt,
        "include_granted_scopes": "true" if auth_config._include_granted_scopes else "false",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    # Enterprise: restrict to specific Google Workspace domain
    if auth_config._hosted_domain:
        params["hd"] = auth_config._hosted_domain
    # Pre-fill email hint if configured
    if auth_config._login_hint:
        params["login_hint"] = auth_config._login_hint

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
