from dataclasses import dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agno.tools.google.auth.manager import OAuthConfig


@dataclass
class GoogleAuth:
    """GCP credentials for Google toolkits. Defaults from env vars."""

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
    oauth_config: Optional["OAuthConfig"] = None

    def create_router(self):
        if self.oauth_config is None:
            raise ValueError("create_router() requires an OAuthConfig. Set oauth_config= in GoogleAuth.")
        return self.oauth_config.create_router(self)

    @property
    def enable_multi_user_oauth(self) -> bool:
        return self.oauth_config.enable_multi_user_oauth if self.oauth_config else False
