"""HTTP management API for :class:`ManagedRoleStore` — the governance product surface.

Admin-only REST API to create roles, set their permissions (in agno scope terms,
with allow/deny), and grant or revoke them at runtime. Mount it on your AgentOS:

    from agno.os.authz.role_store import ManagedRoleStore
    from agno.os.authz.role_router import get_roles_router

    roles = ManagedRoleStore(db_url="postgresql+psycopg://...")
    app = agent_os.get_app()
    app.include_router(get_roles_router(roles))

Response shapes mirror the agno cloud RBAC API so a frontend can reuse its
integration: roles are objects (slug/name/description/is_default/created_at/
updated_at + parsed scopes), scopes are ``{raw, namespace, sub_namespace,
permission, value}``, and list endpoints use the SDK ``PaginatedResponse``
({data, meta}). Single-OS: scopes are a flat list (no org/os split).

Every route is admin-only — admin comes from an ``agent_os:admin`` token scope OR
an admin role in the store. Unauthenticated requests are rejected (401) by the JWT
middleware before these handlers; a valid-but-non-admin caller gets 403.

Endpoints (default prefix ``/authz``):
    GET    /authz/roles                          list roles (paginated)
    GET    /authz/roles/{slug}                   a role with its scopes
    PUT    /authz/roles/{slug}                   set scopes/metadata  {"scopes":[...]}
    DELETE /authz/roles/{slug}                   delete a role
    GET    /authz/users/{subject}/roles          a subject's roles
    POST   /authz/users/{subject}/roles          assign a role        {"role": "..."}
    DELETE /authz/users/{subject}/roles/{role}   revoke a role
"""

from typing import TYPE_CHECKING, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.os.scopes import AgentOSScope

if TYPE_CHECKING:
    from agno.os.authz.role_store import ManagedRoleStore
    from agno.os.authz.user_store import ManagedUserStore


# --------------------------------------------------------------------- schemas
def _parse_scope(raw: str) -> tuple:
    """Split a scope string into (namespace, sub_namespace, permission).

    ``agents:read`` -> ("agents", None, "read")
    ``agents:*:run`` -> ("agents", "*", "run")
    ``agent_os:admin`` -> ("agent_os", None, "admin")
    """
    parts = raw.split(":")
    if len(parts) == 2:
        return parts[0], None, parts[1]
    if len(parts) >= 3:
        return parts[0], ":".join(parts[1:-1]), parts[-1]
    return (parts[0] if parts else "unknown"), None, "unknown"


class RoleScopeSchema(BaseModel):
    """A single permission on a role, parsed and with its allow/deny effect."""

    id: Optional[str] = Field(None, description="Scope id (null — scopes aren't individually addressable here)")
    raw: str = Field(description="Original scope string, e.g. 'agents:*:read'")
    namespace: str = Field(description="Resource namespace, e.g. 'agents'")
    sub_namespace: Optional[str] = Field(None, description="Specific resource id or wildcard '*'")
    permission: str = Field(description="Action, e.g. 'read' / 'run' / 'write'")
    value: str = Field(description="'allow' or 'deny'")

    @classmethod
    def from_entry(cls, entry: dict) -> "RoleScopeSchema":
        ns, sub, perm = _parse_scope(entry["scope"])
        return cls(raw=entry["scope"], namespace=ns, sub_namespace=sub, permission=perm, value=entry.get("effect", "allow"))


class RoleSchema(BaseModel):
    """A role with its scopes — mirrors the cloud RoleWithScopes shape (flattened)."""

    slug: str = Field(description="Unique role id")
    name: str = Field(description="Human-readable display name")
    description: Optional[str] = Field(None, description="Role description")
    is_default: bool = Field(False, description="Whether this is a built-in default role")
    created_at: Optional[int] = Field(None, description="Created (epoch seconds)")
    updated_at: Optional[int] = Field(None, description="Last updated (epoch seconds)")
    scopes: List[RoleScopeSchema] = Field(default_factory=list, description="Permissions on this role")

    @classmethod
    def from_record(cls, rec: dict) -> "RoleSchema":
        return cls(
            slug=rec["slug"],
            name=rec.get("name") or rec["slug"],
            description=rec.get("description"),
            is_default=bool(rec.get("is_default", False)),
            created_at=rec.get("created_at") or None,
            updated_at=rec.get("updated_at") or None,
            scopes=[RoleScopeSchema.from_entry(e) for e in rec.get("scopes", [])],
        )


