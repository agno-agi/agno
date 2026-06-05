from dataclasses import dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Any, List, Optional, Set

if TYPE_CHECKING:
    from agno.db.base import BaseDb


@dataclass
class GoogleAuth:
    """Shared auth config for Google toolkits with scope aggregation.

    When multiple toolkits share the same GoogleAuth instance, their scopes
    are combined so ONE OAuth consent covers all services.

    Example:
        auth = GoogleAuth()
        agent = Agent(tools=[
            GmailTools(auth=auth),           # registers Gmail scopes
            GoogleCalendarTools(auth=auth),  # registers Calendar scopes
            GoogleTasksTools(auth=auth),     # registers Tasks scopes
        ])
        # First tool to authenticate triggers OAuth with ALL scopes combined
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

    # --- Token storage (optional) ---
    db: Optional["BaseDb"] = None
    token_encryption_key: Optional[str] = field(default_factory=lambda: getenv("GOOGLE_TOKEN_ENCRYPTION_KEY"))

    # --- Scope aggregation (internal) ---
    _scopes: Set[str] = field(default_factory=set, repr=False)
    _creds: Any = field(default=None, repr=False)

    def register_scopes(self, scopes: List[str]) -> None:
        """Register scopes from a toolkit. Called during toolkit __init__."""
        self._scopes.update(scopes)

    @property
    def scopes(self) -> List[str]:
        """Get all registered scopes from all toolkits sharing this auth."""
        return list(self._scopes)

    @property
    def creds(self) -> Any:
        """Shared credentials across all toolkits."""
        return self._creds

    @creds.setter
    def creds(self, value: Any) -> None:
        self._creds = value
