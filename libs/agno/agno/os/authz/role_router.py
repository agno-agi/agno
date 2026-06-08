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

from typing import TYPE_CHECKING, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agno.os.authz.role_store import ManagedRoleStore
    from agno.os.authz.user_store import ManagedUserStore


class SetRoleScopesRequest(BaseModel):
    scopes: List[str] = Field(..., description="Permissions in agno scope terms, e.g. ['agents:*:read']")


class AssignRoleRequest(BaseModel):
    role: str = Field(..., description="Role to grant the subject")


class CreateUserRequest(BaseModel):
    id: str = Field(..., description="The user's id — must equal the JWT 'sub' your app mints for them")
    email: Optional[str] = Field(None, description="Optional email (label/audit only; not a credential)")
    name: Optional[str] = Field(None, description="Optional display name")


class UpdateUserRequest(BaseModel):
    email: Optional[str] = Field(None, description="New email")
    name: Optional[str] = Field(None, description="New display name")


def get_roles_router(
    store: "ManagedRoleStore",
    prefix: str = "/authz",
    tags: List[str] = ["Authorization"],
    user_store: "Optional[ManagedUserStore]" = None,
) -> APIRouter:
    """Build the admin-only roles-management router bound to ``store``.

    Pass ``user_store`` to also expose the credential-less user directory
    (``/authz/users``) for the no-IdP case: list/create/update/remove users and
    disable (revoke) them. User views merge in each user's roles from ``store``.
    """

    def require_admin(request: Request) -> str:
        """Gate: caller must be authenticated and an admin.

        Admin can come from two planes (so both run in parallel on one OS):
          - the OS-local store (``store.can_manage`` — the end-user/managed plane), or
          - the token's own scopes carrying the admin scope (the operator plane,
            e.g. an agno-cloud-minted token for someone who administers this OS).
        """
        if not getattr(request.state, "authenticated", False):
            raise HTTPException(status_code=401, detail="Not authenticated")
        principal_id = getattr(request.state, "user_id", None)
        claims = getattr(request.state, "claims", {}) or {}
        token_scopes = getattr(request.state, "scopes", []) or []
        admin_scope = getattr(request.state, "admin_scope", None) or "agent_os:admin"
        if admin_scope in token_scopes or store.can_manage(principal_id, claims):
            return principal_id or ""
        raise HTTPException(status_code=403, detail="Admin privileges required to manage roles")

    router = APIRouter(prefix=prefix, tags=tags, dependencies=[Depends(require_admin)])

    # ---- roles ----------------------------------------------------------
    @router.get("/roles")
    def list_roles() -> dict:
        return {"roles": store.list_roles()}

    @router.get("/roles/{role}")
    def get_role(role: str) -> dict:
        return {"role": role, "scopes": store.get_role_scopes(role)}

    @router.put("/roles/{role}")
    def set_role(role: str, body: SetRoleScopesRequest, actor: str = Depends(require_admin)) -> dict:
        try:
            store.set_role_scopes(role, body.scopes, actor=actor)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"role": role, "scopes": store.get_role_scopes(role)}

    @router.delete("/roles/{role}")
    def delete_role(role: str, actor: str = Depends(require_admin)) -> dict:
        store.remove_role(role, actor=actor)
        return {"role": role, "deleted": True}

    # ---- scope catalog --------------------------------------------------
    @router.get("/scopes")
    def list_scopes() -> dict:
        """The catalog of scopes this AgentOS understands, grouped by resource.

        Derived from the OS's own route→scope map, so it always matches what the
        OS actually enforces. A UI renders this as a resource×action grid; a role
        is then just a set of the resulting ``resource:action`` strings (plus the
        ``agent_os:admin`` super-scope).
        """
        from agno.os.scopes import get_default_scope_mappings

        grouped: dict = {}
        for required in get_default_scope_mappings().values():
            for scope in required:
                parts = scope.split(":")
                if len(parts) == 2:
                    grouped.setdefault(parts[0], set()).add(parts[1])
        grouped_sorted = {r: sorted(a) for r, a in sorted(grouped.items())}
        flat = sorted(f"{r}:{a}" for r, acts in grouped_sorted.items() for a in acts)
        return {"grouped": grouped_sorted, "scopes": flat, "admin_scope": "agent_os:admin"}

    # ---- audit ----------------------------------------------------------
    @router.get("/audit")
    def list_audit(limit: int = 100) -> dict:
        """Recent *change* events (role/assignment mutations, newest first). Empty
        unless the store was given a readable audit sink (e.g. DbAuditSink)."""
        return {"events": store.audit_log(limit)}

    @router.get("/decisions")
    def list_decisions(request: Request, limit: int = 100) -> dict:
        """Recent *decision* events (allow/deny per request, newest first).

        Decision audit is configured on ``AuthorizationConfig(audit=...)`` and lands
        on ``app.state.authz_audit`` — a separate table from the change trail above,
        so a high-volume decision log never buries the change history. Empty unless a
        readable decision sink (e.g. DbAuditSink) is configured."""
        sink = getattr(request.app.state, "authz_audit", None)
        events = sink.read_decisions(limit) if sink is not None and hasattr(sink, "read_decisions") else []
        return {"events": events}

    # ---- assignments ----------------------------------------------------
    @router.get("/users/{subject}/roles")
    def get_user_roles(subject: str) -> dict:
        return {"subject": subject, "roles": store.roles_of(subject)}

    @router.post("/users/{subject}/roles")
    def assign_role(subject: str, body: AssignRoleRequest, actor: str = Depends(require_admin)) -> dict:
        store.assign(subject, body.role, actor=actor)
        return {"subject": subject, "roles": store.roles_of(subject)}

    @router.delete("/users/{subject}/roles/{role}")
    def revoke_role(subject: str, role: str, actor: str = Depends(require_admin)) -> dict:
        store.unassign(subject, role, actor=actor)
        return {"subject": subject, "roles": store.roles_of(subject)}

    # ---- user directory (no-IdP) ---------------------------------------
    # Only mounted when a user_store is supplied. Identity is still asserted by
    # the app's JWT; this is a directory + revocation switch, never credentials.
    if user_store is not None:

        def _with_roles(user: dict) -> dict:
            return {**user, "roles": store.roles_of(user["id"])}

        @router.get("/users")
        def list_users(include_disabled: bool = True, limit: int = 1000) -> dict:
            """All users in the directory (newest first), each with their roles."""
            return {"users": [_with_roles(u) for u in user_store.list(limit=limit, include_disabled=include_disabled)]}

        @router.post("/users")
        def create_user(body: CreateUserRequest, actor: str = Depends(require_admin)) -> dict:
            user = user_store.upsert(body.id, email=body.email, name=body.name, actor=actor)
            return _with_roles(user)

        @router.get("/users/{user_id}")
        def get_user(user_id: str) -> dict:
            user = user_store.get(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail=f"User {user_id!r} not found")
            return _with_roles(user)

        @router.patch("/users/{user_id}")
        def update_user(user_id: str, body: UpdateUserRequest, actor: str = Depends(require_admin)) -> dict:
            user = user_store.upsert(user_id, email=body.email, name=body.name, actor=actor)
            return _with_roles(user)

        @router.delete("/users/{user_id}")
        def delete_user(user_id: str, actor: str = Depends(require_admin)) -> dict:
            deleted = user_store.remove(user_id, actor=actor)
            return {"id": user_id, "deleted": deleted}

        @router.post("/users/{user_id}/disable")
        def disable_user(user_id: str, actor: str = Depends(require_admin)) -> dict:
            """Revoke a user: they are denied at the enforcement point on their next
            request, even with a still-valid token."""
            return _with_roles(user_store.set_disabled(user_id, True, actor=actor))

        @router.post("/users/{user_id}/enable")
        def enable_user(user_id: str, actor: str = Depends(require_admin)) -> dict:
            return _with_roles(user_store.set_disabled(user_id, False, actor=actor))

    return router
