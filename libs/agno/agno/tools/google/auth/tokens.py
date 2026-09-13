from __future__ import annotations

from typing import Any, Optional, Tuple

from agno.utils.log import log_debug, log_warning


def load_token_from_db(
    db: Any,
    encryption_key: Optional[str],
) -> Tuple[Optional[dict], Any]:
    """Load Google OAuth token from DB and build Credentials.

    Returns:
        (row, creds): row dict for scope checking, Credentials object for use.
        (None, None): if not found or decryption/parse fails.
    """
    from google.oauth2.credentials import Credentials

    from agno.utils.encryption import decrypt_dict, is_encrypted

    try:
        row = db.get_auth_token("google", None, "google")
    except NotImplementedError:
        log_warning("Database does not support auth token storage")
        return None, None
    except Exception as e:
        log_debug(f"Could not load token from DB: {e}")
        return None, None

    if not row:
        return None, None

    token_data = row.get("token_data")
    if not token_data:
        return None, None

    try:
        if is_encrypted(token_data):
            token_data = decrypt_dict(token_data, key=encryption_key)
        elif encryption_key:
            log_warning(
                "Loaded unencrypted token (stored before encryption was enabled). "
                "Token will be re-encrypted on next refresh."
            )
        granted = row.get("granted_scopes") or []
        creds = Credentials.from_authorized_user_info(token_data, granted)

        # from_authorized_user_info sets creds.scopes but not creds.granted_scopes
        if granted:
            creds._granted_scopes = granted

        return row, creds
    except ValueError as e:
        log_debug(f"Could not decrypt token from DB: {e}")
        return None, None
    except (KeyError, ImportError) as e:
        log_debug(f"Could not parse token from DB: {e}")
        return None, None


def save_token_to_db(
    db: Any,
    creds: Any,
    granted_scopes: list[str],
    encryption_key: Optional[str],
    encrypt_tokens: bool = True,
) -> bool:
    """Save Google OAuth credentials to DB."""
    from agno.utils.encryption import encrypt_dict

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
    }
    if creds.expiry:
        token_data["expiry"] = creds.expiry.isoformat() + "Z"

    if encrypt_tokens:
        if not encryption_key:
            log_warning(
                "Token encryption required but no key configured. Token NOT saved. "
                "Set GOOGLE_TOKEN_ENCRYPTION_KEY env var, or pass encrypt_tokens=False for local dev."
            )
            return False
        token_data = encrypt_dict(token_data, key=encryption_key)
    else:
        log_warning("Saving Google token WITHOUT encryption (encrypt_tokens=False).")

    try:
        result = db.upsert_auth_token(
            {
                "provider": "google",
                "user_id": None,
                "service": "google",
                "token_data": token_data,
                "granted_scopes": granted_scopes,
            }
        )
        if result is None:
            return False
        return True
    except Exception as e:
        log_debug(f"Could not save token to DB: {e}")
        return False


def delete_token_from_db(db: Any) -> bool:
    """Delete Google OAuth token from DB.

    Use when revoking access. Token rotation happens
    automatically during refresh — this is for explicit revocation only.
    """
    try:
        return db.delete_auth_token("google", None, "google")
    except NotImplementedError:
        log_warning("Database does not support auth token deletion")
        return False
    except Exception as e:
        log_debug(f"Could not delete token from DB: {e}")
        return False
