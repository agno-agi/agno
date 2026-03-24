import json
import os
from functools import wraps
from typing import Any, Dict, List, Literal, Optional, Set
from urllib.parse import urlencode

from agno.tools import Toolkit
from agno.utils.log import log_error


def google_authenticate(service_name: str):
    """Shared auth decorator for all Google toolkits.

    Each toolkit creates a module-level alias:
        authenticate = google_authenticate("gmail")

    Expects the toolkit class to define:
        - self.creds: Google OAuth credentials
        - self.service: Built API client (set by _build_service)
        - self._auth(): Loads or refreshes credentials
        - self._build_service(): Returns build(api_name, api_version, credentials=self.creds)
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if not self.creds or not self.creds.valid:
                try:
                    self._auth()
                except Exception as e:
                    log_error(f"{service_name.title()} authentication failed: {e}")
                    return json.dumps({"error": f"{service_name.title()} authentication failed: {e}"})
            if not self.service:
                try:
                    self.service = self._build_service()
                except Exception as e:
                    log_error(f"{service_name.title()} service initialization failed: {e}")
                    return json.dumps({"error": f"{service_name.title()} service initialization failed: {e}"})
            return func(self, *args, **kwargs)

        return wrapper

    return decorator


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

    def authenticate_google(self, services: List[Literal["gmail", "calendar", "drive", "sheets", "slides"]]) -> str:
        """
        Get the Google OAuth URL for the user to authenticate their Google account.

        Args:
            services (List[str]): Google services to authenticate.

        Returns:
            str: JSON string containing the OAuth URL or error message
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
