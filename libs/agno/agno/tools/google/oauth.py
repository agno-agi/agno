import json
import os
from typing import Any, Dict, List, Literal, Optional, Set
from urllib.parse import urlencode

from agno.tools import Toolkit
from agno.utils.log import log_info


class GoogleOAuth(Toolkit):
    """Shared Google OAuth for multi-toolkit agents.

    Aggregates scopes from all registered Google toolkits and provides a single
    connect_google tool that builds an OAuth URL with only the requested services.
    Supports incremental auth via include_granted_scopes=true.

    Usage:
        google = GoogleOAuth()
        agent = Agent(tools=[
            google,
            GmailTools(google_auth=google),
            GoogleCalendarTools(google_auth=google),
        ])

    For separate accounts:
        personal = GoogleOAuth(name="personal", client_id="...")
        work = GoogleOAuth(name="work", client_id="...")
        agent = Agent(tools=[
            personal, work,
            GmailTools(google_auth=personal),
            GoogleCalendarTools(google_auth=work),
        ])

    Args:
        client_id: Google OAuth client ID. Falls back to GOOGLE_CLIENT_ID env var.
        client_secret: Google OAuth client secret. Falls back to GOOGLE_CLIENT_SECRET env var.
        redirect_uri: OAuth redirect URI. Must match Google Cloud Console config exactly.
        name: Optional name for separate-account scenarios. Changes toolkit name to avoid collisions.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: str = "http://localhost:8080/",
        name: Optional[str] = None,
        **kwargs: Any,
    ):
        toolkit_name = f"google_oauth_{name}" if name else "google_oauth"
        super().__init__(name=toolkit_name, **kwargs)

        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        self.redirect_uri = redirect_uri
        # service_name -> list of OAuth scopes
        self._services: Dict[str, List[str]] = {}

        self.register(self.connect_google)

    def register_service(self, service: str, scopes: List[str]) -> None:
        """Called by each Google toolkit during init to register its scopes."""
        self._services[service] = scopes
        log_info(f"GoogleOAuth: registered {service} with {len(scopes)} scopes")

    @property
    def registered_services(self) -> List[str]:
        return list(self._services.keys())

    @property
    def all_scopes(self) -> Set[str]:
        scopes: Set[str] = set()
        for s in self._services.values():
            scopes.update(s)
        return scopes

    def connect_google(self, services: List[Literal["gmail", "calendar", "drive", "sheets"]]) -> str:
        """Get the Google OAuth URL to connect specific Google services.
        Call this when any Google tool returns an authentication error.

        Args:
            services: Google services to connect. Select the ones that returned auth errors.
        """
        scopes: Set[str] = set()
        unavailable = []
        for service in services:
            if service in self._services:
                scopes.update(self._services[service])
            else:
                unavailable.append(service)

        if unavailable:
            available = ", ".join(self._services.keys()) if self._services else "none"
            return json.dumps({"error": f"Services not available: {', '.join(unavailable)}. Available: {available}"})

        if not scopes:
            return json.dumps({"error": "No services specified"})

        url = self._build_oauth_url(list(scopes))
        return json.dumps(
            {
                "message": f"The user needs to visit this URL to connect {', '.join(services)}",
                "url": url,
            }
        )

    def _build_oauth_url(self, scopes: List[str]) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
