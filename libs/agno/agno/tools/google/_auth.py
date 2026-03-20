import json
from functools import wraps

from agno.utils.log import log_error


def google_authenticate(service_name: str):
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
