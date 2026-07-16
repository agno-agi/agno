import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from agno.tools import Toolkit
from agno.tools.google.auth import AuthConfig
from agno.utils.log import log_debug, log_warning


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
        auth: Optional[AuthConfig] = None,
        # Legacy params (use auth= instead)
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        oauth_port: Optional[int] = 0,
        login_hint: Optional[str] = None,
        **kwargs: Any,
    ):
        # Validate: don't mix auth= with legacy params
        legacy_params = [
            ("service_account_path", service_account_path),
            ("delegated_user", delegated_user),
        ]
        if auth is not None:
            conflicts = [name for name, val in legacy_params if val is not None]
            if conflicts:
                raise ValueError(
                    f"Cannot use both auth= and legacy params ({', '.join(conflicts)}). "
                    "Set these on AuthConfig instead."
                )

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

    def _build_google_service(self, api_name: str, api_version: str, creds: Any) -> Any:
        """Build a Google API service client with timeout-aware HTTP transport.

        This is the single place for httplib2/AuthorizedHttp construction.
        Subclasses should call this instead of duplicating the import/setup.
        """
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build

        timeout = self._get_http_timeout()
        http = httplib2.Http(timeout=timeout)
        authed_http = AuthorizedHttp(creds, http=http)

        return build(api_name, api_version, http=authed_http)

    def _build_service(self, creds: Any) -> Any:
        """Build the primary Google API service client.

        Subclasses can override to transform creds or build companion services.
        """
        return self._build_google_service(self.api_name, self.api_version, creds)

    def _get_http_timeout(self) -> float:
        """Get HTTP timeout from AuthConfig, env, or default (120s matches Google SDK)."""
        if self._auth and self._auth.http_timeout is not None:
            return self._auth.http_timeout
        env_timeout = os.getenv("GOOGLE_API_TIMEOUT")
        if env_timeout:
            try:
                return float(env_timeout)
            except (TypeError, ValueError):
                pass
        return 120.0

    def _make_auth_request(self) -> Any:
        """Create Request for credential refresh operations.

        google.auth.transport.requests.Request uses 120s default timeout internally.
        httplib2-based API calls use _build_google_service with configurable timeout.
        """
        from google.auth.transport.requests import Request

        return Request()

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

        creds.refresh(self._make_auth_request())
        return creds

    def _has_required_scopes(self, creds: Any) -> bool:
        """Check if credentials cover this toolkit's required scopes."""
        granted = set(getattr(creds, "scopes", None) or [])
        required = set(self.scopes)
        if required and not required.issubset(granted):
            missing = required - granted
            log_warning(
                f"{self.google_service_name.title()} cached credentials missing scopes: {', '.join(missing)}. "
                "Re-authenticating with broader scopes."
            )
            return False
        return True

    def _resolve_creds(self) -> Any:
        """Resolve credentials using the priority chain. Returns credentials.

        When using shared GoogleAuth, credentials are cached on the auth object
        and scopes are aggregated across all toolkits sharing that auth.
        """
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        # 1. Shared creds from GoogleAuth (already authenticated by another toolkit)
        if self._auth and self._auth.creds and self._auth.creds.valid:
            if self._has_required_scopes(self._auth.creds):
                return self._auth.creds

        # 2. Instance creds (passed directly or already resolved)
        if self.creds and self.creds.valid:
            if self._has_required_scopes(self.creds):
                return self.creds

        # 3. Service account (never stored in DB)
        service_account_path = self._get_service_account_path()
        if service_account_path:
            creds = self._get_service_account_creds(service_account_path)
            if self._auth:
                self._auth.creds = creds
            return creds

        # Use aggregated scopes from GoogleAuth if available
        oauth_scopes = self._auth.scopes
        db = self._auth.db

        # 4. DB lookup (if configured via auth.db)
        if db:
            from agno.tools.google.auth.tokens import load_token_from_db, save_token_to_db

            row, creds = load_token_from_db(db, self._auth.token_encryption_key)
            if row and creds:
                # Scope check
                granted = set(row.get("granted_scopes") or [])
                if not self.scopes or set(self.scopes).issubset(granted):
                    # Refresh if expired
                    if creds.expired and creds.refresh_token:
                        try:
                            creds.refresh(self._make_auth_request())
                            saved = save_token_to_db(
                                db,
                                creds,
                                list(creds.granted_scopes or creds.scopes),
                                self._auth.token_encryption_key,
                                self._auth.encrypt_tokens,
                            )
                            if not saved:
                                log_warning(
                                    f"{self.google_service_name.title()} token not persisted to DB. "
                                    "Check GOOGLE_TOKEN_ENCRYPTION_KEY or set encrypt_tokens=False."
                                )
                        except Exception as e:
                            log_warning(
                                f"{self.google_service_name.title()} token refresh failed: {e}. "
                                "Falling back to re-authentication."
                            )
                            creds = None
                    if creds and creds.valid:
                        if self._auth:
                            self._auth.creds = creds
                        return creds
                else:
                    missing = set(self.scopes) - granted
                    log_warning(
                        f"{self.google_service_name.title()} DB token missing scopes: {', '.join(missing)}. "
                        "Re-authenticating with broader scopes."
                    )

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
                creds.refresh(self._make_auth_request())
            except Exception:
                creds = None
            # Save refreshed token — best effort, don't fail if file write fails
            if creds and creds.valid:
                try:
                    token_file.write_text(creds.to_json())
                except Exception:
                    log_debug(f"Failed to save refreshed {self.google_service_name} token to file")

        if creds and creds.valid:
            if self._has_required_scopes(creds):
                if self._auth:
                    self._auth.creds = creds
                return creds

        # 6. Interactive OAuth (local only) — uses AGGREGATED scopes
        client_id = self._auth.client_id
        client_secret = self._auth.client_secret

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "project_id": os.getenv("GOOGLE_PROJECT_ID"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost"],
            }
        }
        if creds_file.exists():
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), oauth_scopes)
        else:
            flow = InstalledAppFlow.from_client_config(client_config, oauth_scopes)

        oauth_kwargs: Dict[str, Any] = {
            "prompt": self._auth.prompt,
            "access_type": self._auth.access_type,
        }
        if self._auth.include_granted_scopes:
            oauth_kwargs["include_granted_scopes"] = "true"
        if self._auth.login_hint:
            oauth_kwargs["login_hint"] = self._auth.login_hint
        if self._auth.hosted_domain:
            oauth_kwargs["hd"] = self._auth.hosted_domain
        creds = flow.run_local_server(port=self.oauth_port or 0, **oauth_kwargs)

        # Save to DB or file, then cache on GoogleAuth
        if creds and creds.valid:
            if db:
                from agno.tools.google.auth.tokens import save_token_to_db

                saved = save_token_to_db(
                    db,
                    creds,
                    list(creds.granted_scopes or creds.scopes),
                    self._auth.token_encryption_key,
                    self._auth.encrypt_tokens,
                )
                if not saved:
                    log_warning(
                        f"{self.google_service_name.title()} token not persisted to DB. "
                        "Check GOOGLE_TOKEN_ENCRYPTION_KEY or set encrypt_tokens=False."
                    )
            else:
                token_file.write_text(creds.to_json())
                log_debug(f"{self.google_service_name.title()} credentials saved to file")
            if self._auth:
                self._auth.creds = creds

        return creds
