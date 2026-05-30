"""Governance routers — Track B end-user RBAC HTTP surface.

Three logical groups:

- ``/scope-templates`` — CRUD over reusable scope bundles.
- ``/end-users`` — CRUD over the dev's customers, plus ``POST /end-users/{id}/tokens``
  which derives scopes from the user's assigned template (the killer feature
  over Track A's ``POST /tokens``).
- ``/tokens/{jti}`` and ``/audit-log`` — revocation + audit.

Each router is gated by scopes already declared in
``get_default_scope_mappings`` so ``JWTMiddleware`` enforces them automatically.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agno.os.auth import get_authentication_dependency
from agno.os.governance.store import (
    AuditLogEntry,
    EndUser,
    EndUserStatus,
    GovernanceStore,
    IssuedToken,
    ScopeTemplate,
)
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    UnauthorizedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings

if TYPE_CHECKING:
    from agno.os.app import AgentOS


# ---------------------------------------------------------------- request/response models


class ScopeTemplateBody(BaseModel):
    id: str = Field(..., description="Stable template identifier (e.g. 'free-tier').")
    scopes: List[str] = Field(..., description="Scopes granted to end-users assigned this template.")
    description: Optional[str] = Field(None, description="Human-readable description.")


class ScopeTemplateResponse(BaseModel):
    id: str
    scopes: List[str]
    description: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class EndUserCreateBody(BaseModel):
    external_id: str = Field(..., description="The dev's identifier for this user. Used as the JWT 'sub'.")
    template_id: str = Field(..., description="The scope template assigned to this user.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata (e.g. email, tier name).")


class EndUserPatchBody(BaseModel):
    template_id: Optional[str] = Field(None, description="Reassign to a different template (tier upgrade/downgrade).")
    status: Optional[str] = Field(None, description="One of 'active', 'suspended'. Use DELETE to soft-delete.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Replace metadata.")


class EndUserResponse(BaseModel):
    external_id: str
    template_id: str
    status: str
    metadata: Dict[str, Any]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class GovernedTokenRequest(BaseModel):
    ttl_seconds: int = Field(3600, ge=1, le=86400, description="Token lifetime in seconds (max 24h).")
    session_id: Optional[str] = Field(None, description="Optional session ID to bind to the token.")
    extra_claims: Optional[Dict[str, Any]] = Field(None, description="Extra JWT claims.")


class GovernedTokenResponse(BaseModel):
    token: str
    token_id: str
    scopes: List[str]
    expires_in: int
    audience: str


class IssuedTokenResponse(BaseModel):
    jti: str
    external_id: str
    scopes: List[str]
    issued_at: datetime
    expires_at: datetime
    revoked_at: Optional[datetime]
    last_used_at: Optional[datetime]
    status: str


class AuditLogResponse(BaseModel):
    id: str
    timestamp: datetime
    external_id: Optional[str]
    jti: Optional[str]
    action: str
    resource: Optional[str]
    status: str
    metadata: Dict[str, Any]


# ---------------------------------------------------------------- conversions


def _template_out(t: ScopeTemplate) -> ScopeTemplateResponse:
    return ScopeTemplateResponse(
        id=t.id,
        scopes=t.scopes,
        description=t.description,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _user_out(u: EndUser) -> EndUserResponse:
    return EndUserResponse(
        external_id=u.external_id,
        template_id=u.template_id,
        status=u.status.value,
        metadata=u.metadata,
        created_at=u.created_at,
        updated_at=u.updated_at,
    )


def _token_out(t: IssuedToken) -> IssuedTokenResponse:
    return IssuedTokenResponse(
        jti=t.jti,
        external_id=t.external_id,
        scopes=t.scopes,
        issued_at=t.issued_at,
        expires_at=t.expires_at,
        revoked_at=t.revoked_at,
        last_used_at=t.last_used_at,
        status=t.status.value,
    )


def _audit_out(a: AuditLogEntry) -> AuditLogResponse:
    return AuditLogResponse(
        id=a.id,
        timestamp=a.timestamp,
        external_id=a.external_id,
        jti=a.jti,
        action=a.action,
        resource=a.resource,
        status=a.status,
        metadata=a.metadata,
    )


def _record_audit(
    store: GovernanceStore,
    *,
    action: str,
    status: str,
    external_id: Optional[str] = None,
    jti: Optional[str] = None,
    resource: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort audit write. Governance endpoints log their own activity."""
    try:
        store.record_audit(
            AuditLogEntry(
                id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc),
                external_id=external_id,
                jti=jti,
                action=action,
                resource=resource,
                status=status,
                metadata=dict(metadata or {}),
            )
        )
    except Exception:
        # Audit must never break the request path.
        pass


