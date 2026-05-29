"""OAuth configuration for Google toolkits.

GoogleAuthManager holds config and scope registry.
Callback handling lives in callback.py.
"""
from os import getenv
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from agno.db.base import BaseDb


class GoogleAuthManager:
    """OAuth configuration for Google toolkits. Holds credentials, scopes, and flow options."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        db: Optional["BaseDb"] = None,
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
        # --- OAuth credentials ---
        self.client_id = client_id or getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or getenv("GOOGLE_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or getenv("GOOGLE_REDIRECT_URI", "http://localhost:8080/")

        # --- Scope registry ---
        # Service → scopes mapping, populated by toolkit.register_service()
        self._services: Dict[str, List[str]] = {}

        # --- State and security ---
        self._db: Optional["BaseDb"] = db
        self._state_secret = state_secret or getenv("GOOGLE_OAUTH_STATE_SECRET")
        self._state_ttl_seconds = state_ttl_seconds
        # Set True by create_oauth_router() — tells toolkits to block browser fallback
        self._callback_configured: bool = False

        # --- OAuth flow options ---
        self._include_granted_scopes = include_granted_scopes
        self._hosted_domain = hosted_domain or getenv("GOOGLE_HOSTED_DOMAIN")
        self._access_type = access_type
        self._prompt = prompt
        self._login_hint = login_hint
        self._callback_path = callback_path or getenv("GOOGLE_OAUTH_CALLBACK_PATH", "/google/oauth/callback")

        # --- Service account (alternative to OAuth) ---
        # Shared across all toolkits using this manager
        self._service_account_path = service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        self._delegated_user = delegated_user or getenv("GOOGLE_DELEGATED_USER")

        # --- Token storage ---
        self._store_tokens = store_tokens
        self._encrypt_tokens = encrypt_tokens
        self._token_encryption_key = token_encryption_key

    def register_service(self, service: str, scopes: List[str]) -> None:
        """Register scopes for a service. Called by toolkits during init."""
        # Union with existing scopes — allows incremental registration
        existing = self._services.get(service, [])
        self._services[service] = list(set(existing) | set(scopes))
