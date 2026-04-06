import base64
import inspect
import json
import os
from functools import wraps
from typing import Any, Dict, List, Literal, Optional, Set
from urllib.parse import urlencode

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info


def google_authenticate(service_name: str):
    """Shared auth decorator for all Google toolkits.

    Each toolkit creates a module-level alias:
        authenticate = google_authenticate("gmail")

    Expects the toolkit class to define:
        - self.creds: Google OAuth credentials
        - self.service: Built API client (set by _build_service)
        - self._auth(user_id=None): Loads or refreshes credentials
        - self._build_service(): Returns build(api_name, api_version, credentials=self.creds)
    """

    def decorator(func):
        # Expose original typed params + run_context in the signature so the framework:
        # (1) builds the correct LLM tool schema from the original params
        # (2) injects run_context (which carries user_id) at call time
        # run_context is stripped from the LLM schema at function.py:660-671
        sig = inspect.signature(func)
        if "run_context" not in sig.parameters:
            params = list(sig.parameters.values())
            params.append(inspect.Parameter("run_context", inspect.Parameter.KEYWORD_ONLY, default=None))
            exposed_sig = sig.replace(parameters=params)
        else:
            exposed_sig = sig

        @wraps(func)
        def wrapper(self, *args, run_context=None, **kwargs):
            user_id = getattr(run_context, "user_id", None) if run_context else None

            if not self.creds or not self.creds.valid:
                try:
                    self._auth(user_id=user_id)
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

        wrapper.__signature__ = exposed_sig
        return wrapper

    return decorator


def get_token_db(toolkit: Any) -> Any:
    """Resolve the DB to use for token storage. Returns None if no DB available."""
    ga = getattr(toolkit, "google_auth", None)
    if ga and ga._db:
        return ga._db
    if getattr(toolkit, "store_token_in_db", False):
        return getattr(toolkit, "_db", None)
    return None


def load_token(toolkit: Any, scopes: list, user_id: Optional[str] = None) -> bool:
    """Try loading credentials from DB. Sets toolkit.creds if found. Returns True on success."""
    db = get_token_db(toolkit)
    if not db:
        return False

    ga = getattr(toolkit, "google_auth", None)
    uid = user_id or (ga.user_id if ga and ga.user_id else "") or ""
    try:
        row = db.get_auth_token("google", uid, "google")
    except (NotImplementedError, Exception):
        return False
    if not row:
        return False

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_info(row["token_data"], scopes)
    except (ValueError, KeyError, ImportError):
        return False

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(toolkit, creds)
        except Exception:
            return False

    if creds.valid:
        toolkit.creds = creds
        return True
    return False


