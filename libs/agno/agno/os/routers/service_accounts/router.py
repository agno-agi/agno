"""Service accounts API router - mint, list, and revoke opaque machine tokens."""

import asyncio
import time
from typing import Any, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from agno.db.schemas.service_accounts import ServiceAccount
from agno.os.routers.service_accounts.schema import (
    ServiceAccountCreate,
    ServiceAccountCreateResponse,
    ServiceAccountResponse,
)
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.os.scopes import AgentOSScope, has_required_scopes, parse_scope
from agno.os.service_accounts import (
    DEFAULT_EXPIRY_DAYS,
    DEFAULT_SERVICE_ACCOUNT_SCOPES,
    generate_token,
    get_invalid_scopes,
    get_privileged_scopes,
)
from agno.utils.log import log_error

# Valid DB method names that _db_call can invoke
_ServiceAccountDbMethod = Literal[
    "create_service_account",
    "get_service_account",
    "get_service_account_by_name",
    "get_service_accounts",
    "update_service_account",
]


def _is_integrity_error(exc: Exception) -> bool:
    try:
        from sqlalchemy.exc import IntegrityError

        return isinstance(exc, IntegrityError)
    except ImportError:
        return False


def _caller_holds_scope(caller_scopes: List[str], scope: str, admin_scope: Optional[str]) -> bool:
    """Whether the caller's scopes cover a single requested scope.

    Per-resource scopes (e.g. agents:my-agent:run) must be checked with their
    resource context, so a caller holding exactly that scope - or a wildcard/global
    scope over the resource - is recognised as holding it.
    """
    parsed = parse_scope(scope, admin_scope=admin_scope)
    if parsed.is_per_resource_scope and parsed.resource and parsed.action:
        return has_required_scopes(
            caller_scopes,
            [f"{parsed.resource}:{parsed.action}"],
            resource_type=parsed.resource,
            resource_id=parsed.resource_id,
            admin_scope=admin_scope,
        )
    return has_required_scopes(caller_scopes, [scope], admin_scope=admin_scope)


