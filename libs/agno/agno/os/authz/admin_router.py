"""HTTP management API for managed roles and the user directory — the governance product surface.

Admin-only REST API to create roles, set their permissions (in agno scope terms,
with allow/deny), and grant or revoke them at runtime.

With ``AgentOS(authorization=Authorization(...))`` you do not mount this yourself: AgentOS
registers it at ``/authz`` whenever the object has a role store. The credential-less user
DIRECTORY (who the users are + the disabled kill-switch) is a PEER concern served by
:func:`get_users_router` at ``/users`` -- mounted from ``AgentOS(user_directory=...)``, not this
router.

    from agno.os import Authorization

    authz = Authorization(db_url="postgresql+psycopg://...", verification_keys=KEYS, audience=OS_ID)
    authz.define_role("admin", ["agent_os:admin"])
    agent_os = AgentOS(agents=[...], authorization=authz)
    app = agent_os.get_app()   # /authz is already served

It is registered alongside the other built-in routers, which is what keeps it ahead
of the MCP catch-all mount. That ordering matters: a router included AFTER
``get_app()`` sits behind that mount, where every call 404s.

That caveat still applies to the multi-plane setup, which composes providers instead
and so has no role store for AgentOS to find. Mount the routers yourself there, passing the
Authorization object and the UserDirectory:

    app.include_router(get_roles_router(authz))
    app.include_router(get_users_router(users, role_store=authz))  # the /users directory

Response shapes mirror the agno cloud RBAC API so a frontend can reuse its
integration: roles are objects (slug/name/description/is_default/created_at/
updated_at + parsed scopes), scopes are ``{raw, namespace, sub_namespace,
permission, value}``, and list endpoints use the SDK ``PaginatedResponse``
({data, meta}). Single-OS: scopes are a flat list (no org/os split).

Every route is admin-only — admin comes from an admin role in the store OR, when a
scope plane actually enforces on this OS, an ``agent_os:admin`` token scope. Under a
role-store-only (or ReBAC-only) deployment the token's scopes carry no authorization
weight anywhere else, so they are not trusted here either (see ``require_admin``).
Unauthenticated requests are rejected (401) by the JWT middleware before these
handlers; a valid-but-non-admin caller gets 403.

Roles admin API -- get_roles_router (default prefix ``/authz``):
    GET    /authz/roles                          list roles (paginated)
    POST   /authz/roles                          create a role (metadata only)
    GET    /authz/roles/{slug}                   a role with its scopes
    PATCH  /authz/roles/{slug}                   update metadata (name/description)
    DELETE /authz/roles/{slug}                   delete a role
    PUT    /authz/roles/{slug}/scopes            replace scopes
    PATCH  /authz/roles/{slug}/scopes            diff scopes (upsert/remove)
    GET    /authz/subjects/{subject}/roles       a subject's roles
    POST   /authz/subjects/{subject}/roles       assign a role        {"role": "..."}
    DELETE /authz/subjects/{subject}/roles/{role} revoke a role

User directory admin API -- get_users_router (default prefix ``/users``):
    GET    /users                                list users (paginated, roles merged in)
    POST   /users                                create a directory user
    GET    /users/{user_id}                      a user
    PATCH  /users/{user_id}                      update profile / disable (the kill-switch)
    DELETE /users/{user_id}                      remove a user (cascades role revocation)
    GET    /users/metrics                        directory size, users created per day, users per role
"""

import time
from datetime import date as date_type
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agno.os.authz._role_store import RoleChangeRefused
from agno.os.authz.audit import AUDIT_SORT_FIELDS, DEFAULT_AUDIT_SORT_FIELD
from agno.os.authz.user_directory import DEFAULT_USER_SORT_FIELD, USER_SORT_FIELDS
from agno.os.schema import PaginatedResponse, PaginationInfo, SortOrder
from agno.os.scopes import AgentOSScope

if TYPE_CHECKING:
    from agno.os.authz.authorization import Authorization
    from agno.os.authz.user_directory import UserDirectory


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
        return cls(
            raw=entry["scope"], namespace=ns, sub_namespace=sub, permission=perm, value=entry.get("effect", "allow")
        )


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


