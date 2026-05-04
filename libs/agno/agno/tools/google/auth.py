import base64
import hashlib
import inspect
import json
import os
import secrets
from contextvars import ContextVar
from functools import wraps
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.oauth_state import sign_state, verify_state


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256).

    Returns:
        (code_verifier, code_challenge) tuple.

    code_verifier: 64-char random string (A-Z, a-z, 0-9, -._~)
    code_challenge: Base64URL(SHA256(code_verifier)), no padding
    """
    # 48 bytes → 64 chars base64url (within 43-128 char spec)
    code_verifier = secrets.token_urlsafe(48)
    # S256: SHA256 hash, base64url encoded, no padding
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


# Per-call service, creds, and user_id storage for stateless toolkit access
_google_service: ContextVar[Any] = ContextVar("google_service", default=None)
_google_creds: ContextVar[Any] = ContextVar("google_creds", default=None)
_google_user_id: ContextVar[Optional[str]] = ContextVar("google_user_id", default=None)


def google_authenticate(service_name: str):
    """Shared auth decorator for all Google toolkits.

    Each toolkit creates a module-level alias:
        authenticate = google_authenticate("gmail")

    Expects the toolkit class to define:
        - _resolve_creds(run_context, agent): Returns credentials (stateless)
        - _build_service(creds): Returns build(api_name, api_version, credentials=creds)

    The decorator resolves credentials and builds a fresh service per-call,
    passing both run_context and agent to the wrapped method for stateless access.
    """

    def decorator(func):
        # Expose hidden framework params (run_context, agent) so the framework:
        # (1) builds the LLM tool schema from the original typed params (hidden ones stripped)
        # (2) injects run_context (user_id) and agent (agent.db for token storage) at call time
        # See function.py excluded_params and _build_entrypoint_args for the injection path.
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        for name in ("run_context", "agent"):
            if name not in sig.parameters:
                params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=None))
        exposed_sig = sig.replace(parameters=params)

        @wraps(func)
        def wrapper(self, *args, run_context=None, agent=None, **kwargs):
            try:
                creds = self._resolve_creds(run_context, agent)
            except Exception as e:
                log_error(f"{service_name.title()} authentication failed: {str(e)}")
                return json.dumps({"error": f"{service_name.title()} authentication failed: {e}"})

            try:
                service = self._build_service(creds)
            except Exception as e:
                log_error(f"{service_name.title()} service initialization failed: {str(e)}")
                return json.dumps({"error": f"{service_name.title()} service initialization failed: {e}"})

            # Store service, creds, and user_id in contextvars — async/thread safe
            user_id = getattr(run_context, "user_id", None) if run_context else None
            service_token = _google_service.set(service)
            creds_token = _google_creds.set(creds)
            user_id_token = _google_user_id.set(user_id)
            try:
                return func(self, *args, **kwargs)
            finally:
                _google_service.reset(service_token)
                _google_creds.reset(creds_token)
                _google_user_id.reset(user_id_token)

        wrapper.__signature__ = exposed_sig  # type: ignore[attr-defined]
        return wrapper

    return decorator


def get_current_service() -> Any:
    """Get the Google API service for the current call.

    Used by toolkit methods to access the per-call service built by @google_authenticate.
    Returns None if called outside a decorated method.
    """
    return _google_service.get()


def get_current_creds() -> Any:
    """Get the Google credentials for the current call.

    Used by toolkit methods that need to build additional services (e.g., Drive API
    for sheets duplication) with the same credentials resolved by @google_authenticate.
    Returns None if called outside a decorated method.
    """
    return _google_creds.get()


def get_current_user_id() -> Optional[str]:
    """Get the user_id for the current call.

    Used by toolkit methods to key per-user caches (e.g., label cache in Gmail).
    Returns None if called outside a decorated method or in single-user mode.
    """
    return _google_user_id.get()


def get_cache_key() -> Optional[str]:
    """Get a cache key for the current user. Returns None in single-user mode."""
    return _google_user_id.get()


def _persist_google_token(
    db: Any,
    creds: Any,
    user_id: Optional[str],
    services_registry: Optional[Dict[str, List[str]]] = None,
    encryption_key: Optional[str] = None,
) -> bool:
    """Upsert a Google credentials row.

    services_registry: if provided, granted_scopes is the union of its values
    so multiple toolkits sharing one GoogleAuth consent agree on scope.
    Otherwise falls back to whatever scopes creds.to_json() reports.

    encryption_key: if provided, token_data is encrypted at rest using Fernet.
    """
    if db is None:
        return False
    try:
        token_data: Dict[str, Any] = json.loads(creds.to_json())
        if services_registry:
            granted_scopes = sorted({s for scope_list in services_registry.values() for s in scope_list})
        else:
            granted_scopes = token_data.get("scopes", [])

        # Encrypt token_data if key is configured
        if encryption_key:
            from agno.utils.encryption import encrypt_dict

            token_data = encrypt_dict(token_data, key=encryption_key)

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


def _valid_auth_token_db(db: Any) -> Any:
    """Return db if it supports auth token CRUD, else None.

    Gates the sync BaseDb subclass that overrides get_auth_token — an AsyncBaseDb
    would return unawaited coroutines to sync callers.
    """
    if db is None:
        return None

    from agno.db.base import BaseDb

    if isinstance(db, BaseDb) and type(db).get_auth_token is not BaseDb.get_auth_token:
        return db
    return None


def get_token_db(toolkit: Any, agent: Optional[Any] = None) -> Any:
    """Resolve the DB to use for token storage. Returns None if no DB available.

    Lookup order:
      1. Explicit db on the toolkit's GoogleAuth coordinator or opt-in toolkit _db
      2. agent.db injected at call time by the framework (tool-call path)

    No toolkit state mutation — agent is read fresh per call.
    """
    ga = getattr(toolkit, "google_auth", None)
    agent_db = _valid_auth_token_db(getattr(agent, "db", None))

    if ga is not None:
        return _valid_auth_token_db(getattr(ga, "_db", None)) or agent_db
    if getattr(toolkit, "store_token_in_db", False):
        return _valid_auth_token_db(getattr(toolkit, "_db", None)) or agent_db
    return None


def load_token(
    toolkit: Any,
    scopes: list,
    user_id: Optional[str] = None,
    agent: Optional[Any] = None,
) -> bool:
    """Fetch credentials from DB, refresh if expired, set toolkit.creds. Returns True on success."""
    db = get_token_db(toolkit, agent=agent)
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

    # Check required scopes are included in granted scopes
    granted = set(row.get("granted_scopes") or [])
    required = set(scopes)
    if required and not required.issubset(granted):
        missing = required - granted
        raise PermissionError(
            f"Token missing required scopes: {', '.join(missing)}. "
            "Please re-authenticate to grant access."
        )

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        # Decrypt token_data if encrypted
        token_data = row["token_data"]
        ga = getattr(toolkit, "google_auth", None)
        encryption_key = getattr(ga, "_token_encryption_key", None) if ga else None
        if isinstance(token_data, dict) and "encrypted" in token_data:
            from agno.utils.encryption import decrypt_dict

            token_data = decrypt_dict(token_data, key=encryption_key)

        # Prefer stored granted_scopes (the full consent union) over the caller's
        # required scopes — a single-service toolkit must not narrow a shared token.
        effective_scopes = row.get("granted_scopes") or scopes
        creds = Credentials.from_authorized_user_info(token_data, effective_scopes)
    except (ValueError, KeyError, ImportError) as e:
        log_debug(f"Could not reconstruct google credentials: {e}")
        return False

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(toolkit, creds, user_id=user_id, agent=agent)
        except Exception as e:
            log_debug(f"Token refresh failed: {e}")
            return False

    if not creds.valid:
        return False

    toolkit.creds = creds
    return True


def save_token(
    toolkit: Any,
    creds: Any,
    user_id: Optional[str] = None,
    agent: Optional[Any] = None,
) -> bool:
    """Persist credentials to DB. Returns True on success."""
    ga = getattr(toolkit, "google_auth", None)
    encryption_key = getattr(ga, "_token_encryption_key", None) if ga else None
    return _persist_google_token(
        db=get_token_db(toolkit, agent=agent),
        creds=creds,
        user_id=user_id,
        services_registry=ga._services if ga else None,
        encryption_key=encryption_key,
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
        # agent.db is read per-call via framework injection (no toolkit mutation)
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
        encrypt_tokens: bool = False,
        token_encryption_key: Optional[str] = None,
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
        # Token encryption at rest (opt-in). Requires cryptography package.
        self._encrypt_tokens = encrypt_tokens
        self._token_encryption_key = (
            token_encryption_key or os.getenv("AGNO_ENCRYPTION_KEY") if encrypt_tokens else None
        )
        self.register(self.authenticate_google)

    def register_service(self, service: str, scopes: List[str]) -> None:
        self._services[service] = scopes

    def authenticate_google(
        self,
        run_context: Optional[Any] = None,
        agent: Optional[Any] = None,
    ) -> str:
        """
        Get the Google OAuth URL for the user to authenticate their Google account.

        Automatically requests scopes for ALL registered Google toolkits (Gmail, Calendar,
        Drive, etc.) so the user only needs to authenticate once.

        Returns:
            str: JSON string containing the OAuth URL or error message
        """
        if not self._services:
            return json.dumps(
                {"error": "No Google services registered. Add GmailTools, GoogleCalendarTools, etc. to your agent."}
            )

        services = list(self._services.keys())
        scopes: Set[str] = set()
        for service_scopes in self._services.values():
            scopes.update(service_scopes)

        if not self._state_secret:
            return json.dumps(
                {
                    "error": "GoogleAuth requires a state signing secret. Set state_secret= on "
                    "construction or the GOOGLE_OAUTH_STATE_SECRET environment variable."
                }
            )

        # Resolve DB for PKCE state storage
        db = _valid_auth_token_db(self._db) or _valid_auth_token_db(getattr(agent, "db", None) if agent else None)
        if db is None:
            return json.dumps(
                {
                    "error": "GoogleAuth requires a database for PKCE state storage. "
                    "Pass db= to GoogleAuth or ensure agent.db is configured."
                }
            )

        # PKCE: generate code_verifier (secret, stored in DB) and code_challenge (sent to Google)
        code_verifier, code_challenge = _generate_pkce_pair()
        # Unique state_id links the JWT to the DB row — verifier never leaves the server
        state_id = secrets.token_urlsafe(16)

        # Signed JWT carries user_id + state_id through Google redirect (NOT the verifier)
        user_id = getattr(run_context, "user_id", None) if run_context else None
        try:
            state = sign_state(
                {"user_id": user_id, "services": list(services), "state_id": state_id},
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

        # Store PKCE state in DB — same row will hold the token after exchange
        try:
            db.upsert_auth_token(
                {
                    "provider": "google",
                    "user_id": user_id,
                    "service": "google",
                    "token_data": {
                        "pkce_verifier": code_verifier,
                        "pkce_state_id": state_id,
                        "pending": True,
                    },
                    "granted_scopes": list(scopes),
                }
            )
        except Exception as e:
            log_error(f"Failed to store PKCE state: {e}")
            return json.dumps({"error": f"Failed to initialize OAuth flow: {e}"})

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true" if self._include_granted_scopes else "false",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        log_debug(f"Generated PKCE OAuth URL for user={user_id}, state_id={state_id}")
        link_text = f"Connect {', '.join(services)}"
        # Pre-formatted link for Slack mrkdwn: <url|text>
        slack_link = f"<{url}|{link_text}>"
        return json.dumps({"message": link_text, "url": url, "link": slack_link})

    def handle_oauth_callback(self, code: str, state: str, db: Any) -> Dict[str, Any]:
        """Exchange an OAuth authorization code for credentials and store in DB.

        Called by the /google/oauth/callback endpoint after Google redirects.
        The db is captured by the router closure at mount time — no process-local
        registry needed, works across workers and restarts.

        PKCE flow: The code_verifier is retrieved from the DB (stored during
        authenticate_google), verified via state_id, and used for token exchange.
        The verifier never appears in URLs or JWTs — only the state_id reference.

        Args:
            code: Authorization code from Google's redirect.
            state: HMAC-signed JWT carrying user_id, services, and state_id.
            db: Database handle for token persistence (captured by router closure).

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
        state_id = state_data.get("state_id")

        if not state_id:
            log_warning("OAuth callback missing state_id — possible replay of pre-PKCE token")
            return {"error": "Invalid state: missing state_id"}

        # Retrieve PKCE verifier from DB and verify state_id matches
        try:
            row = db.get_auth_token("google", user_id, "google")
        except Exception as e:
            log_error(f"Failed to retrieve PKCE state: {e}")
            return {"error": "Failed to verify OAuth state"}

        if not row:
            log_warning(f"No PKCE state found for user={user_id}")
            return {"error": "OAuth session expired or invalid. Please try again."}

        token_data = row.get("token_data", {})
        stored_state_id = token_data.get("pkce_state_id")
        code_verifier = token_data.get("pkce_verifier")

        if not stored_state_id or stored_state_id != state_id:
            log_warning(f"PKCE state_id mismatch for user={user_id}: expected {stored_state_id}, got {state_id}")
            return {"error": "OAuth session expired or invalid. Please try again."}

        if not code_verifier:
            log_warning(f"Missing code_verifier for user={user_id}")
            return {"error": "OAuth session corrupted. Please try again."}

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

            # PKCE: pass code_verifier to token exchange
            flow.fetch_token(code=code, code_verifier=code_verifier)
            creds = flow.credentials

        except Exception as e:
            log_error(f"OAuth token exchange failed: {e}")
            return {"error": f"Token exchange failed: {e}"}

        stored = _persist_google_token(
            db=db,
            creds=creds,
            user_id=user_id,
            services_registry=self._services,
            encryption_key=self._token_encryption_key,
        )
        if not stored:
            log_error(f"Token obtained but DB persistence failed for user={user_id}")
            return {"error": "Token obtained but could not be saved to database"}

        log_info(f"OAuth complete for user={user_id}, services={services}")
        return {"status": "ok", "user_id": user_id, "services": services}

    def get_oauth_router(self, db: Any = None) -> Any:
        """Create a FastAPI APIRouter with the /google/oauth/callback endpoint.

        Calling this marks GoogleAuth as "interface mode" — toolkits will raise
        PermissionError on token miss so the LLM can surface an OAuth URL, rather
        than falling through to a local browser flow.

        The db is captured in the router closure at mount time — no process-local
        registry needed, works across workers and container restarts.

        Args:
            db: Database for token persistence. Falls back to GoogleAuth(db=...).

        Usage:
            google_auth = GoogleAuth(client_id="...")
            app.include_router(google_auth.get_oauth_router(db=agent.db))
        """
        if not self._state_secret:
            raise RuntimeError(
                "GoogleAuth.get_oauth_router() requires a state signing secret. "
                "Set state_secret= or the GOOGLE_OAUTH_STATE_SECRET env var."
            )

        # Resolve db: explicit param > GoogleAuth(db=...) > fail
        resolved_db = _valid_auth_token_db(db) or _valid_auth_token_db(self._db)
        if resolved_db is None:
            raise RuntimeError(
                "GoogleAuth.get_oauth_router() requires a DB with auth token support. "
                "Pass db= or set GoogleAuth(db=...)."
            )

        self._callback_configured = True
        from html import escape

        from fastapi import APIRouter, Request
        from fastapi.responses import HTMLResponse

        router = APIRouter(tags=["Google OAuth"])
        google_auth = self
        # Captured in closure — survives restarts, works across workers
        callback_db = resolved_db

        @router.get("/google/oauth/callback")
        async def oauth_callback(request: Request) -> HTMLResponse:
            error = request.query_params.get("error")
            if error:
                desc = escape(request.query_params.get("error_description", error))
                return HTMLResponse(f"<h1>Error</h1><p>{desc}</p>", status_code=400)

            code = request.query_params.get("code")
            state = request.query_params.get("state", "")
            if not code:
                return HTMLResponse("<h1>Error</h1><p>Missing authorization code.</p>", status_code=400)

            result = google_auth.handle_oauth_callback(code, state, db=callback_db)
            if "error" in result:
                safe_error = escape(str(result["error"]))
                return HTMLResponse(f"<h1>Error</h1><p>{safe_error}</p>", status_code=400)

            known = set(google_auth._services)
            safe_services = [s for s in result.get("services", []) if s in known]
            services_str = escape(", ".join(safe_services)) if safe_services else "services"
            return HTMLResponse(
                f"<h1>Connected</h1>"
                f"<p>Google {services_str} connected successfully.</p>"
                f"<p>You can close this window and return to the chat.</p>"
            )

        return router