# ---------------------------------------------------------------- router factory


def get_governance_router(
    agent_os: "AgentOS",
    store: GovernanceStore,
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """All governance endpoints under a single router."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Governance"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            403: {"description": "Forbidden", "model": UnauthorizedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    # ------------------------------------------------------------ scope-templates

    @router.get(
        "/scope-templates",
        operation_id="list_scope_templates",
        summary="List scope templates",
        response_model=List[ScopeTemplateResponse],
    )
    async def list_templates() -> List[ScopeTemplateResponse]:
        return [_template_out(t) for t in store.list_templates()]

    @router.get(
        "/scope-templates/{template_id}",
        operation_id="get_scope_template",
        summary="Get a scope template",
        response_model=ScopeTemplateResponse,
    )
    async def get_template(template_id: str) -> ScopeTemplateResponse:
        t = store.get_template(template_id)
        if t is None:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
        return _template_out(t)

    @router.post(
        "/scope-templates",
        operation_id="create_scope_template",
        summary="Create or replace a scope template",
        response_model=ScopeTemplateResponse,
    )
    async def create_template(body: ScopeTemplateBody, request: Request) -> ScopeTemplateResponse:
        if "tokens:issue" in body.scopes:
            raise HTTPException(
                status_code=400,
                detail="Refusing to create a template that grants 'tokens:issue' — that would let end-users mint tokens.",
            )
        t = store.upsert_template(ScopeTemplate(id=body.id, scopes=list(body.scopes), description=body.description))
        _record_audit(
            store,
            action="template.upsert",
            status="ok",
            resource=t.id,
            metadata={"actor": getattr(request.state, "user_id", None)},
        )
        return _template_out(t)

    @router.patch(
        "/scope-templates/{template_id}",
        operation_id="update_scope_template",
        summary="Update a scope template",
        response_model=ScopeTemplateResponse,
    )
    async def update_template(template_id: str, body: ScopeTemplateBody, request: Request) -> ScopeTemplateResponse:
        if template_id != body.id:
            raise HTTPException(status_code=400, detail="Path template_id and body id must match.")
        existing = store.get_template(template_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
        if "tokens:issue" in body.scopes:
            raise HTTPException(
                status_code=400,
                detail="Refusing to grant 'tokens:issue' via a template.",
            )
        t = store.upsert_template(ScopeTemplate(id=body.id, scopes=list(body.scopes), description=body.description))
        _record_audit(
            store,
            action="template.update",
            status="ok",
            resource=t.id,
            metadata={"actor": getattr(request.state, "user_id", None)},
        )
        return _template_out(t)

    @router.delete(
        "/scope-templates/{template_id}",
        operation_id="delete_scope_template",
        summary="Delete a scope template (only if no users are assigned).",
    )
    async def delete_template(template_id: str, request: Request) -> Dict[str, Any]:
        try:
            deleted = store.delete_template(template_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
        _record_audit(
            store,
            action="template.delete",
            status="ok",
            resource=template_id,
            metadata={"actor": getattr(request.state, "user_id", None)},
        )
        return {"deleted": template_id}

    # ------------------------------------------------------------ end-users

    @router.get(
        "/end-users",
        operation_id="list_end_users",
        summary="List end-users",
        response_model=List[EndUserResponse],
    )
    async def list_users(
        status: Optional[str] = Query(None, description="Filter by status (active/suspended/deleted)."),
        template_id: Optional[str] = Query(None, description="Filter by template."),
    ) -> List[EndUserResponse]:
        status_enum = EndUserStatus(status) if status else None
        return [_user_out(u) for u in store.list_end_users(status=status_enum, template_id=template_id)]

    @router.get(
        "/end-users/{external_id}",
        operation_id="get_end_user",
        summary="Get an end-user",
        response_model=EndUserResponse,
    )
    async def get_user(external_id: str) -> EndUserResponse:
        u = store.get_end_user(external_id)
        if u is None:
            raise HTTPException(status_code=404, detail=f"End-user '{external_id}' not found")
        return _user_out(u)

    @router.post(
        "/end-users",
        operation_id="create_end_user",
        summary="Create or replace an end-user",
        response_model=EndUserResponse,
    )
    async def create_user(body: EndUserCreateBody, request: Request) -> EndUserResponse:
        if store.get_template(body.template_id) is None:
            raise HTTPException(status_code=400, detail=f"Template '{body.template_id}' does not exist.")
        u = store.upsert_end_user(
            EndUser(
                external_id=body.external_id,
                template_id=body.template_id,
                metadata=dict(body.metadata),
            )
        )
        _record_audit(
            store,
            action="end_user.upsert",
            status="ok",
            external_id=u.external_id,
            resource=u.external_id,
            metadata={"template_id": u.template_id, "actor": getattr(request.state, "user_id", None)},
        )
        return _user_out(u)

    @router.patch(
        "/end-users/{external_id}",
        operation_id="update_end_user",
        summary="Update an end-user (e.g. switch tier or suspend).",
        response_model=EndUserResponse,
    )
    async def update_user(external_id: str, body: EndUserPatchBody, request: Request) -> EndUserResponse:
        existing = store.get_end_user(external_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"End-user '{external_id}' not found")
        if body.template_id and store.get_template(body.template_id) is None:
            raise HTTPException(status_code=400, detail=f"Template '{body.template_id}' does not exist.")
        if body.status:
            try:
                new_status = EndUserStatus(body.status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status '{body.status}'")
            if new_status == EndUserStatus.DELETED:
                raise HTTPException(status_code=400, detail="Use DELETE /end-users/{id} to delete.")
        old_template = existing.template_id
        merged = EndUser(
            external_id=existing.external_id,
            template_id=body.template_id or existing.template_id,
            status=EndUserStatus(body.status) if body.status else existing.status,
            metadata=body.metadata if body.metadata is not None else existing.metadata,
            created_at=existing.created_at,
        )
        u = store.upsert_end_user(merged)
        _record_audit(
            store,
            action="end_user.update",
            status="ok",
            external_id=u.external_id,
            resource=u.external_id,
            metadata={
                "old_template": old_template,
                "new_template": u.template_id,
                "new_status": u.status.value,
                "actor": getattr(request.state, "user_id", None),
            },
        )
        return _user_out(u)

    @router.delete(
        "/end-users/{external_id}",
        operation_id="delete_end_user",
        summary="Soft-delete an end-user and revoke their tokens.",
    )
    async def delete_user(external_id: str, request: Request) -> Dict[str, Any]:
        u = store.soft_delete_end_user(external_id)
        if u is None:
            raise HTTPException(status_code=404, detail=f"End-user '{external_id}' not found")
        _record_audit(
            store,
            action="end_user.delete",
            status="ok",
            external_id=external_id,
            resource=external_id,
            metadata={"actor": getattr(request.state, "user_id", None)},
        )
        return {"external_id": external_id, "status": u.status.value}

    # ------------------------------------------------------------ governed tokens

    @router.post(
        "/end-users/{external_id}/tokens",
        operation_id="issue_governed_token",
        summary="Mint a token for an end-user using their assigned template's scopes.",
        response_model=GovernedTokenResponse,
    )
    async def issue_governed_token(
        external_id: str, body: GovernedTokenRequest, request: Request
    ) -> GovernedTokenResponse:
        user = store.get_end_user(external_id)
        if user is None:
            _record_audit(
                store,
                action="token.issue",
                status="error",
                external_id=external_id,
                metadata={"reason": "user_not_found"},
            )
            raise HTTPException(status_code=404, detail=f"End-user '{external_id}' not found")
        if user.status != EndUserStatus.ACTIVE:
            _record_audit(
                store,
                action="token.issue",
                status="denied",
                external_id=external_id,
                metadata={"reason": f"status={user.status.value}"},
            )
            raise HTTPException(
                status_code=403,
                detail=f"End-user '{external_id}' is not active (status={user.status.value}).",
            )
        template = store.get_template(user.template_id)
        if template is None:
            raise HTTPException(
                status_code=500,
                detail=f"End-user '{external_id}' references missing template '{user.template_id}'.",
            )

        token = agent_os.issue_token(
            subject=external_id,
            scopes=template.scopes,
            ttl_seconds=body.ttl_seconds,
            session_id=body.session_id,
            extra_claims=body.extra_claims,
        )
        import jwt as pyjwt

        decoded = pyjwt.decode(token, options={"verify_signature": False})
        jti = decoded["jti"]
        now = datetime.now(timezone.utc)
        store.record_issued_token(
            IssuedToken(
                jti=jti,
                external_id=external_id,
                scopes=list(template.scopes),
                issued_at=now,
                expires_at=datetime.fromtimestamp(decoded["exp"], tz=timezone.utc),
            )
        )
        _record_audit(
            store,
            action="token.issue",
            status="ok",
            external_id=external_id,
            jti=jti,
            metadata={"template_id": template.id, "actor": getattr(request.state, "user_id", None)},
        )
        return GovernedTokenResponse(
            token=token,
            token_id=jti,
            scopes=list(template.scopes),
            expires_in=body.ttl_seconds,
            audience=decoded["aud"],
        )

    @router.get(
        "/end-users/{external_id}/tokens",
        operation_id="list_user_tokens",
        summary="List tokens for an end-user.",
        response_model=List[IssuedTokenResponse],
    )
    async def list_user_tokens(
        external_id: str,
        include_revoked: bool = Query(False, description="Include revoked tokens."),
    ) -> List[IssuedTokenResponse]:
        return [_token_out(t) for t in store.list_tokens_for_user(external_id, include_revoked=include_revoked)]

    @router.delete(
        "/tokens/{jti}",
        operation_id="revoke_token",
        summary="Revoke a token by its jti.",
    )
    async def revoke_token(jti: str, request: Request) -> Dict[str, Any]:
        token = store.get_token(jti)
        if token is None:
            raise HTTPException(status_code=404, detail=f"Token '{jti}' not found")
        if not store.revoke_token(jti):
            return {"jti": jti, "already_revoked": True}
        _record_audit(
            store,
            action="token.revoke",
            status="ok",
            external_id=token.external_id,
            jti=jti,
            metadata={"actor": getattr(request.state, "user_id", None)},
        )
        return {"jti": jti, "revoked": True}

    # ------------------------------------------------------------ audit

    @router.get(
        "/audit-log",
        operation_id="list_audit_log",
        summary="Query the governance audit log.",
        response_model=List[AuditLogResponse],
    )
    async def list_audit(
        external_id: Optional[str] = Query(None),
        action: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
    ) -> List[AuditLogResponse]:
        return [_audit_out(a) for a in store.list_audit(external_id=external_id, action=action, limit=limit)]

    return router
