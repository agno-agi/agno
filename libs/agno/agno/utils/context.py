"""
Context utilities for request-scoped data injection.

This module provides context variables for passing request-scoped data
to agents and tools without threading issues. Context variables are
the thread-safe way to pass data through the call stack.

Issue #404 Fix: Provides session metadata injection for workspace isolation.
Middleware can set session_metadata_context with workspace_id, and agent
session creation will pick it up automatically.
"""

from contextvars import ContextVar
from typing import Any, Dict, Optional


# Context variable for session metadata injection
# Middleware can set this to inject metadata (like workspace_id) into sessions
# created during agent runs, ensuring proper tenant isolation.
_session_metadata_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    'session_metadata_context', default=None
)


def get_session_metadata_context() -> Optional[Dict[str, Any]]:
    """
    Get session metadata from context.

    Returns metadata dict that should be merged into newly created sessions.
    This is typically set by middleware to inject workspace_id for tenant isolation.

    Returns:
        Optional dict of metadata to inject into sessions, or None if not set.
    """
    return _session_metadata_context.get()


def set_session_metadata_context(metadata: Optional[Dict[str, Any]]) -> None:
    """
    Set session metadata context.

    Call this in middleware to inject metadata into sessions created
    during the request. The metadata will be merged into session.metadata
    when new sessions are created by agent._read_or_create_session().

    Args:
        metadata: Dict of metadata to inject, or None to clear.
                  Typically contains {"workspace_id": "..."} for tenant isolation.
    """
    _session_metadata_context.set(metadata)


def clear_session_metadata_context() -> None:
    """Clear the session metadata context."""
    _session_metadata_context.set(None)
