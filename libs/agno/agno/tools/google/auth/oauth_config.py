from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.tools.google.auth.credentials import GoogleAuth


class OAuthConfig:
    """OAuth configuration for Google toolkits.

    Configures multi-user token storage, encryption, scope registry, and router creation.
    Pass as `oauth_config=` to GoogleAuth.
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

    def create_router(self, config: "GoogleAuth"):
        """Create FastAPI router for OAuth callback."""
        from agno.tools.google.auth.callback import create_oauth_router

        return create_oauth_router(config)

    def persist_token(
        self,
        creds: Any,
        user_id: Optional[str],
    ) -> bool:
        """Upsert Google credentials to DB. Returns True on success."""
        import json

        from agno.utils.log import log_debug, log_error

        if self._db is None:
            return False
        try:
            token_data: Dict[str, Any] = json.loads(creds.to_json())
            if self._services:
                granted_scopes = sorted({s for scope_list in self._services.values() for s in scope_list})
            else:
                granted_scopes = token_data.get("scopes", [])

            if self._encrypt_tokens:
                from agno.utils.encryption import encrypt_dict

                token_data = encrypt_dict(token_data, key=self._token_encryption_key)

            self._db.upsert_auth_token(
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

    async def apersist_token(
        self,
        creds: Any,
        user_id: Optional[str],
    ) -> bool:
        """Async variant of persist_token."""
        import json

        from agno.utils.log import log_debug, log_error

        if self._db is None:
            return False
        try:
            token_data: Dict[str, Any] = json.loads(creds.to_json())
            if self._services:
                granted_scopes = sorted({s for scope_list in self._services.values() for s in scope_list})
            else:
                granted_scopes = token_data.get("scopes", [])

            if self._encrypt_tokens:
                from agno.utils.encryption import encrypt_dict

                token_data = encrypt_dict(token_data, key=self._token_encryption_key)

            await self._db.upsert_auth_token(
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
