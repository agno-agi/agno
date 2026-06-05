from agno.tools.google.auth.credentials import GoogleAuth
from agno.tools.google.auth.security import sign_state, verify_state

__all__ = [
    "GoogleAuth",
    "google_authenticate",
    "sign_state",
    "verify_state",
]


def google_authenticate(service_name: str):
    """Decorator that ensures credentials and service are ready before method execution.

    Each toolkit creates a module-level alias:
        authenticate = google_authenticate("gmail")

    The decorator:
    1. Resolves credentials via _resolve_creds() if not already valid
    2. Builds the service client via _build_service() if not already built
    3. Calls the wrapped method

    Expects the toolkit class to define:
        - self.creds: Google OAuth credentials (or None)
        - self._service: Built API client (or None)
        - self._resolve_creds(): Returns valid credentials
        - self._build_service(creds): Returns API service client
    """
    import json
    from functools import wraps

    from agno.utils.log import log_error

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