def get_service_accounts_router(os_db: Any, settings: Any) -> APIRouter:
    """Factory that creates and returns the service accounts router.

    Args:
        os_db: The AgentOS-level DB adapter (must support service account methods).
        settings: AgnoAPISettings instance.

    Returns:
        An APIRouter with all service account endpoints attached.
    """
    from agno.os.auth import get_authentication_dependency

    router = APIRouter(tags=["Service Accounts"])
    auth_dependency = get_authentication_dependency(settings)

    async def _db_call(method_name: _ServiceAccountDbMethod, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(os_db, method_name, None)
        if fn is None:
            raise HTTPException(status_code=503, detail="Service accounts not supported by the configured database")
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            # Sync DB drivers do blocking I/O; keep it off the event loop like the
            # services layer and the ServiceAccountVerifier do.
            return await run_in_threadpool(fn, *args, **kwargs)
        except NotImplementedError:
            raise HTTPException(status_code=503, detail="Service accounts not supported by the configured database")

    def _get_admin_scope(request: Request) -> Optional[str]:
        admin_scope_raw = getattr(request.state, "admin_scope", None) or getattr(request.app.state, "admin_scope", None)
        return admin_scope_raw if isinstance(admin_scope_raw, str) else None

    def _validate_requested_scopes(request: Request, body: ServiceAccountCreate, scopes: List[str]) -> None:
        """Reject unknown scopes, gate privileged scopes behind the explicit flag, and
        enforce the subset rule: a caller with scopes can only grant scopes it holds."""
        admin_scope = _get_admin_scope(request)

        invalid_scopes = get_invalid_scopes(scopes, admin_scope=admin_scope)
        if invalid_scopes:
            raise HTTPException(status_code=400, detail=f"Invalid scope(s): {', '.join(invalid_scopes)}")

        privileged_scopes = get_privileged_scopes(scopes, admin_scope=admin_scope)
        if privileged_scopes and not body.allow_privileged_scopes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Privileged scope(s) require allow_privileged_scopes=true: {', '.join(privileged_scopes)}. "
                    "Privileged tokens must be deliberate, never accidental."
                ),
            )

        # Subset rule: minted scopes must be held by the creator, so a caller with
        # only service_accounts:write can never escalate by minting a token more
        # powerful than itself.
        caller_scopes = getattr(request.state, "scopes", None)
        if caller_scopes is None:
            # No scope context (request.state.scopes is None). Two very different callers
            # can land here:
            #   - a trusted root authenticated by the OS security key: the auth layer set
            #     request.state.authenticated = True but attached no scopes. It is unscoped
            #     by definition and may mint anything. (The internal service token carries
            #     INTERNAL_SERVICE_SCOPES, so it is NOT None here and takes the subset-rule
            #     path below instead.)
            #   - an anonymous caller on an OPEN instance (no security key, no JWT):
            #     authenticated is falsy. It must NOT be able to mint ANY token. A minted PAT
            #     persists as a durable credential even after the operator later switches
            #     authentication on (PAT scopes are enforced independently of the authorization
            #     flag), so a briefly-exposed open instance would leak a permanent credential.
            #     Even a non-privileged run/read token grants durable compute and cross-user
            #     reads, so anonymous minting is refused outright -- not just for privileged
            #     scopes. Minting requires a real credential (OS_SECURITY_KEY or JWT).
            if getattr(request.state, "authenticated", False):
                return
            raise HTTPException(
                status_code=401,
                detail=("JWT authentication is required to mint a service account."),
            )
        effective_admin_scope = admin_scope or AgentOSScope.ADMIN.value
        if effective_admin_scope in caller_scopes:
            return
        scopes_not_held = [scope for scope in scopes if not _caller_holds_scope(caller_scopes, scope, admin_scope)]
        if scopes_not_held:
            raise HTTPException(
                status_code=403,
                detail=f"Cannot grant scope(s) you do not hold: {', '.join(scopes_not_held)}",
            )

    @router.post("/service-accounts", response_model=ServiceAccountCreateResponse, status_code=201)
    async def create_service_account(
        body: ServiceAccountCreate,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> ServiceAccountCreateResponse:
        """Mint a service account token. The plaintext token is returned exactly once."""
        requested_scopes = body.scope_strings()
        scopes = requested_scopes if requested_scopes is not None else list(DEFAULT_SERVICE_ACCOUNT_SCOPES)
        _validate_requested_scopes(request, body, scopes)

        existing = await _db_call("get_service_account_by_name", body.name)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"An active service account named '{body.name}' already exists. Revoke it first to rotate.",
            )

        now = int(time.time())
        expires_at: Optional[int] = None
        if not body.never_expires:
            expires_in_days = body.expires_in_days if body.expires_in_days is not None else DEFAULT_EXPIRY_DAYS
            expires_at = now + expires_in_days * 86400

        plaintext_token, token_hash, token_prefix = generate_token()
        account = ServiceAccount(
            id=str(uuid4()),
            name=body.name,
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=scopes,
            created_at=now,
            expires_at=expires_at,
            created_by=getattr(request.state, "user_id", None),
            user_id=getattr(request.state, "user_id", None),
        )

        try:
            await _db_call("create_service_account", account.to_dict())
        except HTTPException:
            raise
        except Exception as exc:
            if _is_integrity_error(exc):
                raise HTTPException(
                    status_code=409,
                    detail=f"An active service account named '{body.name}' already exists. Revoke it first to rotate.",
                )
            log_error(f"Could not create service account: {exc}")
            raise HTTPException(status_code=500, detail="Could not create service account")

        metadata = ServiceAccountResponse.from_dict(account.to_dict())
        return ServiceAccountCreateResponse(**metadata.model_dump(), token=plaintext_token)

    @router.get("/service-accounts", response_model=PaginatedResponse[ServiceAccountResponse])
    async def list_service_accounts(
        include_revoked: bool = Query(True),
        limit: int = Query(20, ge=1, le=100),
        page: int = Query(1, ge=1),
        sort_by: str = Query("created_at"),
        sort_order: str = Query("desc"),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[ServiceAccountResponse]:
        """List service accounts. Returns metadata and display prefixes only - never hashes or plaintext."""
        accounts, total_count = await _db_call(
            "get_service_accounts",
            include_revoked=include_revoked,
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=[ServiceAccountResponse.from_dict(account) for account in accounts],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.delete("/service-accounts/{service_account_id}", status_code=204)
    async def revoke_service_account(
        service_account_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> None:
        """Revoke a service account. Idempotent.

        Takes effect immediately on this worker (the local verification cache entry is
        evicted) and within the cache TTL on other workers.
        """
        existing = await _db_call("get_service_account", service_account_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Service account '{service_account_id}' not found")
        if existing.get("revoked_at") is None:
            updated = await _db_call("update_service_account", service_account_id, revoked_at=int(time.time()))
            if updated is None:
                raise HTTPException(status_code=500, detail="Could not revoke service account")

        # Evict the cached verification so this worker rejects the token immediately;
        # other workers converge as their cached entry ages out within the TTL.
        verifier = getattr(request.app.state, "service_account_verifier", None)
        token_hash = existing.get("token_hash")
        if verifier is not None and token_hash:
            verifier.invalidate(token_hash)
        return None

    return router
