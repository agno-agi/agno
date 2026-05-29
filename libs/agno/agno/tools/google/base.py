import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from agno.tools import Toolkit
from agno.tools.google.auth import get_current_service
from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.tools.google.auth import GoogleAuthConfig


class GoogleToolkit(Toolkit):
    """Base class for Google Workspace API toolkits.

    Provides unified credential resolution, DB token storage, and per-call service
    isolation via contextvars. Subclasses set class attributes and implement hooks.

    Credential resolution order:
    1. Explicit creds passed to constructor (single-user mode only)
    2. Service account file (if path provided)
    3. DB lookup via agent.db (multi-user mode)
    4. File fallback (token.json for local development)
    5. Interactive OAuth (browser-based, local only)

    Subclasses must set:
        api_name: str - Google API name (e.g., "gmail", "calendar")
        api_version: str - API version (e.g., "v1", "v3")
        google_service_name: str - Name for GoogleAuth registry (e.g., "gmail")
        default_scopes: List[str] | Dict[str, str] - Default scopes (list) or tiered scope levels (dict)

    Optional overrides:
        require_delegated_user_for_service_account: bool - If True, service account
            auth requires delegated_user (Gmail needs this for domain-wide delegation)
    """

    api_name: str = ""
    api_version: str = ""
    google_service_name: str = ""
    default_scopes: Union[List[str], Dict[str, str]] = []
    require_delegated_user_for_service_account: bool = False

    def __init__(
        self,
        scopes: Optional[List[str]] = None,
        creds: Optional[Any] = None,
        token_path: Optional[str] = None,
        credentials_path: Optional[str] = None,
        # New: unified auth config
        auth: Optional["GoogleAuthConfig"] = None,
        # Legacy params (use auth= instead)
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        auth_config: Optional["GoogleAuthConfig"] = None,
        store_token_in_db: bool = False,
        oauth_port: Optional[int] = 0,
        login_hint: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        # Cast is safe: dict-based toolkits (Drive, Sheets) always pass scopes explicitly
        self.scopes = scopes if scopes is not None else cast(List[str], self.default_scopes).copy()
        self._explicit_creds = creds
        self.token_path = token_path
        self.credentials_path = credentials_path
        self.oauth_port = oauth_port

        # Normalize auth config: auth= takes precedence over auth_config=
        self._auth = auth or auth_config

        # Legacy params — only used if no auth config provided
        self._legacy_service_account_path = service_account_path
        self._legacy_delegated_user = delegated_user
        self._legacy_login_hint = login_hint
        self._legacy_store_token_in_db = store_token_in_db
        self._db: Optional[Any] = None

        # Register service scopes with manager
        if self._auth and self._auth.manager and self.google_service_name:
            self._auth.manager.register_service(self.google_service_name, self.scopes)

    @property
    def service(self) -> Any:
        """Per-call service from contextvar. Set by @google_authenticate decorator."""
        return get_current_service()

    def _build_service(self, creds: Any) -> Any:
        """Build the Google API service client."""
        from googleapiclient.discovery import build

        return build(self.api_name, self.api_version, credentials=creds)

    def _get_service_account_path(self) -> Optional[str]:
        """Resolve service account path from auth config or legacy params."""
        if self._auth:
            return self._auth.service_account_path
        return self._legacy_service_account_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")

    def _get_delegated_user(self) -> Optional[str]:
        """Resolve delegated user from auth config or legacy params."""
        if self._auth:
            return self._auth.delegated_user
        return self._legacy_delegated_user or os.getenv("GOOGLE_DELEGATED_USER")

    def _get_service_account_creds(self, service_account_path: str) -> Any:
        """Build service account credentials.

        Override for service-specific logic (e.g., Gmail's delegated_user requirement).
        """
        from google.auth.transport.requests import Request
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials

        delegated_user = self._get_delegated_user()

        if self.require_delegated_user_for_service_account and not delegated_user:
            raise ValueError(
                f"delegated_user is required for {self.google_service_name.title()} service account authentication. "
                f"{self.google_service_name.title()} service accounts must impersonate a user via domain-wide delegation. "
                "Provide delegated_user as a parameter or set GOOGLE_DELEGATED_USER env var."
            )

        creds = ServiceAccountCredentials.from_service_account_file(
            service_account_path,
            scopes=self.scopes,
        )

        if delegated_user:
            creds = creds.with_subject(delegated_user)

        creds.refresh(Request())
        return creds

    def _load_from_db(self, db: Any, user_id: Optional[str]) -> Any:
        """Load and refresh credentials from DB."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        from agno.utils.encryption import decrypt_dict, is_encrypted

        try:
            row = db.get_auth_token("google", user_id, "google")
        except (NotImplementedError, Exception):
            return None
        if not row:
            return None

        # Check required scopes are included in granted scopes
        granted = set(row.get("granted_scopes") or [])
        required = set(self.scopes)
        if required and not required.issubset(granted):
            missing = required - granted
            raise PermissionError(
                f"{self.google_service_name.title()} requires additional scopes: {', '.join(missing)}. "
                "Please re-authenticate to grant access."
            )

        try:
            token_data = row["token_data"]
            manager = self._auth.manager if self._auth else None
            if is_encrypted(token_data):
                key = manager._token_encryption_key if manager else None
                token_data = decrypt_dict(token_data, key=key)
            effective_scopes = row.get("granted_scopes") or self.scopes
            creds = Credentials.from_authorized_user_info(token_data, effective_scopes)
        except (ValueError, KeyError, ImportError):
            return None

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                if manager:
                    manager.persist_token(creds=creds, user_id=user_id)
            except Exception:
                # Token refresh failed — needs re-authentication
                return None

        return creds if creds.valid else None

    def _resolve_creds(self, run_context: Any = None, agent: Any = None) -> Any:
        """Stateless credential resolution. Returns credentials, does not cache on self."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        user_id = getattr(run_context, "user_id", None) if run_context else None

        # 1. Explicit creds from constructor (when multi-user OAuth is not enabled)
        multi_user_mode = self._auth and self._auth.enable_multi_user_oauth
        if self._explicit_creds and self._explicit_creds.valid and not multi_user_mode:
            return self._explicit_creds

        # 2. Service account (never stored in DB)
        service_account_path = self._get_service_account_path()
        if service_account_path:
            return self._get_service_account_creds(service_account_path)

        # 3. DB lookup
        manager = self._auth.manager if self._auth else None
        db = manager._db if manager and manager._store_tokens else None
        if db:
            creds = self._load_from_db(db, user_id)
            if creds:
                return creds
            # Multi-user mode: users authenticate via OAuth URL, no browser fallback
            if multi_user_mode:
                raise PermissionError(
                    f"{self.google_service_name.title()} not authenticated — user must complete OAuth via oauth_google"
                )

        # 4. File fallback (local mode)
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        creds = None
        if token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
            except ValueError:
                creds = None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_file.write_text(creds.to_json())
            except Exception:
                creds = None

        if creds and creds.valid:
            return creds

        # 5. Interactive OAuth (local only)
        manager = self._auth.manager if self._auth else None
        if manager and manager._services:
            consent_scopes = sorted({s for scope_list in manager._services.values() for s in scope_list})
        else:
            consent_scopes = self.scopes

        # Build client config from auth config or env vars
        client_id = self._auth.client_id if self._auth else os.getenv("GOOGLE_CLIENT_ID")
        client_secret = self._auth.client_secret if self._auth else os.getenv("GOOGLE_CLIENT_SECRET")
        redirect_uri = self._auth.redirect_uri if self._auth else os.getenv("GOOGLE_REDIRECT_URI", "http://localhost")

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "project_id": os.getenv("GOOGLE_PROJECT_ID"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": [redirect_uri],
            }
        }
        if creds_file.exists():
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), consent_scopes)
        else:
            flow = InstalledAppFlow.from_client_config(client_config, consent_scopes)

        oauth_kwargs: Dict[str, Any] = {"prompt": "consent"}
        login_hint = self._auth.login_hint if self._auth else self._legacy_login_hint
        if login_hint:
            oauth_kwargs["login_hint"] = login_hint
        hosted_domain = self._auth.hosted_domain if self._auth else None
        if hosted_domain:
            oauth_kwargs["hd"] = hosted_domain
        creds = flow.run_local_server(port=self.oauth_port or 0, **oauth_kwargs)

        # Save to DB or file
        if creds and creds.valid:
            mgr = self._auth.manager if self._auth else None
            if (
                mgr
                and mgr._store_tokens
                and mgr._db
                and mgr.persist_token(creds=creds, user_id=user_id)
            ):
                log_debug(f"{self.google_service_name.title()} credentials saved to DB")
            else:
                token_file.write_text(creds.to_json())
                log_debug(f"{self.google_service_name.title()} credentials saved to file")

        return creds
