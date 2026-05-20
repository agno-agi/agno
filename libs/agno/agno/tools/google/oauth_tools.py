"""
GoogleOAuthTools — LLM-callable toolkit for initiating Google OAuth flows.

This toolkit exposes `oauth_google` which returns an OAuth URL for the user to
authenticate their Google account. It's explicitly added to an agent's tools
when you want the LLM to be able to trigger OAuth (e.g., error-recovery when
Gmail/Calendar tools fail with "authentication required").

Usage (env defaults — zero config):
    agent = Agent(
        db=db,
        tools=[
            GoogleOAuthTools(),   # Explicit opt-in to user OAuth
            GmailTools(),         # Auto-wired
            GoogleCalendarTools(),
        ],
    )

Usage (custom config):
    auth_config = GoogleAuthConfig(hosted_domain="acme.com")
    agent = Agent(
        db=db,
        tools=[
            GoogleOAuthTools(auth_config=auth_config),
            GmailTools(),  # Auto-wired from GoogleOAuthTools
        ],
    )
"""

import json
import secrets
from typing import TYPE_CHECKING, Any, Dict, Optional, Set
from urllib.parse import urlencode

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

if TYPE_CHECKING:
    from agno.tools.google.auth import GoogleAuthConfig


class GoogleOAuthTools(Toolkit):
    """Toolkit exposing oauth_google for LLM-triggered authentication flows.

    Add this toolkit explicitly when you want the LLM to be able to generate
    OAuth URLs for users. Typically used in chat interfaces (Slack, WhatsApp)
    where the LLM needs to recover from authentication errors.

    When no auth_config is provided, the framework auto-wires a shared
    GoogleAuthConfig from env vars (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, etc.)
    across all Google toolkits.

    Attributes:
        auth_config: The GoogleAuthConfig coordinator that holds OAuth config
            (client_id, hosted_domain, etc.) and manages scope consolidation.
    """

    def __init__(
        self,
        auth_config: Optional["GoogleAuthConfig"] = None,
        store_token_in_db: bool = False,
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
        # May be None — wired later by framework in _wire_google_auth()
        self.auth_config = auth_config
        # Propagated to all Google toolkits via _wire_google_auth
        self.store_token_in_db = store_token_in_db
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
        ga = self.auth_config
        if ga is None:
            return json.dumps({"error": "GoogleAuthConfig coordinator not configured."})

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
                    "error": "GOOGLE_OAUTH_STATE_SECRET is required for secure OAuth. "
                    "Set it via environment variable or GoogleAuthConfig(state_secret=...)."
                }
            )

        # Resolve DB for PKCE state storage
        from agno.tools.google.auth import _valid_auth_token_db as _valid_oauth_db

        # Priority: agent.db first (matches get_token_db), then auth_config._db
        db = _valid_oauth_db(getattr(agent, "db", None) if agent else None) or _valid_oauth_db(ga._db)
        if db is None:
            return json.dumps(
                {
                    "error": "GoogleAuthConfig requires a database for PKCE state storage. "
                    "Pass db= to GoogleAuthConfig or ensure agent.db is configured."
                }
            )

        # PKCE: generate code_verifier and code_challenge
        from agno.tools.google.auth import generate_pkce_pair

        code_verifier, code_challenge = generate_pkce_pair()
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

        # Store PKCE state in DB (preserves existing token_data if present)
        try:
            import time

            expires_at = int(time.time()) + ga._state_ttl_seconds
            if not db.set_pkce_state(
                provider="google",
                user_id=user_id,
                service="google",
                verifier=code_verifier,
                state_id=state_id,
                expires_at=expires_at,
                scopes=list(scopes),
            ):
                return json.dumps({"error": "Failed to store PKCE state"})
        except Exception as e:
            log_error(f"Failed to store PKCE state: {e}")
            return json.dumps({"error": f"Failed to initialize OAuth flow: {e}"})

        if not ga.client_id or not ga.redirect_uri:
            return json.dumps(
                {"error": "GoogleAuthConfig requires client_id and redirect_uri. Set via constructor or env vars."}
            )

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
