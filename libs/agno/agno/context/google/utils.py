"""Shared utilities for Google context providers (Gmail, Calendar, GDrive)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agno.context.provider import Status

if TYPE_CHECKING:
    from agno.tools.google.auth import AuthConfig


def validate_google_credentials(
    *,
    provider_id: str,
    sa_path: str | None,
    token_path: str | None,
    delegated_user: str | None = None,
    auth: "AuthConfig | None" = None,
    required_scopes: list[str] | None = None,
) -> Status:
    """Validate Google credentials and return provider status.

    Service account mode: loads and validates the SA JSON file.
    OAuth mode: checks DB first (if auth.db set), then falls back to token file.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    except ImportError:
        return Status(ok=False, detail="google-auth not installed")

    if sa_path:
        if not Path(sa_path).exists():
            return Status(ok=False, detail=f"service account file not found: {sa_path}")
        try:
            creds = ServiceAccountCredentials.from_service_account_file(sa_path)
            if delegated_user:
                creds = creds.with_subject(delegated_user)
            return Status(ok=True, detail=f"{provider_id} (service_account, {creds.service_account_email})")
        except Exception as e:
            return Status(ok=False, detail=f"invalid service account file: {e}")

    # OAuth mode - check DB first, then file
    # 1. Check DB (if auth.db is configured)
    if auth and auth.db:
        status = _check_db_token(provider_id, auth, required_scopes)
        if status:
            return status

    # 2. Fall back to file
    token_file = Path(token_path) if token_path else None
    if token_file and token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file))
            if creds.valid:
                return Status(ok=True, detail=f"{provider_id} (oauth, valid)")
            if creds.expired and creds.refresh_token:
                return Status(ok=True, detail=f"{provider_id} (oauth, expired but refreshable)")
            return Status(ok=False, detail=f"{provider_id} (oauth, token invalid or missing refresh_token)")
        except Exception as e:
            return Status(ok=False, detail=f"invalid token file: {e}")

    return Status(ok=False, detail=f"{provider_id} (oauth, not authenticated)")


def _check_db_token(
    provider_id: str,
    auth: "AuthConfig",
    required_scopes: list[str] | None = None,
) -> Status | None:
    """Check for valid token in DB. Returns Status if found, None to fall back to file."""
    from agno.tools.google.auth.tokens import load_token_from_db

    row, creds = load_token_from_db(auth.db, auth.token_encryption_key)
    if not row or not creds:
        return None

    # Check if granted scopes cover required scopes
    if required_scopes:
        granted = set(row.get("granted_scopes") or [])
        if not set(required_scopes).issubset(granted):
            missing = set(required_scopes) - granted
            return Status(ok=False, detail=f"{provider_id} (oauth/db, missing scopes: {', '.join(missing)})")

    if creds.valid:
        return Status(ok=True, detail=f"{provider_id} (oauth/db, valid)")
    if creds.expired and creds.refresh_token:
        return Status(ok=True, detail=f"{provider_id} (oauth/db, expired but refreshable)")
    return Status(ok=False, detail=f"{provider_id} (oauth/db, token invalid)")
