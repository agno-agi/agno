from dataclasses import dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from agno.db.base import BaseDb


@dataclass
class GoogleAuthConfig:
    """Google API credentials configuration.

    Pure data class — holds GCP credentials and OAuth flow options.
    Pass to toolkits directly for simple use cases, or nest a GoogleAuthManager
    inside for multi-user OAuth, DB token storage, and encryption.

    Authentication modes:
    1. OAuth (client_id + client_secret) — for user-facing apps
    2. Service account (service_account_path) — for server-to-server auth

    Example — Local dev (env vars):
        config = GoogleAuthConfig()
        agent = Agent(tools=[GmailTools(auth=config)])

    Example — Service account:
        config = GoogleAuthConfig(
            service_account_path="/path/to/sa.json",
            delegated_user="admin@company.com",
        )
        agent = Agent(tools=[GmailTools(auth=config)])

    Example — Multi-user OAuth with DB:
        config = GoogleAuthConfig(
            client_id=getenv("GOOGLE_CLIENT_ID"),
            client_secret=getenv("GOOGLE_CLIENT_SECRET"),
            redirect_uri="https://myapp.com/google/oauth/callback",
            manager=GoogleAuthManager(
                db=db,
                state_secret=getenv("GOOGLE_OAUTH_STATE_SECRET"),
                store_tokens=True,
            ),
        )
        app.include_router(config.create_router())
        agent = Agent(db=db, tools=[GmailTools(auth=config)])
    """

    # --- OAuth credentials ---
    client_id: Optional[str] = field(default_factory=lambda: getenv("GOOGLE_CLIENT_ID"))
    client_secret: Optional[str] = field(default_factory=lambda: getenv("GOOGLE_CLIENT_SECRET"))
    redirect_uri: Optional[str] = field(default_factory=lambda: getenv("GOOGLE_REDIRECT_URI", "http://localhost:8080/"))

    # --- Service account (alternative to OAuth) ---
    service_account_path: Optional[str] = field(default_factory=lambda: getenv("GOOGLE_SERVICE_ACCOUNT_FILE"))
    delegated_user: Optional[str] = field(default_factory=lambda: getenv("GOOGLE_DELEGATED_USER"))

    # --- OAuth flow options ---
    hosted_domain: Optional[str] = field(default_factory=lambda: getenv("GOOGLE_HOSTED_DOMAIN"))
    access_type: str = "offline"
    prompt: str = "consent"
    login_hint: Optional[str] = None
    include_granted_scopes: bool = False

    # --- Agno behavior (optional) ---
    manager: Optional["GoogleAuthManager"] = None

    def create_router(self):
        """Create FastAPI router for OAuth callback. Requires manager."""
        if self.manager is None:
            raise ValueError("create_router() requires a GoogleAuthManager. Set manager= in GoogleAuthConfig.")
        return self.manager.create_router(self)

    @property
    def enable_multi_user_oauth(self) -> bool:
        """Whether multi-user OAuth is enabled (URL in error vs browser fallback)."""
        return self.manager.enable_multi_user_oauth if self.manager else False


class GoogleAuthManager:
    """Agno integration for Google OAuth. Adds multi-user token storage, encryption, and router creation.

    Nested inside GoogleAuthConfig to add Agno-specific behavior:
    - Multi-user OAuth (auth fails with OAuth URL when user not authenticated)
    - Token storage in database
    - Token encryption
    - FastAPI router for OAuth callback

    Example:
        config = GoogleAuthConfig(
            client_id=getenv("GOOGLE_CLIENT_ID"),
            client_secret=getenv("GOOGLE_CLIENT_SECRET"),
            redirect_uri="https://myapp.com/google/oauth/callback",
            manager=GoogleAuthManager(
                db=db,
                state_secret=getenv("GOOGLE_OAUTH_STATE_SECRET"),
                store_tokens=True,
            ),
        )
    """

    def __init__(
        self,
        db: Optional["BaseDb"] = None,
        state_secret: Optional[str] = None,
        # Route configuration
        callback_path: Optional[str] = None,
        # Token storage
        store_tokens: bool = False,
        encrypt_tokens: bool = False,
        token_encryption_key: Optional[str] = None,
        # Multi-user OAuth: on auth failure, generate URL instead of browser fallback
        enable_multi_user_oauth: bool = False,
    ):
        # --- Scope registry ---
        self._services: Dict[str, List[str]] = {}

        # --- State and security ---
        self._db: Optional["BaseDb"] = db
        self._state_secret = state_secret or getenv("GOOGLE_OAUTH_STATE_SECRET")

        # --- Multi-user OAuth ---
        self.enable_multi_user_oauth = enable_multi_user_oauth

        # --- Route configuration ---
        self._callback_path = callback_path or getenv("GOOGLE_OAUTH_CALLBACK_PATH", "/google/oauth/callback")

        # --- Token storage ---
        self._store_tokens = store_tokens
        self._encrypt_tokens = encrypt_tokens
        self._token_encryption_key = token_encryption_key

    def register_service(self, service: str, scopes: List[str]) -> None:
        """Register scopes for a service. Called by toolkits during init."""
        existing = self._services.get(service, [])
        self._services[service] = list(set(existing) | set(scopes))

    def create_router(self, config: "GoogleAuthConfig"):
        """Create FastAPI router for OAuth callback."""
        from agno.tools.google.auth.callback import create_oauth_router

        return create_oauth_router(config)

    def persist_token(
        self,
        db: "BaseDb",
        creds: Any,
        user_id: Optional[str],
        services_registry: Optional[Dict[str, List[str]]] = None,
    ) -> bool:
        """Upsert Google credentials to DB. Returns True on success."""
        import json

        from agno.utils.log import log_debug, log_error

        if db is None:
            return False
        try:
            token_data: Dict[str, Any] = json.loads(creds.to_json())
            if services_registry:
                granted_scopes = sorted({s for scope_list in services_registry.values() for s in scope_list})
            else:
                granted_scopes = token_data.get("scopes", [])

            if self._encrypt_tokens:
                from agno.utils.encryption import encrypt_dict

                token_data = encrypt_dict(token_data, key=self._token_encryption_key)

            db.upsert_auth_token(
                {
                    "provider": "google",
                    "user_id": user_id,
                    "service": "google",
                    "token_data": token_data,
                    "granted_scopes": granted_scopes,
                    "pkce_verifier": None,
                    "pkce_state_id": None,
                    "pkce_expires_at": None,
                }
            )
            return True
        except NotImplementedError:
            log_debug("DB does not support auth token storage")
            return False
        except Exception as e:
            log_error(f"Failed to persist Google token: {e}")
            return False
