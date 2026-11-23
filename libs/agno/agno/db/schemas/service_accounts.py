from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s

# Namespace prepended to the account name to build the principal identifier
# (the value used as user_id on requests, sessions and traces). Keeping service
# account principals in a reserved namespace guarantees they can never collide
# with a human JWT sub.
SERVICE_ACCOUNT_PRINCIPAL_PREFIX = "sa:"

# Columns a service-account listing may be sorted by. Shared by every DB backend's
# get_service_accounts so the whitelist cannot drift between them, and so an arbitrary
# sort_by can never reach table.c[...] unclamped.
SERVICE_ACCOUNT_SORTABLE_COLUMNS = frozenset({"created_at", "name", "last_used_at", "expires_at"})


def resolve_service_account_sort_column(sort_by: str) -> str:
    """Clamp a caller-supplied sort_by to a known-safe column, defaulting to created_at."""
    return sort_by if sort_by in SERVICE_ACCOUNT_SORTABLE_COLUMNS else "created_at"


# Columns update_service_account may modify. Everything else is immutable after creation:
# identity (id, name), credentials (token_hash, token_prefix), authorization (scopes,
# user_id) and audit fields (created_at, created_by) — changing any of them would rebind
# or rescope an already-minted token. Shared by every DB backend's update_service_account
# so the guardrail cannot drift between them.
SERVICE_ACCOUNT_MUTABLE_COLUMNS = frozenset({"last_used_at", "revoked_at"})


def validate_service_account_update(updates: Dict[str, Any]) -> None:
    """Reject an update payload that is empty, touches an immutable column, or un-revokes.

    Raises ValueError so misuse fails loudly at the call site instead of reaching the
    database (or being swallowed by an adapter's catch-all error handling).
    """
    if not updates:
        raise ValueError("update_service_account requires at least one column to update")
    disallowed = set(updates) - SERVICE_ACCOUNT_MUTABLE_COLUMNS
    if disallowed:
        raise ValueError(
            f"update_service_account cannot modify {sorted(disallowed)}: "
            f"only {sorted(SERVICE_ACCOUNT_MUTABLE_COLUMNS)} are mutable; "
            "revoke the account and mint a new token instead"
        )
    if updates.get("revoked_at", ...) is None:
        raise ValueError("revocation is one-way: revoked_at cannot be reset to None")


@dataclass
class ServiceAccount:
    """Model for a service account: a machine identity authenticated by an opaque token."""

    id: str
    name: str
    token_hash: str
    token_prefix: str
    scopes: List[str] = field(default_factory=list)
    # The user this account belongs to. Distinct from created_by (audit: who minted
    # the token); user_id is ownership. None means a workspace-level machine account
    # with no owning user.
    user_id: Optional[str] = None
    created_at: Optional[int] = None
    expires_at: Optional[int] = None
    last_used_at: Optional[int] = None
    revoked_at: Optional[int] = None
    created_by: Optional[str] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.expires_at is not None:
            self.expires_at = int(self.expires_at)
        if self.last_used_at is not None:
            self.last_used_at = int(self.last_used_at)
        if self.revoked_at is not None:
            self.revoked_at = int(self.revoked_at)

    @property
    def principal(self) -> str:
        """The identifier attached to requests, sessions and traces as user_id."""
        return f"{SERVICE_ACCOUNT_PRINCIPAL_PREFIX}{self.name}"

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, now: Optional[int] = None) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= (now if now is not None else now_epoch_s())

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values (important for DB updates)."""
        return {
            "id": self.id,
            "name": self.name,
            "user_id": self.user_id,
            "token_hash": self.token_hash,
            "token_prefix": self.token_prefix,
            "scopes": self.scopes,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_used_at": self.last_used_at,
            "revoked_at": self.revoked_at,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceAccount":
        data = dict(data)
        valid_keys = {
            "id",
            "name",
            "user_id",
            "token_hash",
            "token_prefix",
            "scopes",
            "created_at",
            "expires_at",
            "last_used_at",
            "revoked_at",
            "created_by",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        if filtered.get("scopes") is None:
            filtered["scopes"] = []
        return cls(**filtered)
