"""GovernanceStore — persistence layer for Track B end-user RBAC.

Owns four tables:

- ``os_scope_templates`` — reusable scope bundles (e.g. ``free-tier``).
- ``os_end_users`` — Nia's customers; each one is assigned exactly one template.
- ``os_api_tokens`` — every JWT minted via the governance endpoints, keyed by
  the JWT ``jti``. Revoking a token sets ``revoked_at`` on its row.
- ``os_audit_log`` — append-only log of governance + auth events. The pitch:
  Nia can answer ``who did what?`` from this table for their SOC2 evidence.

Design choices (locked in):

- ``external_id`` is the primary key of ``os_end_users``. Nia uses their own
  user identifier directly — no extra UUID mapping.
- Delete is soft: ``DELETE /end-users/{id}`` flips ``status`` to ``deleted``
  and revokes all of the user's active tokens. Audit history is preserved.
- Storage uses the same SQLAlchemy engine that powers the AgentOS database
  (Postgres or SQLite). No new connection / config knob.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    Text,
    and_,
    delete,
    insert,
    select,
    update,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


class EndUserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class TokenStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass
class ScopeTemplate:
    id: str
    scopes: List[str]
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class EndUser:
    external_id: str
    template_id: str
    status: EndUserStatus = EndUserStatus.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class IssuedToken:
    jti: str
    external_id: str
    scopes: List[str]
    issued_at: datetime
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None

    @property
    def status(self) -> TokenStatus:
        if self.revoked_at is not None:
            return TokenStatus.REVOKED
        if self.expires_at <= datetime.now(timezone.utc):
            return TokenStatus.EXPIRED
        return TokenStatus.ACTIVE


@dataclass
class AuditLogEntry:
    id: str
    timestamp: datetime
    external_id: Optional[str]
    jti: Optional[str]
    action: str
    resource: Optional[str]
    status: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GovernanceStore:
    """Persisted state for Track B end-user RBAC.

    Constructed from any DB adapter that exposes ``db_engine`` (i.e. the
    SQLAlchemy-backed adapters: Postgres, SQLite, MySQL, SingleStore).
    Tables are auto-created on first construction.
    """

    TABLE_TEMPLATES = "os_scope_templates"
    TABLE_USERS = "os_end_users"
    TABLE_TOKENS = "os_api_tokens"
    TABLE_AUDIT = "os_audit_log"

    def __init__(self, engine: "Engine", schema: Optional[str] = None) -> None:
        self.engine = engine
        self.schema = schema
        self.metadata = MetaData(schema=schema)
        self._define_tables()
        self.metadata.create_all(self.engine, checkfirst=True)

    def _define_tables(self) -> None:
        self.templates_table = Table(
            self.TABLE_TEMPLATES,
            self.metadata,
            Column("id", String(255), primary_key=True),
            Column("scopes", JSON, nullable=False),
            Column("description", Text, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )

        self.users_table = Table(
            self.TABLE_USERS,
            self.metadata,
            Column("external_id", String(255), primary_key=True),
            Column("template_id", String(255), nullable=False),
            Column("status", String(32), nullable=False),
            Column("metadata", JSON, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )

        self.tokens_table = Table(
            self.TABLE_TOKENS,
            self.metadata,
            Column("jti", String(64), primary_key=True),
            Column("external_id", String(255), nullable=False, index=True),
            Column("scopes", JSON, nullable=False),
            Column("issued_at", DateTime(timezone=True), nullable=False),
            Column("expires_at", DateTime(timezone=True), nullable=False),
            Column("revoked_at", DateTime(timezone=True), nullable=True),
            Column("last_used_at", DateTime(timezone=True), nullable=True),
            Index(f"ix_{self.TABLE_TOKENS}_user_active", "external_id", "revoked_at"),
        )

        self.audit_table = Table(
            self.TABLE_AUDIT,
            self.metadata,
            Column("id", String(36), primary_key=True),
            Column("timestamp", DateTime(timezone=True), nullable=False, index=True),
            Column("external_id", String(255), nullable=True, index=True),
            Column("jti", String(64), nullable=True, index=True),
            Column("action", String(64), nullable=False),
            Column("resource", String(255), nullable=True),
            Column("status", String(32), nullable=False),
            Column("metadata", JSON, nullable=False),
            Column("is_governance_event", Boolean, nullable=False, default=False),
        )

    # ------------------------------------------------------------------ templates

    def upsert_template(self, template: ScopeTemplate) -> ScopeTemplate:
        now = _utcnow()
        if template.created_at is None:
            template.created_at = now
        template.updated_at = now
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(self.templates_table).where(self.templates_table.c.id == template.id)
            ).first()
            if existing is None:
                conn.execute(
                    insert(self.templates_table).values(
                        id=template.id,
                        scopes=list(template.scopes),
                        description=template.description,
                        created_at=template.created_at,
                        updated_at=template.updated_at,
                    )
                )
            else:
                conn.execute(
                    update(self.templates_table)
                    .where(self.templates_table.c.id == template.id)
                    .values(
                        scopes=list(template.scopes),
                        description=template.description,
                        updated_at=template.updated_at,
                    )
                )
        return template

    def get_template(self, template_id: str) -> Optional[ScopeTemplate]:
        with self.engine.connect() as conn:
            row = conn.execute(select(self.templates_table).where(self.templates_table.c.id == template_id)).first()
        return _row_to_template(row) if row else None

    def list_templates(self) -> List[ScopeTemplate]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(self.templates_table)).fetchall()
        return [_row_to_template(r) for r in rows]

    def delete_template(self, template_id: str) -> bool:
        with self.engine.begin() as conn:
            # Refuse to delete a template that's still assigned to users.
            in_use = conn.execute(
                select(self.users_table.c.external_id).where(self.users_table.c.template_id == template_id).limit(1)
            ).first()
            if in_use is not None:
                raise ValueError(f"Template '{template_id}' is still assigned to one or more end-users.")
            result = conn.execute(delete(self.templates_table).where(self.templates_table.c.id == template_id))
        return result.rowcount > 0

    # ------------------------------------------------------------------ end-users

    def upsert_end_user(self, user: EndUser) -> EndUser:
        now = _utcnow()
        if user.created_at is None:
            user.created_at = now
        user.updated_at = now
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(self.users_table).where(self.users_table.c.external_id == user.external_id)
            ).first()
            if existing is None:
                conn.execute(
                    insert(self.users_table).values(
                        external_id=user.external_id,
                        template_id=user.template_id,
                        status=user.status.value,
                        metadata=dict(user.metadata),
                        created_at=user.created_at,
                        updated_at=user.updated_at,
                    )
                )
            else:
                conn.execute(
                    update(self.users_table)
                    .where(self.users_table.c.external_id == user.external_id)
                    .values(
                        template_id=user.template_id,
                        status=user.status.value,
                        metadata=dict(user.metadata),
                        updated_at=user.updated_at,
                    )
                )
        return user

    def get_end_user(self, external_id: str) -> Optional[EndUser]:
        with self.engine.connect() as conn:
            row = conn.execute(select(self.users_table).where(self.users_table.c.external_id == external_id)).first()
        return _row_to_user(row) if row else None

    def list_end_users(
        self,
        status: Optional[EndUserStatus] = None,
        template_id: Optional[str] = None,
    ) -> List[EndUser]:
        stmt = select(self.users_table)
        conditions = []
        if status is not None:
            conditions.append(self.users_table.c.status == status.value)
        if template_id is not None:
            conditions.append(self.users_table.c.template_id == template_id)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_row_to_user(r) for r in rows]

    def soft_delete_end_user(self, external_id: str) -> Optional[EndUser]:
        """Mark a user as deleted and revoke all their active tokens.

        Returns the updated user, or None if the user didn't exist.
        Audit history is preserved (`DELETE` is logged separately by the caller).
        """
        now = _utcnow()
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(self.users_table).where(self.users_table.c.external_id == external_id)
            ).first()
            if existing is None:
                return None
            conn.execute(
                update(self.users_table)
                .where(self.users_table.c.external_id == external_id)
                .values(status=EndUserStatus.DELETED.value, updated_at=now)
            )
            conn.execute(
                update(self.tokens_table)
                .where(
                    and_(
                        self.tokens_table.c.external_id == external_id,
                        self.tokens_table.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=now)
            )
            row = conn.execute(select(self.users_table).where(self.users_table.c.external_id == external_id)).first()
        return _row_to_user(row) if row else None

    # ------------------------------------------------------------------ tokens

    def record_issued_token(self, token: IssuedToken) -> IssuedToken:
        with self.engine.begin() as conn:
            conn.execute(
                insert(self.tokens_table).values(
                    jti=token.jti,
                    external_id=token.external_id,
                    scopes=list(token.scopes),
                    issued_at=token.issued_at,
                    expires_at=token.expires_at,
                    revoked_at=token.revoked_at,
                    last_used_at=token.last_used_at,
                )
            )
        return token

    def get_token(self, jti: str) -> Optional[IssuedToken]:
        with self.engine.connect() as conn:
            row = conn.execute(select(self.tokens_table).where(self.tokens_table.c.jti == jti)).first()
        return _row_to_token(row) if row else None

    def list_tokens_for_user(self, external_id: str, include_revoked: bool = False) -> List[IssuedToken]:
        stmt = select(self.tokens_table).where(self.tokens_table.c.external_id == external_id)
        if not include_revoked:
            stmt = stmt.where(self.tokens_table.c.revoked_at.is_(None))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_row_to_token(r) for r in rows]

    def revoke_token(self, jti: str) -> bool:
        now = _utcnow()
        with self.engine.begin() as conn:
            result = conn.execute(
                update(self.tokens_table)
                .where(
                    and_(
                        self.tokens_table.c.jti == jti,
                        self.tokens_table.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=now)
            )
        return result.rowcount > 0

    def touch_token(self, jti: str) -> None:
        """Update last_used_at on a token. Best-effort; never raises."""
        now = _utcnow()
        try:
            with self.engine.begin() as conn:
                conn.execute(update(self.tokens_table).where(self.tokens_table.c.jti == jti).values(last_used_at=now))
        except Exception:
            pass

    # ------------------------------------------------------------------ audit

    def record_audit(self, entry: AuditLogEntry) -> AuditLogEntry:
        with self.engine.begin() as conn:
            conn.execute(
                insert(self.audit_table).values(
                    id=entry.id,
                    timestamp=entry.timestamp,
                    external_id=entry.external_id,
                    jti=entry.jti,
                    action=entry.action,
                    resource=entry.resource,
                    status=entry.status,
                    metadata=dict(entry.metadata),
                    is_governance_event=entry.metadata.pop("__governance__", False) if entry.metadata else False,
                )
            )
        return entry

    def list_audit(
        self,
        external_id: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AuditLogEntry]:
        stmt = select(self.audit_table).order_by(self.audit_table.c.timestamp.desc()).limit(limit)
        conditions = []
        if external_id:
            conditions.append(self.audit_table.c.external_id == external_id)
        if action:
            conditions.append(self.audit_table.c.action == action)
        if since:
            conditions.append(self.audit_table.c.timestamp >= since)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_row_to_audit(r) for r in rows]


def _row_to_template(row: Any) -> ScopeTemplate:
    m = row._mapping
    return ScopeTemplate(
        id=m["id"],
        scopes=list(m["scopes"] or []),
        description=m["description"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


def _row_to_user(row: Any) -> EndUser:
    m = row._mapping
    return EndUser(
        external_id=m["external_id"],
        template_id=m["template_id"],
        status=EndUserStatus(m["status"]),
        metadata=dict(m["metadata"] or {}),
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


def _row_to_token(row: Any) -> IssuedToken:
    m = row._mapping
    return IssuedToken(
        jti=m["jti"],
        external_id=m["external_id"],
        scopes=list(m["scopes"] or []),
        issued_at=m["issued_at"],
        expires_at=m["expires_at"],
        revoked_at=m["revoked_at"],
        last_used_at=m["last_used_at"],
    )


def _row_to_audit(row: Any) -> AuditLogEntry:
    m = row._mapping
    return AuditLogEntry(
        id=m["id"],
        timestamp=m["timestamp"],
        external_id=m["external_id"],
        jti=m["jti"],
        action=m["action"],
        resource=m["resource"],
        status=m["status"],
        metadata=dict(m["metadata"] or {}),
    )
