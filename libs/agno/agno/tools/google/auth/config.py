from dataclasses import dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agno.tools.google.auth.manager import GoogleAuthManager


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
