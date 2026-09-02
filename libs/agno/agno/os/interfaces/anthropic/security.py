"""API key authentication for the Anthropic Messages API interface."""

from __future__ import annotations

from os import getenv
from typing import Optional

from fastapi import HTTPException, Request, status

from agno.os.interfaces.anthropic.helpers import error_response

API_KEY_ENV_VAR = "AGNO_ANTHROPIC_INTERFACE_API_KEY"


def resolve_api_key(configured_key: Optional[str]) -> Optional[str]:
    """Return the constructor-provided key, falling back to the env var."""
    return configured_key or getenv(API_KEY_ENV_VAR)


def extract_request_key(request: Request) -> Optional[str]:
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return auth


def verify_api_key(request: Request, expected_key: Optional[str]) -> None:
    """Validate the request's API key against the configured key.

    If `expected_key` is None, auth is disabled (development mode).
    """
    if not expected_key:
        return
    provided = extract_request_key(request)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_response("authentication_error", "Missing API key."),
        )
    if provided != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_response("authentication_error", "Invalid API key."),
        )