class UserSchema(BaseModel):
    """A directory user with their role merged in (one role per user)."""

    id: str = Field(description="User id (the JWT 'sub')")
    email: Optional[str] = None
    name: Optional[str] = None
    status: str = Field(description="'active' or 'disabled'")
    disabled: bool = False
    role_slug: Optional[str] = Field(None, description="The user's role slug (one role per user), or null")
    role_name: Optional[str] = Field(
        None,
        description=(
            "Display name of the user's role, so a directory view needs no second request to "
            "/authz/roles. Falls back to the slug when the role has no display name; null when the "
            "user has no role"
        ),
    )
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    @classmethod
    def from_user(cls, user: dict, role: Optional[str], role_name: Optional[str] = None) -> "UserSchema":
        return cls(
            id=user["id"],
            email=user.get("email"),
            name=user.get("name"),
            status="disabled" if user.get("disabled") else "active",
            disabled=bool(user.get("disabled")),
            role_slug=role,
            role_name=(role_name or role) if role is not None else None,
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
    disabled: Optional[bool] = Field(
        None, description="Set the revocation kill-switch: true denies the user on every request, false re-enables"
    )


class UsersCreatedOnDay(BaseModel):
    date: date_type = Field(..., description="UTC day")
    count: int = Field(..., description="Users created on that day", ge=0)


class UsersByRole(BaseModel):
    role_slug: str = Field(..., description="Role slug")
    role_name: str = Field(..., description="Role display name (the slug when the role has no display name)")
    count: int = Field(..., description="Users in the directory holding this role, disabled users included", ge=0)


class UserManagementMetrics(BaseModel):
    """The directory as it is now plus its registration history. Computed on read;
    there is no cache and no refresh step."""

    total: int = Field(..., description="Users in the directory, including disabled ones", ge=0)
    active: int = Field(..., description="Users not disabled", ge=0)
    disabled: int = Field(..., description="Users switched off by the disabled kill-switch", ge=0)
    without_role: Optional[int] = Field(
        None,
        description=(
            "Users with no role assigned in the role store (they rely on the default role, if any). "
            "Null when no role store is configured."
        ),
        ge=0,
    )
    created_per_day: List[UsersCreatedOnDay] = Field(
        ..., description="Users created per UTC day, oldest first; days with no registrations are omitted"
    )
    by_role: Optional[List[UsersByRole]] = Field(
        None, description="Users per role, sorted by role. Null when no role store is configured"
    )


def _paginated(data: list, page: int, limit: int, total: int, search_time_ms: float = 0) -> PaginatedResponse:
    """Wrap one already-paged slice in the SDK's PaginatedResponse ({data, meta})."""
    return PaginatedResponse(
        data=data,
        meta=PaginationInfo(
            page=page,
            limit=limit,
            total_count=total,
            total_pages=(total + limit - 1) // limit if limit > 0 else 0,
            search_time_ms=search_time_ms,
        ),
    )


def _page(items: list, page: int, limit: int) -> PaginatedResponse:
    """Paginate a fully-materialised list."""
    start = max(page - 1, 0) * limit
    return _paginated(items[start : start + limit], page, limit, len(items))


def _token_scopes_enforced(request: Request) -> bool:
    """True when a scope plane actually enforces on this OS -- i.e. the token's
    ``scopes`` claim carries authorization weight for resource access.

    Only then is an ``agent_os:admin`` token scope a valid admin path on the /authz
    gate. A managed-role (or ReBAC) provider used on its own never reads token scopes
    (see :mod:`agno.os.authz.provider`), so honouring them here would let any
    validly-signed token carrying ``agent_os:admin`` administer roles while being
    denied every actual resource. Shared with the other token-scope gates via
    :func:`agno.os.auth.token_scopes_are_authoritative`.
    """
    from agno.os.auth import token_scopes_are_authoritative

    return token_scopes_are_authoritative(request)


def _make_require_admin(role_store: "Optional[Authorization]" = None, *, auth_enabled: bool = True) -> Any:
    """Build the admin gate shared by the roles admin API and the user-directory API.

    Admin can come from two planes (both run in parallel on one OS):
      - the token's own scopes carrying the admin scope (the operator plane, e.g. an
        agno-cloud-minted token for someone who administers this OS), OR
      - when a role store is present, an admin role in it (``can_manage`` — the managed
        plane). A directory running on plain scope RBAC has no role store, so admin is
        the token scope alone.

    The token-scope path is honoured ONLY when a scope plane actually enforces on this OS
    (:func:`_token_scopes_enforced`). Under a role-store-only or ReBAC-only deployment the
    enforcement plane ignores the token's scopes for every resource, so trusting
    ``agent_os:admin`` here would let any validly-signed token carrying that scope
    administer despite being denied every resource -- a privilege escalation.
    """

    # Async, and the token plane is checked first: the managed plane is a DB read, and
    # the role store may be bound to an async database, which its sync methods refuse.
    async def require_admin(request: Request) -> str:
        if not auth_enabled and not getattr(request.state, "authenticated", False):
            # No auth middleware at mount time AND none ran for this request: the whole OS serves
            # anonymous callers, so the directory admin API is open too. The roster is already
            # writable by anyone (a run with a new user_id provisions a row) and the disabled switch
            # is advisory without a verified identity, so gating /users alone would be inconsistent.
            # Turn authorization on to make it a real boundary. The request-time half matters for a
            # JWTMiddleware added by hand after get_app(): the mount saw no auth, but the request
            # carries a verified identity, so it is gated like any other. The actor recorded on the
            # open path is whatever user_id the request asserts.
            return getattr(request.state, "user_id", None) or ""
        if not getattr(request.state, "authenticated", False):
            raise HTTPException(status_code=401, detail="Not authenticated")
        if getattr(request.state, "security_key_verified", False):
            # Security-key mode: the key is the OS's unscoped root and every other route admits
            # it, so the directory admin API does too. Nothing else can administer a directory on
            # such a deployment. There is no subject to record as the actor.
            return ""
        principal_id = getattr(request.state, "user_id", None)
        claims = getattr(request.state, "claims", {}) or {}
        token_scopes = getattr(request.state, "scopes", []) or []
        admin_scope = getattr(request.state, "admin_scope", None) or AgentOSScope.ADMIN.value
        if admin_scope in token_scopes and _token_scopes_enforced(request):
            return principal_id or ""
        if role_store is not None and await role_store.acan_manage(principal_id, claims):
            return principal_id or ""
        raise HTTPException(status_code=403, detail="Admin privileges required")

    return require_admin


def get_roles_router(
    store: "Authorization",
    prefix: str = "/authz",
    tags: Optional[List[Union[str, Enum]]] = None,
) -> APIRouter:
    """Build the admin-only roles-management router bound to ``store``.

    Serves role definitions, the scope catalog, the audit trails, and role ASSIGNMENT
    (which role a subject holds). The credential-less user DIRECTORY (who the users are +
    the disabled kill-switch) is a peer concern served by :func:`get_users_router` at
    ``/users`` -- AgentOS mounts it from ``AgentOS(user_directory=...)``.
    """
    if tags is None:
        tags = ["Authorization"]

    require_admin = _make_require_admin(store)
    router = APIRouter(prefix=prefix, tags=tags, dependencies=[Depends(require_admin)])

    async def _role_or_404(slug: str) -> dict:
        rec = await store.aget_role(slug)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Role {slug!r} not found")
        return rec

    def _refused(e: RoleChangeRefused) -> HTTPException:
        # A well-formed request the store refuses on safety grounds (last admin, admin default,
        # role named after a user): a conflict with the store's state, not a validation error.
        return HTTPException(status_code=409, detail=str(e))

    # ---- roles ----------------------------------------------------------
    @router.get("/roles", response_model=PaginatedResponse[RoleSchema])
    async def list_roles(
        limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
        page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    ):
        roles = [RoleSchema.from_record(r) for r in await store._alist_roles_detailed()]
        return _page(roles, page, limit)

    @router.post("/roles", response_model=RoleSchema, status_code=201)
    async def create_role(body: CreateRoleRequest, actor: str = Depends(require_admin)):
        """Create a role (metadata only — RESTful). Add permissions afterwards via
        PUT/PATCH /roles/{slug}/scopes. Mirrors the cloud POST /roles."""
        try:
            await store._acreate_role(
                body.slug, name=body.name, description=body.description, is_default=body.is_default, actor=actor
            )
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Role {body.slug!r} already exists")
        except RoleChangeRefused as e:
            raise _refused(e)
        return RoleSchema.from_record(await _role_or_404(body.slug))

    @router.get("/roles/{slug}", response_model=RoleSchema)
    async def get_role(slug: str):
        return RoleSchema.from_record(await _role_or_404(slug))

    @router.patch("/roles/{slug}", response_model=RoleSchema)
    async def update_role(slug: str, body: UpdateRoleRequest, actor: str = Depends(require_admin)):
        """Update a role's metadata only (name/description/is_default) — scopes
        untouched. Mirrors the cloud PATCH /roles/{slug}."""
        try:
            await store.aset_role_meta(
                slug, name=body.name, description=body.description, is_default=body.is_default, actor=actor
            )
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Role {slug!r} not found")
        except RoleChangeRefused as e:
            raise _refused(e)
        return RoleSchema.from_record(await _role_or_404(slug))

    @router.delete("/roles/{slug}")
    async def delete_role(slug: str, actor: str = Depends(require_admin)) -> dict:
        try:
            await store.aremove_role(slug, actor=actor)
        except RoleChangeRefused as e:
            raise _refused(e)
        return {"slug": slug, "deleted": True}

    # ---- role scopes (subresource) -------------------------------------
    def _to_store_scopes(items):
        return [s if isinstance(s, str) else {"scope": s.scope, "effect": s.effect} for s in items]

    @router.put("/roles/{slug}/scopes", response_model=List[RoleScopeSchema])
    async def replace_role_scopes(slug: str, body: ReplaceScopesRequest, actor: str = Depends(require_admin)):
        """Replace ALL of a role's scopes (metadata preserved). Mirrors the cloud
        PUT /roles/{slug}/scopes; returns the resulting scope list."""
        await _role_or_404(slug)
        try:
            await store.aset_role_scopes(slug, _to_store_scopes(body.scopes), actor=actor)
        except RoleChangeRefused as e:
            raise _refused(e)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return [RoleScopeSchema.from_entry(e) for e in await store._aget_role_scope_entries(slug)]

    @router.patch("/roles/{slug}/scopes", response_model=RoleSchema)
    async def patch_role_scopes(slug: str, body: PatchScopesRequest, actor: str = Depends(require_admin)):
        """Apply a scope diff: add/flip ``upsert``, drop ``remove`` (everything else
        kept). Mirrors the cloud PATCH /roles/{slug}/scopes; returns the full role."""
        await _role_or_404(slug)
        try:
            await store._apatch_role_scopes(
                slug, upsert=_to_store_scopes(body.upsert), remove=_to_store_scopes(body.remove), actor=actor
            )
        except RoleChangeRefused as e:
            raise _refused(e)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return RoleSchema.from_record(await _role_or_404(slug))

    # ---- scope catalog --------------------------------------------------
    @router.get("/scopes", response_model=List[AvailableScopeItem], response_model_exclude_none=True)
    async def list_scopes() -> List[AvailableScopeItem]:
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
    def _validated_sort_field(sort_by: str) -> str:
        if sort_by not in AUDIT_SORT_FIELDS:
            raise HTTPException(status_code=422, detail=f"sort_by must be one of {list(AUDIT_SORT_FIELDS)}")
        return sort_by

    @router.get("/audit")
    async def list_audit(
        limit: int = Query(default=100, ge=1, le=1000, description="Items per page"),
        page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
        search: Optional[str] = Query(default=None, description="Filter by actor/action/target (case-insensitive)"),
        sort_by: str = Query(default=DEFAULT_AUDIT_SORT_FIELD, description="Field to sort by"),
        sort_order: SortOrder = Query(default=SortOrder.DESC, description="Sort order (asc or desc)"),
    ) -> PaginatedResponse:
        """*Change* events (role/assignment mutations), paginated ``{data, meta}``.

        404 when the change trail is off (no readable audit sink), so a frontend can tell "audit
        disabled" from "enabled but empty" and hide the tab. Mirrors how the whole ``/authz`` and
        ``/users`` surfaces 404 when their capability is not configured."""
        if not store._audit_readable:
            raise HTTPException(status_code=404, detail="Change audit is not enabled")
        start_ms = time.time() * 1000
        events = await store.aaudit_log(
            limit,
            offset=(page - 1) * limit,
            search=search,
            sort_by=_validated_sort_field(sort_by),
            order=sort_order.value,
        )
        total = await store._aaudit_count(search=search)
        return _paginated(events, page, limit, total, search_time_ms=round(time.time() * 1000 - start_ms, 2))

    @router.get("/decisions")
    async def list_decisions(
        request: Request,
        limit: int = Query(default=100, ge=1, le=1000, description="Items per page"),
        page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
        search: Optional[str] = Query(default=None, description="Filter by actor/action/target (case-insensitive)"),
        sort_by: str = Query(default=DEFAULT_AUDIT_SORT_FIELD, description="Field to sort by"),
        sort_order: SortOrder = Query(default=SortOrder.DESC, description="Sort order (asc or desc)"),
    ) -> PaginatedResponse:
        """*Decision* events (allow/deny per request), paginated ``{data, meta}``.

        Decision audit is configured on ``Authorization(audit=...)`` and lands
        on ``app.state.authz_audit`` — a separate table from the change trail above,
        so a high-volume decision log never buries the change history.

        404 when decision audit is off (no readable decision sink), the same signal the change
        trail above gives, so a frontend hides the tab instead of showing a permanently empty one."""
        sink = getattr(request.app.state, "authz_audit", None)
        if sink is None or not hasattr(sink, "read_decisions"):
            raise HTTPException(status_code=404, detail="Decision audit is not enabled")
        start_ms = time.time() * 1000
        events = await _await_sink(
            sink,
            "read_decisions",
            limit,
            offset=(page - 1) * limit,
            search=search,
            sort_by=_validated_sort_field(sort_by),
            order=sort_order.value,
        )
        total = await _await_sink(sink, "count_decisions", search=search)
        return _paginated(events, page, limit, total, search_time_ms=round(time.time() * 1000 - start_ms, 2))

    # ---- assignments ----------------------------------------------------
    async def _role_of(subject: str) -> Optional[str]:
        """The subject's single role, or None (one role per user)."""
        roles = await store.aroles_of(subject)
        return roles[0] if roles else None

    @router.get("/subjects/{subject}/roles")
    async def get_user_role(subject: str) -> dict:
        return {"subject": subject, "role": await _role_of(subject)}

    @router.post("/subjects/{subject}/roles")
    async def assign_role(subject: str, body: AssignRoleRequest, actor: str = Depends(require_admin)) -> dict:
        """Set the subject's role. One role per subject: this REPLACES any
        current role (a role select in a UI, not a multi-grant)."""
        # Validate the role exists first. Without this, an arbitrary string is written as
        # a role assignment -- and a transposed call (POST /subjects/<role-slug>/roles with
        # {"role": "<a user id>"}) would turn that user id into a "role name" in the shared
        # subject/role namespace, which the collision guard then refuses on every request,
        # silently denying that user all access with no trace in the role views.
        await _role_or_404(body.role)
        try:
            await store.aset_role(subject, body.role, actor=actor)
        except RoleChangeRefused as e:
            raise _refused(e)
        except ValueError as e:
            # The subject is itself a role slug (the transposed call the comment above describes,
            # the other way round): the store refuses it because it would be role inheritance,
            # not a user grant. Surface that as a client error, not a 500.
            raise HTTPException(status_code=400, detail=str(e))
        return {"subject": subject, "role": await _role_of(subject)}

    @router.delete("/subjects/{subject}/roles/{role}")
    async def revoke_role(subject: str, role: str, actor: str = Depends(require_admin)) -> dict:
        try:
            await store.aunassign(subject, role, actor=actor)
        except RoleChangeRefused as e:
            raise _refused(e)
        return {"subject": subject, "role": await _role_of(subject)}

    return router


async def _await_sink(sink: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    """Call a decision-sink read through its async twin (``a<name>``) when the sink has one,
    else run the sync method in a worker thread, so the handler never blocks the loop and a
    sink over an async database works."""
    import asyncio

    afn = getattr(sink, f"a{name}", None)
    if callable(afn):
        return await afn(*args, **kwargs)
    return await asyncio.to_thread(getattr(sink, name), *args, **kwargs)


def _day_bounds(starting_date: Optional[date_type], ending_date: Optional[date_type]) -> tuple:
    """Inclusive start / exclusive end of the requested UTC day range, as epoch seconds."""
    if starting_date is not None and ending_date is not None and starting_date > ending_date:
        raise HTTPException(status_code=422, detail="starting_date must be on or before ending_date")
    starting_at = (
        int(datetime.combine(starting_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        if starting_date is not None
        else None
    )
    # The exclusive bound is one day after the start of ending_date, added in epoch
    # seconds rather than as a date so date.max (9999-12-31) cannot overflow.
    ending_before = (
        int(datetime.combine(ending_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()) + 24 * 60 * 60
        if ending_date is not None
        else None
    )
    return starting_at, ending_before


def _build_user_management_metrics(
    status: Dict[str, int],
    created_rows: List[Dict[str, int]],
    roles_of: Optional[Dict[str, List[str]]],
    role_names: Optional[Dict[str, str]] = None,
) -> UserManagementMetrics:
    """Turn the store reads into the response; shared by the sync and async collectors.
    ``role_names`` maps slug to display name; a slug not in it is shown as itself."""
    names = role_names or {}
    total, disabled = status["total"], status["disabled"]
    created = [
        UsersCreatedOnDay(date=datetime.fromtimestamp(row["date"], tz=timezone.utc).date(), count=row["count"])
        for row in created_rows
    ]
    by_role: Optional[List[UsersByRole]] = None
    without_role: Optional[int] = None
    if roles_of is not None:
        counts: Dict[str, int] = {}
        without_role = 0
        for roles in roles_of.values():
            if not roles:
                without_role += 1
                continue
            for role in roles:
                counts[role] = counts.get(role, 0) + 1
        by_role = [
            UsersByRole(role_slug=role, role_name=names.get(role) or role, count=count)
            for role, count in sorted(counts.items())
        ]
    return UserManagementMetrics(
        total=total,
        active=total - disabled,
        disabled=disabled,
        without_role=without_role,
        created_per_day=created,
        by_role=by_role,
    )


def collect_user_management_metrics(
    user_store: "UserDirectory",
    role_store: "Optional[Authorization]" = None,
    starting_at: Optional[int] = None,
    ending_before: Optional[int] = None,
) -> UserManagementMetrics:
    """Read the directory metrics live. The date range bounds only the per-day series;
    the counts always describe the whole directory as it is now.

    The directory is bounded by the product's user limits and its ``created_at`` column
    is indexed, so a bounded group-by is cheaper than keeping a cache table in step.
    Roles come from the role store, not the grouping table directly, so a custom policy
    engine that keeps assignments elsewhere is counted correctly. Disabled users keep
    their role and stay in the breakdown, matching ``total``.
    """
    status = user_store.count_by_status()
    created_rows = user_store.created_by_day(starting_at=starting_at, ending_before=ending_before)
    roles_of = role_store._roles_of_many(user_store.ids()) if role_store is not None else None
    role_names = role_store._role_names() if role_store is not None else None
    return _build_user_management_metrics(status, created_rows, roles_of, role_names)


async def acollect_user_management_metrics(
    user_store: "UserDirectory",
    role_store: "Optional[Authorization]" = None,
    starting_at: Optional[int] = None,
    ending_before: Optional[int] = None,
) -> UserManagementMetrics:
    """Async twin of :func:`collect_user_management_metrics`; works whether the stores are
    bound to a sync or an async database."""
    status = await user_store.acount_by_status()
    created_rows = await user_store.acreated_by_day(starting_at=starting_at, ending_before=ending_before)
    roles_of = await role_store._aroles_of_many(await user_store.aids()) if role_store is not None else None
    role_names = await role_store._arole_names() if role_store is not None else None
    return _build_user_management_metrics(status, created_rows, roles_of, role_names)


def get_users_router(
    user_store: "UserDirectory",
    role_store: "Optional[Authorization]" = None,
    prefix: str = "/users",
    tags: Optional[List[Union[str, Enum]]] = None,
    auth_enabled: bool = True,
) -> APIRouter:
    """Build the user-DIRECTORY router (who the users are + the disabled kill-switch), a PEER of the
    roles admin API.

    AgentOS mounts this from ``AgentOS(user_directory=...)``. Identity is still asserted by the app's
    JWT; this is a directory + revocation switch, never credentials. Pass ``role_store`` to merge each
    user's role into the view and to cascade role revocation on delete (omit it for a directory
    running on plain scope RBAC). ``auth_enabled=False`` mounts it open, matching a no-auth OS where
    every route already serves anonymous callers (the admin gate needs a verified identity to check).
    """
    if tags is None:
        tags = ["User directory"]

    require_admin = _make_require_admin(role_store, auth_enabled=auth_enabled)
    router = APIRouter(prefix=prefix, tags=tags, dependencies=[Depends(require_admin)])

    async def _role_of(subject: str) -> Optional[str]:
        if role_store is None:
            return None
        roles = await role_store.aroles_of(subject)
        return roles[0] if roles else None

    async def _role_names() -> Dict[str, str]:
        """Slug to display name for every role, one metadata read. Read once per request and
        shared across a page of users, so the list view does not do one read per row."""
        return await role_store._arole_names() if role_store is not None else {}

    async def _user(user: dict, names: Optional[Dict[str, str]] = None) -> UserSchema:
        role = await _role_of(user["id"])
        if role is None:
            return UserSchema.from_user(user, None)
        if names is None:
            names = await _role_names()
        return UserSchema.from_user(user, role, names.get(role))

    @router.get("", response_model=PaginatedResponse[UserSchema])
    async def list_users(
        include_disabled: bool = True,
        limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
        page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
        search: Optional[str] = Query(default=None, description="Filter by id/email/name (case-insensitive substring)"),
        sort_by: str = Query(default=DEFAULT_USER_SORT_FIELD, description="Field to sort by"),
        sort_order: SortOrder = Query(default=SortOrder.DESC, description="Sort order (asc or desc)"),
    ):
        if sort_by not in USER_SORT_FIELDS:
            raise HTTPException(status_code=422, detail=f"sort_by must be one of {list(USER_SORT_FIELDS)}")
        # Paginate in the store (offset/limit + count) so we don't materialise the whole
        # directory and resolve roles for every user on each call. `search` filters before
        # pagination, so meta counts the matches.
        start_ms = time.time() * 1000
        rows = await user_store.alist(
            limit=limit,
            offset=(page - 1) * limit,
            include_disabled=include_disabled,
            search=search,
            sort_by=sort_by,
            order=sort_order.value,
        )
        total = await user_store.acount(include_disabled=include_disabled, search=search)
        names = await _role_names()
        return _paginated(
            [await _user(u, names) for u in rows],
            page,
            limit,
            total,
            search_time_ms=round(time.time() * 1000 - start_ms, 2),
        )

    async def _refuse_non_user_id(user_id: str) -> None:
        """The directory holds people. A system-reserved principal (``sa:*``, ``__scheduler__``,
        ``__oauth__:*``) is never a directory user: those identities skip the directory entirely,
        so a row for one is dead weight and disabling it looks like a revocation that never
        happens (a service-account PAT keeps working). A role slug is not a person either, and a
        row for one turns the roster and its metrics into nonsense. Refuse both up front."""
        from agno.os.middleware.jwt import is_reserved_principal

        if is_reserved_principal(user_id):
            raise HTTPException(
                status_code=422,
                detail=f"{user_id!r} is a system-reserved principal, not a directory user. Service accounts "
                "and system identities are never stored in the directory, so disabling them here would "
                "have no effect; revoke the credential instead.",
            )
        if role_store is not None and await role_store.aget_role(user_id) is not None:
            raise HTTPException(
                status_code=422,
                detail=f"{user_id!r} is a role, not a user. Subjects and roles share one namespace; use "
                "an opaque id (an email, say) for the person.",
            )

    @router.post("", response_model=UserSchema)
    async def create_user(body: CreateUserRequest, actor: str = Depends(require_admin)):
        await _refuse_non_user_id(body.id)
        return await _user(await user_store.aupsert(body.id, email=body.email, name=body.name, actor=actor))

    # Declared before /{user_id} so the path parameter does not swallow it.
    @router.get("/metrics", response_model=UserManagementMetrics)
    async def get_user_metrics(
        starting_date: Optional[date_type] = Query(
            default=None, description="First UTC day of the series (YYYY-MM-DD)"
        ),
        ending_date: Optional[date_type] = Query(default=None, description="Last UTC day of the series (YYYY-MM-DD)"),
    ):
        """Directory size (total, active, disabled), users created per UTC day, and, when a
        role store is configured, users per role and how many hold none. The date range
        bounds only the per-day series. Served through the async store path so it works
        whether the directory is bound to a sync or an async database."""
        starting_at, ending_before = _day_bounds(starting_date, ending_date)
        return await acollect_user_management_metrics(
            user_store, role_store, starting_at=starting_at, ending_before=ending_before
        )

    @router.get("/{user_id}", response_model=UserSchema)
    async def get_user(user_id: str):
        user = await user_store.aget(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=f"User {user_id!r} not found")
        return await _user(user)

    @router.patch("/{user_id}", response_model=UserSchema)
    async def update_user(user_id: str, body: UpdateUserRequest, actor: str = Depends(require_admin)):
        """Update a user. ``disabled`` is the revocation kill-switch: a disabled user is
        denied at the enforcement point on their next request, even with a still-valid token."""
        if await user_store.aget(user_id) is None:
            # PATCH creates an unknown id, so a create needs the same check as POST. An existing
            # row is exempt: a person who was in the directory before a role took their name must
            # stay manageable, since disabling them is the revocation an admin reaches for.
            await _refuse_non_user_id(user_id)
        user = await user_store.aupsert(user_id, email=body.email, name=body.name, actor=actor)
        if body.disabled is not None and body.disabled != user["disabled"]:
            user = await user_store.aset_disabled(user_id, body.disabled, actor=actor)
        return await _user(user)

    @router.delete("/{user_id}")
    async def delete_user(user_id: str, actor: str = Depends(require_admin)) -> dict:
        # Delete is a COMPLETE removal: revoke the user's role assignments in the same
        # operation. Otherwise deleting a (disabled) user would REVERSE their revocation --
        # the directory row is the kill-switch tombstone (absence reads as "not disabled", by
        # design, so auto-provision works), while their role assignment survives in the role
        # store, so their still-valid token regains its old access. Revoking the roles first
        # makes a deleted user access-less regardless of the tombstone.
        if role_store is not None:
            for role in await role_store.aroles_of(user_id):
                try:
                    await role_store.aunassign(user_id, role, actor=actor)
                except RoleChangeRefused as e:
                    # Deleting the last admin would lock the directory and roles APIs; refuse
                    # before the row goes, so nothing is half-deleted.
                    raise HTTPException(status_code=409, detail=str(e))
        deleted = await user_store.aremove(user_id, actor=actor)
        return {"id": user_id, "deleted": deleted}

    return router
