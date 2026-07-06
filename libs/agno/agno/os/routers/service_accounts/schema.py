"""Pydantic request/response models for the service accounts API.

Scopes ride the shared RBAC payload shapes (:class:`~agno.os.schema.ScopeItem` for
writes, :class:`~agno.os.schema.ScopeSchema` for reads) so this API and the RBAC
governance APIs present one payload structure to frontends.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from agno.os.schema import ScopeItem, ScopeSchema
from agno.os.service_accounts import (
    DEFAULT_EXPIRY_DAYS,
    get_principal,
    is_valid_service_account_name,
)


class ServiceAccountCreate(BaseModel):
    name: str = Field(
        ...,
        max_length=63,
        description="Machine identity name (lowercase slug), e.g. 'claude-code' or 'github-actions'",
    )
    scopes: Optional[List[ScopeItem]] = Field(
        default=None,
        description="Scopes granted to the token, as {scope, effect} objects "
        "(the shared RBAC write shape; token scopes are grants, so only effect='allow' is accepted). "
        "Defaults to run and read scopes: agents:run, teams:run, workflows:run, sessions:read",
    )
    expires_in_days: Optional[int] = Field(
        default=DEFAULT_EXPIRY_DAYS,
        ge=1,
        le=3650,
        description=f"Days until the token expires (default: {DEFAULT_EXPIRY_DAYS})",
    )
    never_expires: bool = Field(
        default=False,
        description="Mint a non-expiring token. Must be set explicitly; overrides expires_in_days.",
    )
    allow_privileged_scopes: bool = Field(
        default=False,
        description="Required to grant privileged scopes: any write or delete action, the admin scope, "
        "or any service_accounts scope. Privileged tokens must be deliberate, never accidental.",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not is_valid_service_account_name(v):
            raise ValueError(
                "Name must be a lowercase slug: start with a letter or digit, "
                "then letters, digits, '_' or '-' (max 63 chars)"
            )
        return v

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: Optional[List[ScopeItem]]) -> Optional[List[ScopeItem]]:
        for item in v or []:
            if item.effect != "allow":
                raise ValueError(
                    f"Token scopes are grants: effect must be 'allow' (got {item.effect!r} for {item.scope!r})"
                )
        return v

    def scope_strings(self) -> Optional[List[str]]:
        """The requested scopes as raw strings."""
        if self.scopes is None:
            return None
        return [item.scope for item in self.scopes]


class ServiceAccountResponse(BaseModel):
    """Service account metadata. Never includes the token hash or plaintext."""

    id: str
    name: str
    principal: str = Field(..., description="The user_id attached to runs made with this token, e.g. 'sa:claude-code'")
    user_id: Optional[str] = Field(
        default=None,
        description="The user this account belongs to; None for workspace-level accounts. "
        "Distinct from created_by, which records who minted the token.",
    )
    token_prefix: str = Field(..., description="First characters of the token, for display only")
    scopes: List[ScopeSchema] = Field(
        default_factory=list, description="Scopes granted to the token, in the shared RBAC read shape"
    )
    created_at: int
    expires_at: Optional[int] = None
    last_used_at: Optional[int] = None
    revoked_at: Optional[int] = None
    created_by: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceAccountResponse":
        return cls(
            id=data["id"],
            name=data["name"],
            principal=get_principal(data["name"]),
            token_prefix=data["token_prefix"],
            scopes=[ScopeSchema.from_raw(scope) for scope in data.get("scopes") or []],
            created_at=data["created_at"],
            expires_at=data.get("expires_at"),
            last_used_at=data.get("last_used_at"),
            revoked_at=data.get("revoked_at"),
            created_by=data.get("created_by"),
            user_id=data.get("user_id"),
        )


class ServiceAccountCreateResponse(ServiceAccountResponse):
    """Returned once, at creation. The token is never retrievable again."""

    token: str = Field(..., description="The plaintext token. Shown exactly once - store it securely now.")
