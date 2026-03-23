import json
import os
from typing import Any, Dict, List, Literal, Optional, Set
from urllib.parse import urlencode

from agno.tools import Toolkit


class GoogleAuth(Toolkit):
    def __init__(
        self,
        client_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(
            name="google_auth",
            instructions="When any Google tool (Gmail, Calendar, Drive, Sheets) returns an authentication error, immediately call authenticate_google to get the OAuth URL for the user.",
            **kwargs,
        )
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.redirect_uri = redirect_uri or os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8080/")
        self._services: Dict[str, List[str]] = {}
        self.register(self.authenticate_google)

    def register_service(self, service: str, scopes: List[str]) -> None:
        self._services[service] = scopes

    def authenticate_google(self, services: List[Literal["gmail", "calendar", "drive", "sheets"]]) -> str:
        """Get the Google OAuth URL for the user to authenticate their Google account.
        Call this immediately when any Google tool returns an authentication error.
        Send the returned URL to the user — they must visit it to grant access.

        Args:
            services: Which Google services failed authentication (e.g. ["gmail"], ["calendar"], ["gmail", "calendar"]).
        """
        scopes: Set[str] = set()
        for service in services:
            if service in self._services:
                scopes.update(self._services[service])
        if not scopes:
            return json.dumps({"error": f"Unknown services. Available: {', '.join(self._services)}"})
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        return json.dumps({"message": f"Connect {', '.join(services)}", "url": url})
