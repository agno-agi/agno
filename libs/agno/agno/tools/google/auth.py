import inspect
import json
import os
from functools import wraps
from typing import Any, Dict, List, Literal, Optional, Set
from urllib.parse import urlencode

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.oauth_state import sign_state, verify_state


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
                    log_error(f"{service_name.title()} authentication failed: {str(e)}")
                    return json.dumps({"error": f"{service_name.title()} authentication failed: {e}"})
            if not self.service:
                try:
                    self.service = self._build_service()
                except Exception as e:
                    log_error(f"{service_name.title()} service initialization failed: {str(e)}")
                    return json.dumps({"error": f"{service_name.title()} service initialization failed: {e}"})
            return func(self, *args, **kwargs)

        wrapper.__signature__ = exposed_sig  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _persist_google_token(
    db: Any,
    creds: Any,
    user_id: Optional[str],
    services_registry: Optional[Dict[str, List[str]]] = None,
) -> bool:
    """Upsert a Google credentials row.

    services_registry: if provided, granted_scopes is the union of its values
    so multiple toolkits sharing one GoogleAuth consent agree on scope.
    Otherwise falls back to whatever scopes creds.to_json() reports.
    """
    if db is None:
        return False
    try:
        token_data = json.loads(creds.to_json())
        if services_registry:
            granted_scopes = sorted({s for scope_list in services_registry.values() for s in scope_list})
        else:
            granted_scopes = token_data.get("scopes", [])
        db.upsert_auth_token(
            {
                "provider": "google",
                "user_id": user_id,
                "service": "google",
                "token_data": token_data,
                "granted_scopes": granted_scopes,
            }
        )
        return True
    except NotImplementedError:
        log_debug("DB does not support auth token storage")
        return False
    except Exception as e:
        log_error(f"Failed to persist Google token: {e}")
        return False


def get_token_db(toolkit: Any) -> Any:
    """Resolve the DB to use for token storage. Returns None if no DB available."""
    ga = getattr(toolkit, "google_auth", None)
    if ga and ga._db:
        return ga._db
    if getattr(toolkit, "store_token_in_db", False):
        return getattr(toolkit, "_db", None)
    return None


def load_token(toolkit: Any, scopes: list, user_id: Optional[str] = None) -> bool:
    """Fetch credentials from DB, refresh if expired, set toolkit.creds. Returns True on success."""
    db = get_token_db(toolkit)
    if db is None:
        return False
    try:
        row = db.get_auth_token("google", user_id, "google")
    except NotImplementedError:
        return False
    except Exception as e:
        log_debug(f"DB load failed for google: {e}")
        return False
    if not row:
        return False

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        # Prefer stored granted_scopes (the full consent union) over the caller's
        # required scopes — a single-service toolkit must not narrow a shared token.
        effective_scopes = row.get("granted_scopes") or scopes
        creds = Credentials.from_authorized_user_info(row["token_data"], effective_scopes)
    except (ValueError, KeyError, ImportError) as e:
        log_debug(f"Could not reconstruct google credentials: {e}")
        return False

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(toolkit, creds, user_id=user_id)
        except Exception as e:
            log_debug(f"Token refresh failed: {e}")
            return False

    if not creds.valid:
        return False

    toolkit.creds = creds
    return True


