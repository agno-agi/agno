from dataclasses import dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agno.db.base import BaseDb


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

    # --- Token storage (optional) ---
    db: Optional["BaseDb"] = None
    token_encryption_key: Optional[str] = field(default_factory=lambda: getenv("GOOGLE_TOKEN_ENCRYPTION_KEY"))
