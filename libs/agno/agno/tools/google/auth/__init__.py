import json
import os
from functools import wraps
from typing import Any, Dict, List, Literal, Optional, Set
from urllib.parse import urlencode

from agno.tools import Toolkit
from agno.tools.google.auth.credentials import AuthConfig
from agno.utils.log import log_error

__all__ = [
    "AuthConfig",
    "GoogleAuth",
    "google_authenticate",
]


def google_authenticate(service_name: str):
    """Shared auth decorator for all Google toolkits.

    Each toolkit creates a module-level alias:
        authenticate = google_authenticate("gmail")

    Expects the toolkit class to define:
        - self.creds: Google OAuth credentials
        - self._service: Built API client (set by _build_service)
        - self._resolve_creds(): Loads or refreshes credentials
        - self._build_service(creds): Returns build(api_name, api_version, credentials=creds)
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if not self.creds or not self.creds.valid:
                try:
                    self.creds = self._resolve_creds()
                except Exception as e:
                    log_error(f"{service_name.title()} authentication failed: {e}")
                    return json.dumps({"error": f"{service_name.title()} authentication failed: {e}"})
            if not self._service:
                try:
                    self._service = self._build_service(self.creds)
                except Exception as e:
                    log_error(f"{service_name.title()} service initialization failed: {e}")
                    return json.dumps({"error": f"{service_name.title()} service initialization failed: {e}"})
            return func(self, *args, **kwargs)

        return wrapper

    return decorator


class GoogleAuth(Toolkit):
    """Toolkit that exposes authenticate_google tool for web/chat UI OAuth flows.

    Use this when run_local_server() won't work (e.g., chatbot interfaces).
    The agent calls authenticate_google() to get an OAuth URL for the user.
    """

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
        """Register a Google service and its scopes for URL generation."""
        self._services[service] = scopes

    def authenticate_google(self, services: List[Literal["gmail", "calendar", "drive", "sheets", "slides"]]) -> str:
        """Get the Google OAuth URL for the user to authenticate their Google account.

        Args:
            services: Google services to authenticate (gmail, calendar, drive, sheets, slides).

        Returns:
            JSON string containing the OAuth URL or error message.
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