def save_token(toolkit: Any, creds: Any, user_id: Optional[str] = None) -> bool:
    """Persist credentials to DB. Returns True on success."""
    ga = getattr(toolkit, "google_auth", None)
    return _persist_google_token(
        db=get_token_db(toolkit),
        creds=creds,
        user_id=user_id,
        services_registry=ga._services if ga else None,
    )


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
        state_secret: Optional[str] = None,
        state_ttl_seconds: int = 600,
        include_granted_scopes: bool = False,
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
        # Set by auto-wiring from agent.db, or explicitly via db= param
        self._db: Optional[Any] = db
        self._services: Dict[str, List[str]] = {}
        # True once get_oauth_router() has mounted a callback handler — toolkits read this
        # to choose interface mode (raise, let LLM handle OAuth) vs cookbook mode (browser).
        self._callback_configured: bool = False
        # Shared HMAC secret for signing the state JWT. Must match across workers.
        self._state_secret = state_secret or os.getenv("GOOGLE_OAUTH_STATE_SECRET")
        # When True, Google carries prior grants for the same OAuth client into the
        # response — convenient for multi-toolkit, but per-scope revocation moves to
        # myaccount.google.com rather than clearing a scope-narrow row here.
        self._include_granted_scopes = include_granted_scopes
        self._state_ttl_seconds = state_ttl_seconds
        self.register(self.authenticate_google)

    def register_service(self, service: str, scopes: List[str]) -> None:
        self._services[service] = scopes

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

        if not self._state_secret:
            return json.dumps(
                {
                    "error": "GoogleAuth requires a state signing secret. Set state_secret= on "
                    "construction or the GOOGLE_OAUTH_STATE_SECRET environment variable."
                }
            )

        # Signed JWT carries user_id through the Google round-trip unforgeably.
        user_id = getattr(run_context, "user_id", None) if run_context else None
        try:
            state = sign_state(
                {"user_id": user_id, "services": list(services)},
                secret=self._state_secret,
                ttl_seconds=self._state_ttl_seconds,
            )
        except ImportError:
            return json.dumps(
                {
                    "error": "PyJWT is required for OAuth state signing. "
                    "Install with `pip install PyJWT` or `pip install agno[os]`."
                }
            )

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true" if self._include_granted_scopes else "false",
            "state": state,
        }
        url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        return json.dumps({"message": f"Connect {', '.join(services)}", "url": url})

    def handle_oauth_callback(self, code: str, state: str) -> Dict[str, Any]:
        """Exchange an OAuth authorization code for credentials and store in DB.

        Called by the /google/oauth/callback endpoint after Google redirects.

        Args:
            code: Authorization code from Google's redirect.
            state: HMAC-signed JWT carrying user_id and services (see authenticate_google).

        Returns:
            Dict with status, user_id, and services that were authorized.
        """
        if not self._state_secret:
            return {
                "error": "GoogleAuth requires a state signing secret. Set state_secret= on "
                "construction or the GOOGLE_OAUTH_STATE_SECRET environment variable."
            }

        try:
            import jwt  # imported for the exception type
        except ImportError:
            return {
                "error": "PyJWT is required for OAuth state verification. "
                "Install with `pip install PyJWT` or `pip install agno[os]`."
            }

        try:
            state_data = verify_state(state, secret=self._state_secret)
        except jwt.InvalidTokenError as e:
            log_warning(f"Rejected OAuth callback: {e}")
            return {"error": f"Invalid state: {e}"}

        user_id = state_data.get("user_id")
        services = state_data.get("services", [])

        try:
            from google_auth_oauthlib.flow import Flow

            # include_granted_scopes=true may return scopes beyond this flow's request;
            # pass the union and disable strict-match. false mode passes just this flow's
            # scopes and lets oauthlib verify the response shape normally.
            if self._include_granted_scopes:
                scopes: list = []
                for svc_scopes in self._services.values():
                    scopes.extend(svc_scopes)
            else:
                scopes = []
                for svc in services:
                    scopes.extend(self._services.get(svc, []))

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

            if self._include_granted_scopes:
                flow.oauth2session.scope = None

            flow.fetch_token(code=code)
            creds = flow.credentials

        except Exception as e:
            log_error(f"OAuth token exchange failed: {e}")
            return {"error": f"Token exchange failed: {e}"}

        # Store one consolidated token row — all Google services share it
        stored = _persist_google_token(
            db=self._db,
            creds=creds,
            user_id=user_id,
            services_registry=self._services,
        )
        if not stored:
            log_error(f"Token obtained but DB persistence failed for user={user_id}")
            return {"error": "Token obtained but could not be saved to database"}

        log_info(f"OAuth complete for user={user_id}, services={services}")
        return {"status": "ok", "user_id": user_id, "services": services}

    def get_oauth_router(self) -> Any:
        """Create a FastAPI APIRouter with the /google/oauth/callback endpoint.

        Calling this marks GoogleAuth as "interface mode" — toolkits will raise
        PermissionError on token miss so the LLM can surface an OAuth URL, rather
        than falling through to a local browser flow.

        The router closes over this GoogleAuth instance. _db must be wired
        (via AgentOS init-time binding or explicit db= param) before the
        callback fires, otherwise token storage silently skips.

        Usage:
            google_auth = GoogleAuth(client_id="...")
            app.include_router(google_auth.get_oauth_router())
        """
        # Fail-closed at mount on config the agent can't recover (no db-wiring hook
        # for the state secret). The db for token persistence is auto-wired at
        # agent.run() time — don't require it this early.
        if not self._state_secret:
            raise RuntimeError(
                "GoogleAuth.get_oauth_router() requires a state signing secret. "
                "Set state_secret= or the GOOGLE_OAUTH_STATE_SECRET env var."
            )
        self._callback_configured = True
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