class AuthzUserSchema(BaseModel):
    """A directory user with roles merged in."""

    id: str = Field(description="User id (the JWT 'sub')")
    email: Optional[str] = None
    name: Optional[str] = None
    status: str = Field(description="'active' or 'disabled'")
    disabled: bool = False
    roles: List[str] = Field(default_factory=list, description="Roles assigned to this user")
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    @classmethod
    def from_user(cls, user: dict, roles: List[str]) -> "AuthzUserSchema":
        return cls(
            id=user["id"],
            email=user.get("email"),
            name=user.get("name"),
            status="disabled" if user.get("disabled") else "active",
            disabled=bool(user.get("disabled")),
            roles=roles,
            created_at=user.get("created_at"),
            updated_at=user.get("updated_at"),
        )


class AvailableScopeItem(BaseModel):
    """One scope the OS understands (catalog entry — no effect/id, just the shape)."""

    raw: str = Field(description="Scope string, e.g. 'agents:read'")
    namespace: str = Field(description="Resource namespace, e.g. 'agents'")
    sub_namespace: Optional[str] = Field(None, description="Sub-namespace if present")
    permission: str = Field(description="Action/permission, e.g. 'read'")

    @classmethod
    def from_raw(cls, raw: str) -> "AvailableScopeItem":
        ns, sub, perm = _parse_scope(raw)
        return cls(raw=raw, namespace=ns, sub_namespace=sub, permission=perm)


class ScopeItem(BaseModel):
    scope: str = Field(description="Scope string, e.g. 'agents:*:read'")
    effect: str = Field("allow", description="'allow' or 'deny'")


class SetRoleScopesRequest(BaseModel):
    scopes: List[Union[str, ScopeItem]] = Field(
        ..., description="Permissions: strings (allow) or {scope, effect} objects"
    )
    name: Optional[str] = Field(None, description="Display name")
    description: Optional[str] = Field(None, description="Role description")
    is_default: Optional[bool] = Field(None, description="Mark as a default role")


class CreateRoleRequest(BaseModel):
    """Create a role — metadata only; scopes are managed via /roles/{slug}/scopes."""

    slug: str = Field(..., min_length=1, description="Unique role id")
    name: Optional[str] = Field(None, description="Display name (defaults to slug)")
    description: Optional[str] = Field(None, description="Role description")
    is_default: Optional[bool] = Field(None, description="Mark as a default role")


class UpdateRoleRequest(BaseModel):
    """Metadata-only update (PATCH) — does not touch scopes."""

    name: Optional[str] = Field(None, description="Display name")
    description: Optional[str] = Field(None, description="Role description")
    is_default: Optional[bool] = Field(None, description="Mark as a default role")


class ReplaceScopesRequest(BaseModel):
    """Full replace of a role's scopes (PUT /roles/{slug}/scopes)."""

    scopes: List[Union[str, ScopeItem]] = Field(
        ..., description="Permissions: strings (allow) or {scope, effect} objects"
    )


class PatchScopesRequest(BaseModel):
    """Scope diff (PATCH /roles/{slug}/scopes): add/flip ``upsert``, drop ``remove``."""

    upsert: List[Union[str, ScopeItem]] = Field(default_factory=list, description="Scopes to add or flip")
    remove: List[Union[str, ScopeItem]] = Field(default_factory=list, description="Scopes to remove (effect ignored)")


class AssignRoleRequest(BaseModel):
    role: str = Field(..., description="Role to grant the subject")


