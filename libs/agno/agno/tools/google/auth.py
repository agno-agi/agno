import os
from typing import Any, Dict, List, Optional

from agno.utils.log import log_error, log_info, log_warning
from agno.utils.oauth_state import verify_state

from agno.tools.google.tokens import _persist_google_token, _valid_auth_token_db


class GoogleAuthManager:
    """OAuth coordinator for Google toolkits — NOT a Toolkit itself.

    Handles:
    - OAuth URL generation for interactive auth flows (Slack, etc.)
    - Token storage/retrieval via agent's DB when available
    - Service scope registry for combined OAuth consent

    Usage (cookbook — file-based, zero config):
        gmail = GmailTools()

    Usage (interface — client-side OAuth, opt-in):
        auth_config = GoogleAuthManager(hosted_domain="mycompany.com")
        agent = Agent(
            db=db,
            tools=[
                GoogleOAuthTools(auth_config=auth_config),
                GmailTools(),  # Auto-wired from GoogleOAuthTools
            ],
        )
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
        # Enterprise OAuth parameters
        hosted_domain: Optional[str] = None,
        access_type: str = "offline",
        prompt: str = "consent",
        login_hint: Optional[str] = None,
        # Route configuration
        callback_path: Optional[str] = None,
        # Service account authentication (alternative to OAuth)
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        # Token storage config
        store_tokens: bool = False,
        encrypt_tokens: bool = False,
        token_encryption_key: Optional[str] = None,
    ):
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8080/")
        self._db: Optional[Any] = db
        self._services: Dict[str, List[str]] = {}
        self._callback_configured: bool = False
        self._state_secret = state_secret or os.getenv("GOOGLE_OAUTH_STATE_SECRET")
        self._include_granted_scopes = include_granted_scopes
        self._state_ttl_seconds = state_ttl_seconds
        self._hosted_domain = hosted_domain or os.getenv("GOOGLE_HOSTED_DOMAIN")
        self._access_type = access_type
        self._callback_path = callback_path or os.getenv("GOOGLE_OAUTH_CALLBACK_PATH", "/google/oauth/callback")
        self._prompt = prompt
        self._login_hint = login_hint
        self._service_account_path = service_account_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        self._delegated_user = delegated_user or os.getenv("GOOGLE_DELEGATED_USER")
        self._store_tokens = store_tokens
        self._encrypt_tokens = encrypt_tokens
        self._token_encryption_key = token_encryption_key

    def register_service(self, service: str, scopes: List[str]) -> None:
        existing = self._services.get(service, [])
        self._services[service] = list(set(existing) | set(scopes))

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
        try:
            import jwt
        except ImportError:
            return {
                "error": "PyJWT is required for OAuth state verification. "
                "Install with `pip install PyJWT` or `pip install agno[os]`."
            }

        if not self._state_secret:
            return {
                "error": "GOOGLE_OAUTH_STATE_SECRET not configured. "
                "OAuth callback cannot verify state without a signing secret."
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

        try:
            row = db.get_auth_token("google", user_id, "google")
        except Exception as e:
            log_error(f"Failed to retrieve PKCE state: {e}")
            return {"error": "Failed to verify OAuth state"}

        if not row:
            log_warning(f"No PKCE state found for user={user_id}")
            return {"error": "OAuth session expired or invalid. Please try again."}

        stored_state_id = row.get("pkce_state_id")
        code_verifier = row.get("pkce_verifier")
        pkce_expires_at = row.get("pkce_expires_at")

        if not stored_state_id or stored_state_id != state_id:
            log_warning(f"PKCE state_id mismatch for user={user_id}: expected {stored_state_id}, got {state_id}")
            return {"error": "OAuth session expired or invalid. Please try again."}

        if not code_verifier:
            log_warning(f"Missing code_verifier for user={user_id}")
            return {"error": "OAuth session corrupted. Please try again."}

        import time

        if pkce_expires_at and int(time.time()) > pkce_expires_at:
            log_warning(f"PKCE state expired for user={user_id}")
            return {"error": "OAuth session expired. Please try again."}

        try:
            from google_auth_oauthlib.flow import Flow

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
            auth_config=self,
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
                "GOOGLE_OAUTH_STATE_SECRET is required for OAuth callback security. "
                "Set it via environment variable or GoogleAuthManager(state_secret=...)."
            )

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
        callback_path: str = self._callback_path or "/google/oauth/callback"
        callback_db = resolved_db

        @router.get(callback_path)
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
