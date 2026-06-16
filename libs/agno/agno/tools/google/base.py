import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from agno.tools import Toolkit
from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.tools.google.auth import AuthConfig


class GoogleToolkit(Toolkit):
    """Base class for Google Workspace API toolkits."""

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
        # Unified auth config for scope aggregation + DB storage
        auth: Optional["AuthConfig"] = None,
        # Legacy params (use auth= instead)
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        oauth_port: Optional[int] = 0,
        login_hint: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        # Cast is safe: dict-based toolkits (Drive, Sheets) always pass scopes explicitly
        self.scopes = scopes if scopes is not None else cast(List[str], self.default_scopes).copy()
        self.creds = creds
        self._service: Optional[Any] = None
        self.token_path = token_path
        self.credentials_path = credentials_path
        self.oauth_port = oauth_port

        # Create internal AuthConfig if none provided, populated with constructor params
        if auth is None:
            from agno.tools.google.auth import AuthConfig

            # Only pass explicitly set params — let AuthConfig use env var defaults for None
            auth_kwargs: Dict[str, Any] = {}
            if service_account_path is not None:
                auth_kwargs["service_account_path"] = service_account_path
            if delegated_user is not None:
                auth_kwargs["delegated_user"] = delegated_user
            if login_hint is not None:
                auth_kwargs["login_hint"] = login_hint
            self._auth = AuthConfig(**auth_kwargs)
        else:
            self._auth = auth

        # Register scopes with shared auth for aggregation
        self._auth.register_scopes(self.scopes)

    @property
    def service(self) -> Any:
        """Get the Google API service client."""
        return self._service

    def _build_service(self, creds: Any) -> Any:
        """Build the Google API service client."""
        from googleapiclient.discovery import build

        return build(self.api_name, self.api_version, credentials=creds)

    def _get_service_account_path(self) -> Optional[str]:
        """Get service account path from auth config."""
        return self._auth.service_account_path

    def _get_delegated_user(self) -> Optional[str]:
        """Get delegated user from auth config."""
        return self._auth.delegated_user

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
            if is_encrypted(token_data):
                key = getattr(self._auth, "token_encryption_key", None)
                token_data = decrypt_dict(token_data, key=key)
            effective_scopes = row.get("granted_scopes") or self.scopes
            creds = Credentials.from_authorized_user_info(token_data, effective_scopes)
        except (ValueError, KeyError, ImportError):
            return None

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                return None

        return creds if creds.valid else None

    def _resolve_creds(self) -> Any:
        """Resolve credentials using the priority chain. Returns credentials.

        When using shared GoogleAuth, credentials are cached on the auth object
        and scopes are aggregated across all toolkits sharing that auth.
        """
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        # 1. Shared creds from GoogleAuth (already authenticated by another toolkit)
        if self._auth and self._auth.creds and self._auth.creds.valid:
            return self._auth.creds

        # 2. Instance creds (passed directly or already resolved)
        if self.creds and self.creds.valid:
            return self.creds

        # 3. Service account (never stored in DB)
        service_account_path = self._get_service_account_path()
        if service_account_path:
            creds = self._get_service_account_creds(service_account_path)
            if self._auth:
                self._auth.creds = creds
            return creds

        # Use aggregated scopes from GoogleAuth if available
        oauth_scopes = self._auth.scopes if self._auth else self.scopes

        # 4. DB lookup (if configured via auth.db)
        db = getattr(self._auth, "db", None) if self._auth else None
        if db:
            creds = self._load_from_db(db, user_id=None)
            if creds:
                if self._auth:
                    self._auth.creds = creds
                return creds

        # 5. File fallback (local mode)
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        creds = None
        if token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_file), oauth_scopes)
            except ValueError:
                creds = None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_file.write_text(creds.to_json())
            except Exception:
                creds = None

        if creds and creds.valid:
            if self._auth:
                self._auth.creds = creds
            return creds

        # 6. Interactive OAuth (local only) — uses AGGREGATED scopes
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
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), oauth_scopes)
        else:
            flow = InstalledAppFlow.from_client_config(client_config, oauth_scopes)

        oauth_kwargs: Dict[str, Any] = {"prompt": "consent"}
        if self._auth.login_hint:
            oauth_kwargs["login_hint"] = self._auth.login_hint
        if self._auth.hosted_domain:
            oauth_kwargs["hd"] = hosted_domain
        creds = flow.run_local_server(port=self.oauth_port or 0, **oauth_kwargs)

        # Save to DB or file, then cache on GoogleAuth
        if creds and creds.valid:
            if db:
                self._save_to_db(db, creds, user_id=None)
            else:
                token_file.write_text(creds.to_json())
                log_debug(f"{self.google_service_name.title()} credentials saved to file")
            if self._auth:
                self._auth.creds = creds

        return creds

    def _save_to_db(self, db: Any, creds: Any, user_id: Optional[str]) -> bool:
        """Save credentials to DB."""
        from agno.utils.encryption import encrypt_dict

        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
        }

        # Encrypt if key provided
        key = getattr(self._auth, "token_encryption_key", None)
        if key:
            token_data = encrypt_dict(token_data, key=key)

        try:
            db.upsert_auth_token(
                {
                    "provider": "google",
                    "user_id": user_id,
                    "service": "google",
                    "token_data": token_data,
                    "granted_scopes": list(creds.scopes)
                    if creds.scopes
                    else (self._auth.scopes if self._auth else self.scopes),
                }
            )
            log_debug(f"{self.google_service_name.title()} credentials saved to DB")
            return True
        except Exception as e:
            log_debug(f"Failed to save credentials to DB: {e}")
            return False
