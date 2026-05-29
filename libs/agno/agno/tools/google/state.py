import inspect
import json
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, Optional

from agno.utils.log import log_error


@dataclass
class GoogleCallContext:
    """Per-call state for Google toolkit methods."""

    service: Any
    creds: Any
    user_id: Optional[str]


_google_context: ContextVar[Optional[GoogleCallContext]] = ContextVar("google_context", default=None)


def get_current_service() -> Any:
    """Get the Google API service for the current call.

    Used by toolkit methods to access the per-call service built by @google_authenticate.
    Returns None if called outside a decorated method.
    """
    ctx = _google_context.get()
    return ctx.service if ctx else None


def get_current_creds() -> Any:
    """Get the Google credentials for the current call.

    Used by toolkit methods that need to build additional services (e.g., Drive API
    for sheets duplication) with the same credentials resolved by @google_authenticate.
    Returns None if called outside a decorated method.
    """
    ctx = _google_context.get()
    return ctx.creds if ctx else None


def get_current_user_id() -> Optional[str]:
    """Get the user_id for the current call.

    Used by toolkit methods to key per-user caches (e.g., label cache in Gmail).
    Returns None if called outside a decorated method or in single-user mode.
    """
    ctx = _google_context.get()
    return ctx.user_id if ctx else None


def get_cache_key() -> Optional[str]:
    """Get a cache key for the current user. Returns None in single-user mode."""
    ctx = _google_context.get()
    return ctx.user_id if ctx else None


def google_authenticate(service_name: str):
    """Shared auth decorator for all Google toolkits.

    Each toolkit creates a module-level alias:
        authenticate = google_authenticate("gmail")

    Expects the toolkit class to define:
        - _resolve_creds(run_context, agent): Returns credentials (stateless)
        - _build_service(creds): Returns build(api_name, api_version, credentials=creds)

    The decorator resolves credentials and builds a fresh service per-call,
    passing both run_context and agent to the wrapped method for stateless access.
    """

    def decorator(func):
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        for name in ("run_context", "agent"):
            if name not in sig.parameters:
                params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=None))
        exposed_sig = sig.replace(parameters=params)

        @wraps(func)
        def wrapper(self, *args, run_context=None, agent=None, **kwargs):
            try:
                creds = self._resolve_creds(run_context, agent)
            except Exception as e:
                log_error(f"{service_name.title()} authentication failed: {str(e)}")
                return json.dumps({"error": f"{service_name.title()} authentication failed: {e}"})

            try:
                service = self._build_service(creds)
            except Exception as e:
                log_error(f"{service_name.title()} service initialization failed: {str(e)}")
                return json.dumps({"error": f"{service_name.title()} service initialization failed: {e}"})

            user_id = getattr(run_context, "user_id", None) if run_context else None
            ctx = GoogleCallContext(service=service, creds=creds, user_id=user_id)
            token = _google_context.set(ctx)
            try:
                return func(self, *args, **kwargs)
            finally:
                _google_context.reset(token)

        wrapper.__signature__ = exposed_sig  # type: ignore[attr-defined]
        return wrapper

    return decorator
