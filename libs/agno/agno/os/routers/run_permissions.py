"""Shared async permission checks for scheduled and accepted run targets."""

import posixpath
from typing import Literal
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException, Request

from agno.db.schemas.scheduler import RUN_ENDPOINT_RE
from agno.os.scopes import AgentOSScope, has_required_scopes
from agno.registry._reserved import RESERVED_MEMBER_IDS


async def _require_endpoint_permission(
    request: Request, endpoint: str, method: str, *, action: Literal["schedule", "accept"] = "schedule"
) -> None:
    """Require the caller's run permission before scheduling or accepting work."""
    from agno.os.auth import build_insufficient_permissions_detail, caller_scopes_are_authoritative

    path = posixpath.normpath(unquote(urlsplit(endpoint).path))
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in ("agents", "teams", "workflows") and parts[1] in RESERVED_MEMBER_IDS:
        detail = (
            "Manager specialists are internal. Select a registered agent, team or workflow as the Task executor."
            if action == "accept"
            else "Manager specialists are internal. Schedule OS Manager instead."
        )
        raise HTTPException(status_code=409, detail=detail)

    if not getattr(request.state, "authorization_enabled", False):
        return

    caller_scopes = getattr(request.state, "scopes", [])
    admin_scope_raw = getattr(request.state, "admin_scope", None) or getattr(request.app.state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None

    match = RUN_ENDPOINT_RE.match(endpoint) if method.upper() == "POST" else None

    if not caller_scopes_are_authoritative(request):
        # The token's scopes are NOT the authority here (a managed-roles/ReBAC/custom
        # plane governs access, and ignores them). Decide the target the same way its
        # own route gate would -- through the configured provider -- so write permission
        # cannot target a component the caller may not run themselves.
        from agno.os.auth import resolve_authorization_provider
        from agno.os.authz.provider import AuthorizationContext

        if match is None:
            # A non-run target is admin-only; a managed/ReBAC plane exposes no generic
            # "is admin" question to pose here, so fail closed.
            raise HTTPException(
                status_code=403,
                detail=(
                    "Accepting a non-run endpoint requires a scope-based authorization plane"
                    if action == "accept"
                    else "Scheduling a non-run endpoint requires a scope-based authorization plane"
                ),
            )
        resource_type, resource_id = match.group(1), match.group(2)
        provider = resolve_authorization_provider(request)
        ctx = AuthorizationContext(
            principal_id=getattr(request.state, "user_id", None),
            scopes=list(caller_scopes),
            claims=getattr(request.state, "claims", None) or {},
            resource_type=resource_type,
            resource_id=resource_id,
            action="run",
            admin_scope=admin_scope,
        )
        if not await provider.acheck(ctx):
            raise HTTPException(status_code=403, detail=build_insufficient_permissions_detail([f"{resource_type}:run"]))
        return

    if match is None:
        admin = admin_scope or AgentOSScope.ADMIN.value
        if not has_required_scopes(list(caller_scopes), [admin], admin_scope=admin_scope):
            raise HTTPException(
                status_code=403, detail=f"Only admins can {action} an endpoint that is not a run endpoint"
            )
        return

    resource_type, resource_id = match.group(1), match.group(2)
    required_scope = f"{resource_type}:run"
    if not has_required_scopes(
        list(caller_scopes),
        [required_scope],
        resource_type=resource_type,
        resource_id=resource_id,
        admin_scope=admin_scope,
    ):
        raise HTTPException(status_code=403, detail=build_insufficient_permissions_detail([required_scope]))
