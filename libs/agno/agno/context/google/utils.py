"""Shared utilities for Google context providers (Gmail, Calendar, GDrive)."""

from __future__ import annotations

from pathlib import Path

from agno.context.provider import Status


def validate_google_credentials(
    *,
    provider_id: str,
    sa_path: str | None,
    token_path: str | None,
    delegated_user: str | None = None,
) -> Status:
    """Validate Google credentials and return provider status.

    Service account mode: loads and validates the SA JSON file.
    OAuth mode: loads and validates the cached token file.
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

    # OAuth mode
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
