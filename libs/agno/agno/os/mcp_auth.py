"""Authorization helpers for AgentOS MCP tools."""

from __future__ import annotations

from typing import List, Optional

from starlette.requests import Request

from agno.os.auth import build_insufficient_permissions_detail
from agno.os.scopes import has_required_scopes


def _get_fastmcp_request() -> Optional[Request]:
    """Return the in-flight FastMCP HTTP request, when there is one."""
    try:
        from fastmcp.server.dependencies import get_http_request
    except ImportError:
        return None

    try:
        return get_http_request()
    except RuntimeError:
        return None


def require_mcp_scope(
    required_scopes: List[str],
    *,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    request: Optional[Request] = None,
) -> None:
    """Enforce AgentOS RBAC for an MCP tool call.

    FastMCP tools are invoked through a single HTTP route (``/mcp``), so the
    REST middleware cannot infer a per-tool scope from the URL. This helper
    applies the same scope matcher inside each built-in tool when an HTTP/JWT
    request context exists. Direct in-memory MCP tests and local programmatic
    calls keep the previous behavior because no request context is available.
    """
    request = request or _get_fastmcp_request()
    if request is None:
        return

    state = getattr(request, "state", None)
    if not getattr(state, "authorization_enabled", False):
        return

    scopes = getattr(state, "scopes", []) or []
    if isinstance(scopes, str):
        scopes = [scopes]

    admin_scope_raw = getattr(state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None

    if has_required_scopes(
        scopes,
        required_scopes,
        resource_type=resource_type,
        resource_id=resource_id,
        admin_scope=admin_scope,
    ):
        return

    raise PermissionError(build_insufficient_permissions_detail(required_scopes))
