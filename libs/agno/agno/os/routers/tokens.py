"""Token issuance router (Track A: end-user RBAC).

Exposes a single endpoint, ``POST /tokens``, that the developer's backend uses
to mint scoped JWTs for their end-users. The endpoint is itself protected by
the ``tokens:issue`` scope so only the developer's backend (holding a token
with that scope) can mint downstream tokens. Never grant ``tokens:issue`` to
end-user-facing tokens.

This router is a thin HTTP wrapper around ``AgentOS.issue_token()`` so the
helper and the API stay in lock-step. Track B will add a richer router under
``/end-users`` that derives scopes from persisted scope templates.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    UnauthenticatedResponse,
    UnauthorizedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings

if TYPE_CHECKING:
    from agno.os.app import AgentOS


class IssueTokenRequest(BaseModel):
    subject: str = Field(..., description="End-user identifier; stored in the JWT 'sub' claim.")
    scopes: List[str] = Field(..., description="List of Agno scope strings to grant.")
    ttl_seconds: int = Field(3600, ge=1, le=86400, description="Token lifetime in seconds (max 24h).")
    session_id: Optional[str] = Field(None, description="Optional session ID to bind the token to.")
    extra_claims: Optional[Dict[str, Any]] = Field(
        None, description="Optional extra JWT claims (e.g. tenant_id, role)."
    )


class IssueTokenResponse(BaseModel):
    token: str = Field(..., description="The signed JWT.")
    token_id: str = Field(..., description="The JWT 'jti' claim — use this for revocation/audit.")
    expires_in: int = Field(..., description="Seconds until the token expires.")
    audience: str = Field(..., description="The 'aud' claim (the AgentOS ID).")


def get_tokens_router(agent_os: "AgentOS", settings: AgnoAPISettings = AgnoAPISettings()) -> APIRouter:
    """Create the token issuance router bound to a specific AgentOS instance."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Tokens"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            403: {"description": "Forbidden", "model": UnauthorizedResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    @router.post(
        "/tokens",
        operation_id="issue_token",
        summary="Issue a scoped JWT for an end-user",
        description=(
            "Mints a short-lived HS256 JWT bound to this AgentOS instance. The caller must "
            "hold the `tokens:issue` scope — this endpoint is intended to be called by the "
            "developer's backend, not by end-users directly. The returned token's audience "
            "(`aud`) is pinned to the AgentOS id, so it cannot be replayed against another OS."
        ),
        response_model=IssueTokenResponse,
    )
    async def issue_token(request: Request, body: IssueTokenRequest) -> IssueTokenResponse:
        # Guardrail: refuse to mint tokens that include `tokens:issue` themselves.
        # End-user tokens should never be able to issue more tokens — that's a
        # privilege-escalation footgun. Operators who really want a downstream
        # service to mint tokens can call ``agent_os.issue_token()`` directly.
        if "tokens:issue" in body.scopes:
            raise HTTPException(
                status_code=400,
                detail="Refusing to issue a token carrying 'tokens:issue'. Mint such tokens server-side.",
            )

        try:
            token = agent_os.issue_token(
                subject=body.subject,
                scopes=body.scopes,
                ttl_seconds=body.ttl_seconds,
                session_id=body.session_id,
                extra_claims=body.extra_claims,
            )
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        # Decode (without verification — we just signed it) to surface the jti
        # and audience back to the caller so they can store them for revocation.
        import jwt as pyjwt

        decoded = pyjwt.decode(token, options={"verify_signature": False})
        return IssueTokenResponse(
            token=token,
            token_id=decoded["jti"],
            expires_in=body.ttl_seconds,
            audience=decoded["aud"],
        )

    return router
