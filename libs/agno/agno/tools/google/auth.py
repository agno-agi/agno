import json
import os
from functools import wraps
from typing import Any, Dict, List, Literal, Optional, Set, Union
from urllib.parse import urlencode

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


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


def google_auth_from_store(
    toolkit: Any,
    service_name: str,
    scopes: list,
) -> bool:
    """Try loading credentials from GoogleAuth's DB store.

    Returns True if credentials are now valid on toolkit.creds.
    Handles refresh and auto-persist on refresh.
    """
    google_auth: Optional[GoogleAuth] = getattr(toolkit, "google_auth", None)
    if not google_auth or not google_auth._db:
        return False

    creds = google_auth.load_token(service_name, scopes)
    if not creds:
        return False

    toolkit.creds = creds
    return True


def google_auth_save_to_store(
    toolkit: Any,
    service_name: str,
) -> None:
    """Persist toolkit credentials to GoogleAuth's DB store after successful auth."""
    google_auth: Optional[GoogleAuth] = getattr(toolkit, "google_auth", None)
    if not google_auth or not google_auth._db or not toolkit.creds:
        return
    google_auth.store_token(service_name, toolkit.creds)


class GoogleAuth(Toolkit):
    """Central auth coordinator and token store for all Google toolkits.

    Handles:
    - OAuth URL generation for interactive auth flows (Slack, etc.)
    - Token storage/retrieval via agent's DB when available
    - Service scope registry for combined OAuth consent

    Usage (cookbook — file-based, zero config):
        gmail = GmailTools()

    Usage (interface — DB-backed via agent):
        google_auth = GoogleAuth(client_id="...")
        gmail = GmailTools(google_auth=google_auth)
        agent = Agent(db=PgDb(...), tools=[google_auth, gmail])
        # auto-wiring sets google_auth._db = agent.db
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        db: Optional[Any] = None,
        user_id: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(
            name="google_auth",
            instructions="When any Google tool (Gmail, Calendar, Drive, Sheets) returns an authentication error, immediately call authenticate_google to get the OAuth URL for the user.",
            **kwargs,
        )
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8080/")
        self.user_id: Optional[str] = user_id
        # Set by auto-wiring from agent.db, or explicitly via db= param
        self._db: Optional[Any] = db
        self._services: Dict[str, List[str]] = {}
        self.register(self.authenticate_google)

    def register_service(self, service: str, scopes: List[str]) -> None:
        self._services[service] = scopes

    def load_token(self, service: str, scopes: list) -> Any:
        """Load credentials from DB, refresh if expired, auto-persist on refresh.

        Returns valid Credentials or None.
        """
        if not self._db:
            return None

        user_id = self.user_id or ""
        try:
            row = self._db.get_oauth_token("google", user_id, service)
        except NotImplementedError:
            # Backend doesn't support oauth tokens yet
            return None
        except Exception as e:
            log_error(f"DB load failed for {service}: {e}")
            return None

        if not row:
            return None

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_info(row["token_data"], scopes)
        except (ValueError, KeyError, ImportError) as e:
            log_error(f"Invalid stored token for {service}: {e}")
            return None

        # Refresh expired token and auto-persist
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self.store_token(service, creds)
            except Exception as e:
                log_error(f"Token refresh failed for {service}: {e}")
                return None

        return creds if creds.valid else None

    def store_token(self, service: str, creds: Any) -> None:
        """Serialize and persist credentials to DB."""
        if not self._db:
            return

        user_id = self.user_id or ""
        try:
            token_data = json.loads(creds.to_json())
            self._db.upsert_oauth_token(
                {
                    "provider": "google",
                    "user_id": user_id,
                    "service": service,
                    "token_data": token_data,
                    "granted_scopes": token_data.get("scopes", []),
                }
            )
            log_debug(f"Token stored for {user_id}/{service}")
        except NotImplementedError:
            log_debug("Backend does not support oauth token storage")
        except Exception as e:
            log_error(f"Failed to store token for {service}: {e}")

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
