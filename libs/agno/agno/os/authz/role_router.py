"""HTTP management API for :class:`ManagedRoleStore` — the governance product surface.

This is the productisation of the managed-roles tier: a small, admin-only REST
API to create roles, set their permissions (in agno scope terms), and grant or
revoke them at runtime. Mount it on your AgentOS app:

    from agno.os.authz.role_store import ManagedRoleStore
    from agno.os.authz.role_router import get_roles_router

    roles = ManagedRoleStore(db_url="postgresql+psycopg://...")
    app = agent_os.get_app()
    app.include_router(get_roles_router(roles))

Every route requires the caller to be an admin (satisfies ``agent_os:admin``,
whether that comes from a token scope or an admin role in the store). The JWT
middleware still runs first, so an unauthenticated request is rejected (401)
before these handlers; a valid-but-non-admin caller gets 403.

Endpoints (default prefix ``/authz``):
    GET    /authz/roles                          list roles
    GET    /authz/roles/{role}                   a role's scopes
    PUT    /authz/roles/{role}                   set a role's scopes  {"scopes": [...]}
    DELETE /authz/roles/{role}                   delete a role
    GET    /authz/users/{subject}/roles          a subject's roles
    POST   /authz/users/{subject}/roles          assign a role        {"role": "..."}
    DELETE /authz/users/{subject}/roles/{role}   revoke a role
"""

from typing import TYPE_CHECKING, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agno.os.authz.role_store import ManagedRoleStore


class SetRoleScopesRequest(BaseModel):
    scopes: List[str] = Field(..., description="Permissions in agno scope terms, e.g. ['agents:*:read']")


class AssignRoleRequest(BaseModel):
    role: str = Field(..., description="Role to grant the subject")


def get_roles_router(store: "ManagedRoleStore", prefix: str = "/authz", tags: List[str] = ["Authorization"]) -> APIRouter:
    """Build the admin-only roles-management router bound to ``store``."""

    def require_admin(request: Request) -> str:
        """Gate: caller must be authenticated and an admin of the store."""
        if not getattr(request.state, "authenticated", False):
            raise HTTPException(status_code=401, detail="Not authenticated")
        principal_id = getattr(request.state, "user_id", None)
        claims = getattr(request.state, "claims", {}) or {}
        if not store.can_manage(principal_id, claims):
            raise HTTPException(status_code=403, detail="Admin privileges required to manage roles")
        return principal_id or ""

    router = APIRouter(prefix=prefix, tags=tags, dependencies=[Depends(require_admin)])

    # ---- roles ----------------------------------------------------------
    @router.get("/roles")
    def list_roles() -> dict:
        return {"roles": store.list_roles()}

    @router.get("/roles/{role}")
    def get_role(role: str) -> dict:
        return {"role": role, "scopes": store.get_role_scopes(role)}

    @router.put("/roles/{role}")
    def set_role(role: str, body: SetRoleScopesRequest) -> dict:
        try:
            store.set_role_scopes(role, body.scopes)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"role": role, "scopes": store.get_role_scopes(role)}

    @router.delete("/roles/{role}")
    def delete_role(role: str) -> dict:
        store.remove_role(role)
        return {"role": role, "deleted": True}

    # ---- assignments ----------------------------------------------------
    @router.get("/users/{subject}/roles")
    def get_user_roles(subject: str) -> dict:
        return {"subject": subject, "roles": store.roles_of(subject)}

    @router.post("/users/{subject}/roles")
    def assign_role(subject: str, body: AssignRoleRequest) -> dict:
        store.assign(subject, body.role)
        return {"subject": subject, "roles": store.roles_of(subject)}

    @router.delete("/users/{subject}/roles/{role}")
    def revoke_role(subject: str, role: str) -> dict:
        store.unassign(subject, role)
        return {"subject": subject, "roles": store.roles_of(subject)}

    return router
