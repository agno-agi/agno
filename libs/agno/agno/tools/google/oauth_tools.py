"""
GoogleOAuthTools — LLM-callable toolkit for initiating Google OAuth flows.

This toolkit exposes `oauth_google` which returns an OAuth URL for the user to
authenticate their Google account. It's explicitly added to an agent's tools
when you want the LLM to be able to trigger OAuth (e.g., error-recovery when
Gmail/Calendar tools fail with "authentication required").

Usage:
    from agno.tools.google.oauth import GoogleOAuth
    from agno.tools.google.oauth_tools import GoogleOAuthTools

    google_oauth = GoogleOAuth(hosted_domain="acme.com")

    agent = Agent(
        db=db,
        tools=[
            GoogleOAuthTools(google_auth=google_auth),  # Explicit opt-in
            GmailTools(google_auth=google_auth),
            GoogleCalendarTools(google_auth=google_auth),
        ],
    )
"""

import json
import secrets
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class GoogleOAuthTools(Toolkit):
    """Toolkit exposing oauth_google for LLM-triggered authentication flows.

    Add this toolkit explicitly when you want the LLM to be able to generate
    OAuth URLs for users. Typically used in chat interfaces (Slack, WhatsApp)
    where the LLM needs to recover from authentication errors.

    Attributes:
        google_oauth: The GoogleOAuth coordinator that holds OAuth config
            (client_id, hosted_domain, etc.) and manages scope consolidation.
    """

    def __init__(
        self,
        google_auth: Any,
        name: str = "google_oauth_tools",
        **kwargs: Any,
    ):
        super().__init__(
            name=name,
            instructions=(
                "When any Google tool (Gmail, Calendar, Drive, Sheets) returns an "
                "authentication error, call oauth_google to get the OAuth URL for the user."
            ),
            **kwargs,
        )
        self.google_auth = google_auth
        self.register(self.oauth_google)

    def oauth_google(
        self,
        run_context: Optional[Any] = None,
        agent: Optional[Any] = None,
    ) -> str:
        """
        Get the Google OAuth URL for the user to authenticate their Google account.

        Automatically requests scopes for ALL registered Google toolkits (Gmail, Calendar,
        Drive, etc.) so the user only needs to authenticate once.

        Returns:
            str: JSON string containing the OAuth URL or error message.
        """
        ga = self.google_auth
        if ga is None:
            return json.dumps({"error": "GoogleOAuth coordinator not configured."})

        if not ga._services:
            return json.dumps(
                {"error": "No Google services registered. Add GmailTools, GoogleCalendarTools, etc. to your agent."}
            )

        services = list(ga._services.keys())
        scopes: Set[str] = set()
        for service_scopes in ga._services.values():
            scopes.update(service_scopes)

        if not ga._state_secret:
            return json.dumps(
                {
                    "error": "GoogleOAuth requires a state signing secret. Set state_secret= on "
                    "construction or the GOOGLE_OAUTH_STATE_SECRET environment variable."
                }
            )

        # Resolve DB for PKCE state storage
        from agno.tools.google.auth import _valid_auth_token_db as _valid_oauth_db

        db = _valid_oauth_db(ga._db) or _valid_oauth_db(getattr(agent, "db", None) if agent else None)
        if db is None:
            return json.dumps(
                {
                    "error": "GoogleOAuth requires a database for PKCE state storage. "
                    "Pass db= to GoogleOAuth or ensure agent.db is configured."
                }
            )

        # PKCE: generate code_verifier and code_challenge
        from agno.tools.google.auth import _generate_pkce_pair

        code_verifier, code_challenge = _generate_pkce_pair()
        state_id = secrets.token_urlsafe(16)

        # Signed JWT carries user_id + state_id through Google redirect
        user_id = getattr(run_context, "user_id", None) if run_context else None
        try:
            from agno.utils.oauth_state import sign_state

            state = sign_state(
                {"user_id": user_id, "services": list(services), "state_id": state_id},
                secret=ga._state_secret,
                ttl_seconds=ga._state_ttl_seconds,
            )
        except ImportError:
            return json.dumps(
                {
                    "error": "PyJWT is required for OAuth state signing. "
                    "Install with `pip install PyJWT` or `pip install agno[os]`."
                }
            )

        # Store PKCE state in DB
        try:
            db.upsert_auth_token(
                {
                    "provider": "google",
                    "user_id": user_id,
                    "service": "google",
                    "token_data": {
                        "pkce_verifier": code_verifier,
                        "pkce_state_id": state_id,
                        "pending": True,
                    },
                    "granted_scopes": list(scopes),
                }
            )
        except Exception as e:
            log_error(f"Failed to store PKCE state: {e}")
            return json.dumps({"error": f"Failed to initialize OAuth flow: {e}"})

        params: Dict[str, str] = {
            "client_id": ga.client_id,
            "redirect_uri": ga.redirect_uri,
            "scope": " ".join(scopes),
            "response_type": "code",
            "access_type": ga._access_type,
            "prompt": ga._prompt,
            "include_granted_scopes": "true" if ga._include_granted_scopes else "false",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        # Enterprise: restrict to specific Google Workspace domain
        if ga._hosted_domain:
            params["hd"] = ga._hosted_domain
        # Pre-fill email hint if configured
        if ga._login_hint:
            params["login_hint"] = ga._login_hint

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
