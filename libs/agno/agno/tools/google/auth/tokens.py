import json
from typing import Any, Dict, List, Optional

from agno.utils.log import log_debug, log_error, log_warning


def valid_auth_token_db(db: Any) -> Any:
    """Return db if it supports sync auth token CRUD, else None."""
    if db is None:
        return None

    from agno.db.base import AsyncBaseDb, BaseDb

    if isinstance(db, AsyncBaseDb):
        log_warning(
            "Async database detected but Google OAuth requires sync DB for token storage. "
            "Token persistence will be disabled. Use a sync DB (e.g., SqliteDb, PgDb) for multi-user OAuth."
        )
        return None

    if isinstance(db, BaseDb) and type(db).get_auth_token is not BaseDb.get_auth_token:
        return db
    return None


def get_token_db(toolkit: Any, agent: Optional[Any] = None) -> Any:
    """Resolve the DB for token storage, or None if not configured."""
    ga = getattr(toolkit, "auth_config", None)
    manager_wants_db = ga is not None and getattr(ga, "_store_tokens", False)
    toolkit_wants_db = getattr(toolkit, "store_token_in_db", False)

    if not manager_wants_db and not toolkit_wants_db:
        return None

    return valid_auth_token_db(getattr(agent, "db", None))


def persist_google_token(
    db: Any,
    creds: Any,
    user_id: Optional[str],
    services_registry: Optional[Dict[str, List[str]]] = None,
    auth_config: Optional[Any] = None,
) -> bool:
    """Upsert Google credentials to DB. Returns True on success."""
    if db is None:
        return False
    try:
        token_data: Dict[str, Any] = json.loads(creds.to_json())
        if services_registry:
            granted_scopes = sorted({s for scope_list in services_registry.values() for s in scope_list})
        else:
            granted_scopes = token_data.get("scopes", [])

        if auth_config and auth_config._encrypt_tokens:
            from agno.utils.encryption import encrypt_dict

            token_data = encrypt_dict(token_data, key=auth_config._token_encryption_key)

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


def load_token(
    toolkit: Any,
    scopes: list,
    user_id: Optional[str] = None,
    agent: Optional[Any] = None,
) -> bool:
    """Load credentials from DB, refresh if expired. Returns True on success."""
    db = get_token_db(toolkit, agent=agent)
    if db is None:
        return False
    try:
        row = db.get_auth_token("google", user_id, "google")
    except NotImplementedError:
        return False
    except Exception as e:
        log_debug(f"DB load failed for google: {e}")
        return False
    if not row:
        return False

    granted = set(row.get("granted_scopes") or [])
    required = set(scopes)
    if required and not required.issubset(granted):
        missing = required - granted
        raise PermissionError(
            f"Token missing required scopes: {', '.join(missing)}. Please re-authenticate to grant access."
        )

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        from agno.utils.encryption import decrypt_dict, is_encrypted

        token_data = row["token_data"]
        if is_encrypted(token_data):
            auth_config = getattr(toolkit, "auth_config", None)
            key = auth_config._token_encryption_key if auth_config else None
            token_data = decrypt_dict(token_data, key=key)

        effective_scopes = row.get("granted_scopes") or scopes
        creds = Credentials.from_authorized_user_info(token_data, effective_scopes)
    except (ValueError, KeyError, ImportError) as e:
        log_debug(f"Could not reconstruct google credentials: {e}")
        return False

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(toolkit, creds, user_id=user_id, agent=agent)
        except Exception as e:
            log_debug(f"Token refresh failed: {e}")
            return False

    if not creds.valid:
        return False

    toolkit.creds = creds
    return True


def save_token(
    toolkit: Any,
    creds: Any,
    user_id: Optional[str] = None,
    agent: Optional[Any] = None,
) -> bool:
    """Persist credentials to DB. Returns True on success."""
    auth_config = getattr(toolkit, "auth_config", None)
    return persist_google_token(
        db=get_token_db(toolkit, agent=agent),
        creds=creds,
        user_id=user_id,
        services_registry=auth_config._services if auth_config else None,
        auth_config=auth_config,
    )
