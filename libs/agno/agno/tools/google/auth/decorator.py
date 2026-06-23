import json
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, Optional

from agno.utils.log import log_debug, log_error


@dataclass
class GoogleCallContext:
    """Per-call state for Google toolkit methods."""

    service: Any
    creds: Any
    user_id: Optional[str]


_google_context: ContextVar[Optional[GoogleCallContext]] = ContextVar("google_context", default=None)


def get_current_service() -> Any:
    """Return the Google API service for the current call, or None if outside decorator."""
    ctx = _google_context.get()
    return ctx.service if ctx else None


def get_current_creds() -> Any:
    """Return the Google credentials for the current call, or None if outside decorator."""
    ctx = _google_context.get()
    return ctx.creds if ctx else None


def get_cache_key() -> Optional[str]:
    """Return a cache key for the current user, or None in single-user mode."""
    ctx = _google_context.get()
    return ctx.user_id if ctx else None


def _is_auth_error(e: Exception) -> bool:
    """Check if exception is an authentication error that needs re-auth."""
    if isinstance(e, PermissionError):
        return True
    try:
        from google.auth.exceptions import GoogleAuthError

        return isinstance(e, GoogleAuthError)
    except ImportError:
        return False


def google_authenticate(service_name: str):
    """Decorator that resolves credentials and builds a fresh service per-call.

    Methods using this decorator MUST have `agent` and `run_context` as their first
    two parameters after `self`, following the DaytonaTools/MemoryTools pattern:

        @google_authenticate("gmail")
        def get_latest_emails(self, agent: Agent, run_context: RunContext, count: int) -> str:

    The framework injects these params automatically (function.py:898-905) and they are
    excluded from the LLM tool schema (function.py:441-451).

    - agent: provides agent.db for token storage/lookup
    - run_context: provides user_id for per-user credential isolation

    When enable_multi_user_oauth=True and authentication fails, returns OAuth URL
    instead of plain error — allows interface to display login link.
    """
    from agno.run.base import RunContext

    def decorator(func):
        @wraps(func)
        def wrapper(self, agent: Optional[Any] = None, run_context: Optional[RunContext] = None, *args, **kwargs):
            try:
                creds = self._resolve_creds(run_context, agent=agent)
            except Exception as e:
                # Check if multi-user OAuth is enabled — if so, return OAuth URL
                auth_config = getattr(self, "_auth", None)
                if auth_config and auth_config.enable_multi_user_oauth and _is_auth_error(e):
                    log_debug(f"{service_name.title()} auth failed, generating OAuth URL: {e}")
                    from agno.tools.google.auth.oauth import oauth_google

                    return oauth_google(auth_config, run_context, agent)

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
                return func(self, agent, run_context, *args, **kwargs)
            finally:
                _google_context.reset(token)

        return wrapper

    return decorator
