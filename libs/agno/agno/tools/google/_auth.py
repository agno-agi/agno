import json
from functools import wraps

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
            try:
                if not self.creds or not self.creds.valid:
                    self._auth()
                if not self.service:
                    self.service = self._build_service()
            except Exception as e:
                log_error(f"{service_name.title()} authentication failed: {e}")
                # When google_auth or oauth_redirect_url is set, direct agent to connect_google tool
                if getattr(self, "google_auth", None) or getattr(self, "oauth_redirect_url", None):
                    return json.dumps(
                        {
                            "error": f"{service_name.title()} authentication failed. "
                            "User has not connected their Google account. "
                            f"Use the connect_google tool with services=['{service_name}'] "
                            "to get the authentication URL."
                        }
                    )
                return json.dumps({"error": f"{service_name.title()} authentication failed: {e}"})
            return func(self, *args, **kwargs)

        return wrapper

    return decorator