def save_token(toolkit: Any, creds: Any, user_id: Optional[str] = None) -> bool:
    """Persist credentials to DB. Returns True on success."""
    db = get_token_db(toolkit)
    if not db:
        return False

    ga = getattr(toolkit, "google_auth", None)
    uid = user_id or (ga.user_id if ga and ga.user_id else "") or ""
    try:
        token_data = json.loads(creds.to_json())
        db.upsert_auth_token(
            {
                "provider": "google",
                "user_id": uid,
                "service": "google",
                "token_data": token_data,
                "granted_scopes": token_data.get("scopes", []),
            }
        )
        return True
    except (NotImplementedError, Exception):
        return False


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
        # Default user_id for single-user/cookbook mode; multi-user gets it from RunContext
        self.user_id: Optional[str] = user_id
        # Set by auto-wiring from agent.db, or explicitly via db= param
        self._db: Optional[Any] = db
        self._services: Dict[str, List[str]] = {}
        self.register(self.authenticate_google)

    def register_service(self, service: str, scopes: List[str]) -> None:
        self._services[service] = scopes

    def load_token(self, service: str, scopes: list, user_id: Optional[str] = None) -> Any:
        """Load credentials from DB, refresh if expired, auto-persist on refresh.

        Returns valid Credentials or None.
        """
        if not self._db:
            return None

        effective_user_id = user_id or self.user_id or ""
        if not effective_user_id:
            log_debug("No user_id for token lookup — all anonymous users share one token row")
        try:
            row = self._db.get_auth_token("google", effective_user_id, service)
        except NotImplementedError:
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

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self.store_token(service, creds, user_id=user_id)
            except Exception as e:
                log_error(f"Token refresh failed for {service}: {e}")
                return None

        return creds if creds.valid else None

    def store_token(self, service: str, creds: Any, user_id: Optional[str] = None) -> bool:
        """Serialize and persist credentials to DB. Returns True on success."""
        if not self._db:
            return False

        effective_user_id = user_id or self.user_id or ""
        try:
            token_data = json.loads(creds.to_json())
            self._db.upsert_auth_token(
                {
                    "provider": "google",
                    "user_id": effective_user_id,
                    "service": service,
                    "token_data": token_data,
                    "granted_scopes": token_data.get("scopes", []),
                }
            )
            log_debug(f"Token stored for {effective_user_id}/{service}")
            return True
        except NotImplementedError:
            log_debug("Backend does not support auth token storage")
            return False
        except Exception as e:
            log_error(f"Failed to store token for {service}: {e}")
            return False

    def authenticate_google(
        self,
        services: List[Literal["gmail", "calendar", "drive", "sheets", "slides"]],
        run_context: Optional[Any] = None,
    ) -> str:
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

        # Encode user_id + services in state so the callback knows who authenticated
        user_id = getattr(run_context, "user_id", None) if run_context else None
        state_data = {"services": list(services), "user_id": user_id or self.user_id or ""}
        state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        return json.dumps({"message": f"Connect {', '.join(services)}", "url": url})

    def handle_oauth_callback(self, code: str, state: str) -> Dict[str, Any]:
        """Exchange an OAuth authorization code for credentials and store in DB.

        Called by the /google/oauth/callback endpoint after Google redirects.

        Args:
            code: Authorization code from Google's redirect.
            state: Base64-encoded JSON with user_id and services.

        Returns:
            Dict with status, user_id, and services that were authorized.
        """
        try:
            state_data = json.loads(base64.urlsafe_b64decode(state))
        except Exception:
            return {"error": "Invalid state parameter"}

        user_id = state_data.get("user_id", "")
        services = state_data.get("services", [])

        try:
            from google_auth_oauthlib.flow import Flow

            # Collect ALL registered scopes as the base request
            scopes: list = []
            for svc_scopes in self._services.values():
                scopes.extend(svc_scopes)

            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [self.redirect_uri],
                    }
                },
                scopes=scopes,
                redirect_uri=self.redirect_uri,
            )

            # Disable strict scope validation — Google returns a superset of
            # scopes when include_granted_scopes=true carries over prior grants.
            # Setting scope=None tells oauthlib to skip the comparison.
            flow.oauth2session.scope = None

            flow.fetch_token(code=code)
            creds = flow.credentials

        except Exception as e:
            log_error(f"OAuth token exchange failed: {e}")
            return {"error": f"Token exchange failed: {e}"}

        # Store one consolidated token row — all Google services share it
        stored = self.store_token("google", creds, user_id=user_id)
        if not stored:
            log_error(f"Token obtained but DB persistence failed for user={user_id}")
            return {"error": "Token obtained but could not be saved to database"}

        log_info(f"OAuth complete for user={user_id}, services={services}")
        return {"status": "ok", "user_id": user_id, "services": services}

    def get_oauth_router(self) -> Any:
        """Create a FastAPI APIRouter with the /google/oauth/callback endpoint.

        The router closes over this GoogleAuth instance. _db must be wired
        (via AgentOS init-time binding or explicit db= param) before the
        callback fires, otherwise token storage silently skips.

        Usage:
            google_auth = GoogleAuth(client_id="...")
            app.include_router(google_auth.get_oauth_router())
        """
        from html import escape

        from fastapi import APIRouter, Request
        from fastapi.responses import HTMLResponse

        router = APIRouter(tags=["Google OAuth"])
        google_auth = self

        @router.get("/google/oauth/callback")
        async def oauth_callback(request: Request) -> HTMLResponse:
            # Google sends error/error_description on denial or failure
            error = request.query_params.get("error")
            if error:
                desc = escape(request.query_params.get("error_description", error))
                return HTMLResponse(f"<h1>Error</h1><p>{desc}</p>", status_code=400)

            code = request.query_params.get("code")
            state = request.query_params.get("state", "")
            if not code:
                return HTMLResponse("<h1>Error</h1><p>Missing authorization code.</p>", status_code=400)

            result = google_auth.handle_oauth_callback(code, state)
            if "error" in result:
                safe_error = escape(str(result["error"]))
                return HTMLResponse(f"<h1>Error</h1><p>{safe_error}</p>", status_code=400)

            # Validate services against the registered allow-list before rendering
            known = set(google_auth._services)
            safe_services = [s for s in result.get("services", []) if s in known]
            services_str = escape(", ".join(safe_services)) if safe_services else "services"
            return HTMLResponse(
                f"<h1>Connected</h1>"
                f"<p>Google {services_str} connected successfully.</p>"
                f"<p>You can close this window and return to the chat.</p>"
            )

        return router