class CreateUserRequest(BaseModel):
    id: str = Field(..., description="The user's id — must equal the JWT 'sub' your app mints for them")
    email: Optional[str] = Field(None, description="Optional email (label/audit only; not a credential)")
    name: Optional[str] = Field(None, description="Optional display name")


class UpdateUserRequest(BaseModel):
    email: Optional[str] = Field(None, description="New email")
    name: Optional[str] = Field(None, description="New display name")


def _page(items: list, page: int, limit: int) -> PaginatedResponse:
    """Wrap a fully-materialised list in the SDK's PaginatedResponse ({data, meta})."""
    total = len(items)
    start = max(page - 1, 0) * limit
    return PaginatedResponse(
        data=items[start : start + limit],
        meta=PaginationInfo(
            page=page,
            limit=limit,
            total_count=total,
            total_pages=(total + limit - 1) // limit if limit > 0 else 0,
        ),
    )


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
        admin_scope = getattr(request.state, "admin_scope", None) or AgentOSScope.ADMIN.value
        if admin_scope in token_scopes or store.can_manage(principal_id, claims):
            return principal_id or ""
        raise HTTPException(status_code=403, detail="Admin privileges required to manage roles")

    router = APIRouter(prefix=prefix, tags=tags, dependencies=[Depends(require_admin)])

    def _role_or_404(slug: str) -> dict:
        rec = store.get_role(slug)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Role {slug!r} not found")
        return rec

    # ---- roles ----------------------------------------------------------
    @router.get("/roles", response_model=PaginatedResponse[RoleSchema])
    def list_roles(
        limit: int = Query(default=20, ge=1, description="Items per page"),
        page: int = Query(default=1, ge=0, description="Page number"),
    ):
        roles = [RoleSchema.from_record(r) for r in store.list_roles_detailed()]
        return _page(roles, page, limit)

    @router.post("/roles", response_model=RoleSchema, status_code=201)
    def create_role(body: CreateRoleRequest, actor: str = Depends(require_admin)):
        """Create a role (metadata only — RESTful). Add permissions afterwards via
        PUT/PATCH /roles/{slug}/scopes. Mirrors the cloud POST /roles."""
        try:
            store.create_role(
                body.slug, name=body.name, description=body.description, is_default=body.is_default, actor=actor
            )
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Role {body.slug!r} already exists")
        return RoleSchema.from_record(_role_or_404(body.slug))

    @router.get("/roles/{slug}", response_model=RoleSchema)
    def get_role(slug: str):
        return RoleSchema.from_record(_role_or_404(slug))

    @router.put("/roles/{slug}", response_model=RoleSchema)
    def set_role(slug: str, body: SetRoleScopesRequest, actor: str = Depends(require_admin)):
        scopes = [s if isinstance(s, str) else {"scope": s.scope, "effect": s.effect} for s in body.scopes]
        try:
            store.set_role_scopes(
                slug, scopes, actor=actor, name=body.name, description=body.description, is_default=body.is_default
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return RoleSchema.from_record(_role_or_404(slug))

    @router.patch("/roles/{slug}", response_model=RoleSchema)
    def update_role(slug: str, body: UpdateRoleRequest, actor: str = Depends(require_admin)):
        """Update a role's metadata only (name/description/is_default) — scopes
        untouched. Mirrors the cloud PATCH /roles/{slug}."""
        try:
            store.set_role_meta(
                slug, name=body.name, description=body.description, is_default=body.is_default, actor=actor
            )
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Role {slug!r} not found")
        return RoleSchema.from_record(_role_or_404(slug))

    @router.delete("/roles/{slug}")
    def delete_role(slug: str, actor: str = Depends(require_admin)) -> dict:
        store.remove_role(slug, actor=actor)
        return {"slug": slug, "deleted": True}

    # ---- role scopes (subresource) -------------------------------------
    def _to_store_scopes(items):
        return [s if isinstance(s, str) else {"scope": s.scope, "effect": s.effect} for s in items]

    @router.put("/roles/{slug}/scopes", response_model=List[RoleScopeSchema])
    def replace_role_scopes(slug: str, body: ReplaceScopesRequest, actor: str = Depends(require_admin)):
        """Replace ALL of a role's scopes (metadata preserved). Mirrors the cloud
        PUT /roles/{slug}/scopes; returns the resulting scope list."""
        _role_or_404(slug)
        try:
            store.set_role_scopes(slug, _to_store_scopes(body.scopes), actor=actor)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return [RoleScopeSchema.from_entry(e) for e in store.get_role_scope_entries(slug)]

    @router.patch("/roles/{slug}/scopes", response_model=RoleSchema)
    def patch_role_scopes(slug: str, body: PatchScopesRequest, actor: str = Depends(require_admin)):
        """Apply a scope diff: add/flip ``upsert``, drop ``remove`` (everything else
        kept). Mirrors the cloud PATCH /roles/{slug}/scopes; returns the full role."""
        _role_or_404(slug)
        try:
            store.patch_role_scopes(
                slug, upsert=_to_store_scopes(body.upsert), remove=_to_store_scopes(body.remove), actor=actor
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return RoleSchema.from_record(_role_or_404(slug))

    # ---- scope catalog --------------------------------------------------
    @router.get("/scopes", response_model=List[AvailableScopeItem], response_model_exclude_none=True)
    def list_scopes() -> List[AvailableScopeItem]:
        """All scopes this AgentOS understands, as a flat list.

        Derived from the OS's own route→scope map (so it always matches what the OS
        actually enforces) plus the ``agent_os:admin`` super-scope. Each item is
        parsed into ``{raw, namespace, sub_namespace, permission}`` for a UI to
        render a resource×action grid. (Single OS: no org-level scopes.)
        """
        from agno.os.scopes import get_default_scope_mappings

        raws = {scope for required in get_default_scope_mappings().values() for scope in required}
        raws.add("agent_os:admin")
        return [AvailableScopeItem.from_raw(r) for r in sorted(raws)]

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

        def _user(user: dict) -> AuthzUserSchema:
            return AuthzUserSchema.from_user(user, store.roles_of(user["id"]))

        @router.get("/users", response_model=PaginatedResponse[AuthzUserSchema])
        def list_users(
            include_disabled: bool = True,
            limit: int = Query(default=20, ge=1, description="Items per page"),
            page: int = Query(default=1, ge=0, description="Page number"),
        ):
            users = [_user(u) for u in user_store.list(limit=100000, include_disabled=include_disabled)]
            return _page(users, page, limit)

        @router.post("/users", response_model=AuthzUserSchema)
        def create_user(body: CreateUserRequest, actor: str = Depends(require_admin)):
            return _user(user_store.upsert(body.id, email=body.email, name=body.name, actor=actor))

        @router.get("/users/{user_id}", response_model=AuthzUserSchema)
        def get_user(user_id: str):
            user = user_store.get(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail=f"User {user_id!r} not found")
            return _user(user)

        @router.patch("/users/{user_id}", response_model=AuthzUserSchema)
        def update_user(user_id: str, body: UpdateUserRequest, actor: str = Depends(require_admin)):
            return _user(user_store.upsert(user_id, email=body.email, name=body.name, actor=actor))

        @router.delete("/users/{user_id}")
        def delete_user(user_id: str, actor: str = Depends(require_admin)) -> dict:
            deleted = user_store.remove(user_id, actor=actor)
            return {"id": user_id, "deleted": deleted}

        @router.post("/users/{user_id}/disable", response_model=AuthzUserSchema)
        def disable_user(user_id: str, actor: str = Depends(require_admin)):
            """Revoke a user: they are denied at the enforcement point on their next
            request, even with a still-valid token."""
            return _user(user_store.set_disabled(user_id, True, actor=actor))

        @router.post("/users/{user_id}/enable", response_model=AuthzUserSchema)
        def enable_user(user_id: str, actor: str = Depends(require_admin)):
            return _user(user_store.set_disabled(user_id, False, actor=actor))

    return router
