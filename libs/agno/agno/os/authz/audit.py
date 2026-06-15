"""Audit trail for authorization changes.

There are two kinds of "audit" people mean, and we keep them in two separate
tables (see :class:`DbAuditSink`) because they answer different questions:

1. Decision audit ("was alice allowed to run agent X, and with which token?") —
   recorded by the JWT middleware on every protected request when an
   :class:`AuditSink` is set on ``AuthorizationConfig(audit=...)``. Each row is an
   ``access.allowed`` / ``access.denied`` event with the principal, the route, the
   required scopes, the caller's scopes, and a NON-secret token reference (the
   token's ``jti`` when present, otherwise a short hash — never the token itself).
   (The native policy engine also logs every decision to the ``agno.authz.engine``
   logger; ``ManagedRoleStore(decision_log=True)`` bumps it to INFO.)

2. Change audit ("who granted alice the admin role, when, before/after?") — the
   policy engine cannot provide this: it never sees the acting principal, and its
   policy rows are overwrite-in-place with no history. So it must be captured at
   the layer that knows the actor — the management API / store. Plug an
   :class:`AuditSink` into :class:`~agno.os.authz.role_store.ManagedRoleStore`
   (directly or via ``get_roles_router``) and every role/assignment mutation emits
   a structured, append-only :class:`AuditEvent` with the actor and before/after.

The same :class:`DbAuditSink` instance can serve both: ``record()`` routes change
events to ``authz_audit`` and decision events to ``authz_decisions``.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional

# The audit-trail read contract (shared by both trails — change and decision):
# which fields a page can be sorted by / searched over, and the defaults. The
# roles router validates request params against these, so they have one owner.
AUDIT_SORT_FIELDS = ("created_at", "actor", "action", "target")
AUDIT_SEARCH_FIELDS = ("actor", "action", "target")
DEFAULT_AUDIT_SORT_FIELD = "created_at"
DEFAULT_AUDIT_SORT_ORDER = "desc"


@dataclass
class AuditEvent:
    """One authorization-change record. Append-only; never mutated after emit.

    Attributes:
        action: what happened — ``role.set_scopes`` / ``role.removed`` /
            ``user.assigned`` / ``user.unassigned``.
        actor: the principal who made the change (JWT ``sub`` of the admin), or
            None for changes made in code outside a request (treated as system).
        target: the role name (role changes) or subject id (assignment changes).
        before: prior state — the subject's roles (list of str) or a role's scope
            entries (list of ``{"scope", "effect"}`` dicts) — or None.
        after: new state, or None (e.g. on removal).
        timestamp: epoch seconds when the change was recorded.
    """

    action: str
    actor: Optional[str]
    target: str
    before: Optional[List[Any]] = None
    after: Optional[List[Any]] = None
    timestamp: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "created_at": self.timestamp,
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "before": self.before,
            "after": self.after,
            **({"metadata": self.metadata} if self.metadata else {}),
        }


class AuditSink(ABC):
    """Where audit events go. Implement ``record`` to send them anywhere."""

    @abstractmethod
    def record(self, event: AuditEvent) -> None:
        """Persist/emit one event. Must not raise into the caller's path."""
        ...


class LoggingAuditSink(AuditSink):
    """Emit each event as one JSON line to a logger (default ``agno.authz.audit``)."""

    def __init__(self, logger_name: str = "agno.authz.audit", level: int = logging.INFO):
        self._logger = logging.getLogger(logger_name)
        self._level = level

    def record(self, event: AuditEvent) -> None:
        self._logger.log(self._level, json.dumps(event.to_dict()))


def _is_decision(action: str) -> bool:
    """Decision events (``access.allowed`` / ``access.denied``) vs change events."""
    return action.startswith("access.")


class DbAuditSink(AuditSink):
    """Append-only audit tables in your own DB (SQLAlchemy).

    The two kinds of audit are kept in two physically separate tables, because
    they answer different questions, have different shapes, and grow at very
    different rates:

    - **changes** (``authz_audit``): who granted/changed a role, with before/after.
      Low volume, one row per admin action.
    - **decisions** (``authz_decisions``): every allow/deny on a request, with the
      required scopes, the granted scopes, and a non-secret token reference. High
      volume, one row per protected request.

    Keeping them apart means a decision-log flood never buries the change trail,
    each table has only the columns it needs, and you can retain/export them on
    different schedules. ``record()`` routes by action; you read each side with
    :meth:`read` (changes) and :meth:`read_decisions`.

    Writes are INSERT-only — rows are never updated or deleted — so both tables are
    tamper-evident trails suitable for SOC2-style evidence. Point it at the same DB
    as the role store or a separate one.
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        engine: Optional[Any] = None,
        table_name: str = "authz_audit",
        decision_table_name: str = "authz_decisions",
        create_table: bool = True,
        db: Optional[Any] = None,
    ):
        import sqlalchemy as sa

        if db is not None and engine is None:
            from agno.os.authz._db import engine_from_db

            engine = engine_from_db(db)
        if engine is None and db_url is None:
            raise ValueError("DbAuditSink needs one of: db (an agno Db), engine, or db_url")
        self._engine = engine if engine is not None else sa.create_engine(db_url)  # type: ignore[arg-type]
        metadata = sa.MetaData()
        # change trail: role/assignment mutations with before/after
        self._table = sa.Table(
            table_name,
            metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("actor", sa.String(255)),
            sa.Column("action", sa.String(255), nullable=False),
            sa.Column("target", sa.String(255), nullable=False),
            sa.Column("before", sa.Text),
            sa.Column("after", sa.Text),
        )
        # decision trail: per-request allow/deny with the token reference
        self._decisions = sa.Table(
            decision_table_name,
            metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("actor", sa.String(255)),
            sa.Column("action", sa.String(255), nullable=False),  # access.allowed / access.denied
            sa.Column("target", sa.String(512), nullable=False),  # "METHOD /path"
            sa.Column("token_ref", sa.String(255)),  # jti (preferred) or short hash — never the token
            sa.Column("required", sa.Text),  # scopes the route required (JSON)
            sa.Column("scopes", sa.Text),  # scopes the caller had (JSON)
        )
        if create_table:
            metadata.create_all(self._engine)

    def record(self, event: AuditEvent) -> None:
        if _is_decision(event.action):
            self._record_decision(event)
        else:
            self._record_change(event)

    def _record_change(self, event: AuditEvent) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                self._table.insert().values(
                    created_at=event.timestamp,
                    actor=event.actor,
                    action=event.action,
                    target=event.target,
                    before=json.dumps(event.before) if event.before is not None else None,
                    after=json.dumps(event.after) if event.after is not None else None,
                )
            )

    def _record_decision(self, event: AuditEvent) -> None:
        meta = event.metadata or {}
        with self._engine.begin() as conn:
            conn.execute(
                self._decisions.insert().values(
                    created_at=event.timestamp,
                    actor=event.actor,
                    action=event.action,
                    target=event.target,
                    token_ref=meta.get("token"),
                    required=json.dumps(meta.get("required")) if meta.get("required") is not None else None,
                    scopes=json.dumps(meta.get("scopes")) if meta.get("scopes") is not None else None,
                )
            )

    # Both trails read the same way: sortable, searchable pages over the columns
    # the two tables share (AUDIT_SORT_FIELDS / AUDIT_SEARCH_FIELDS). Only the
    # row shape differs, so read()/read_decisions() are thin mappers over these
    # two helpers.
    @staticmethod
    def _search_clause(table, search: str):
        import sqlalchemy as sa

        pattern = f"%{search}%"
        return sa.or_(*(table.c[f].ilike(pattern) for f in AUDIT_SEARCH_FIELDS))

    def _select_page(
        self, table, limit: int, offset: int, search: Optional[str], sort_by: str, order: str
    ) -> List[Any]:
        import sqlalchemy as sa

        if sort_by not in AUDIT_SORT_FIELDS:
            raise ValueError(f"sort_by must be one of {AUDIT_SORT_FIELDS}, got {sort_by!r}")
        stmt = sa.select(table)
        if search:
            stmt = stmt.where(self._search_clause(table, search))
        # For time order, sort on id: it's monotonic and finer-grained than ts
        # (second resolution). id also tie-breaks every other field.
        cols = (table.c.id,) if sort_by == DEFAULT_AUDIT_SORT_FIELD else (table.c[sort_by], table.c.id)
        order_by = [c.asc() if order == "asc" else c.desc() for c in cols]
        with self._engine.connect() as conn:
            return list(conn.execute(stmt.order_by(*order_by).limit(limit).offset(offset)).mappings().all())

    def _count(self, table, search: Optional[str]) -> int:
        import sqlalchemy as sa

        stmt = sa.select(sa.func.count()).select_from(table)
        if search:
            stmt = stmt.where(self._search_clause(table, search))
        with self._engine.connect() as conn:
            return int(conn.execute(stmt).scalar() or 0)

    def read(
        self,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        sort_by: str = DEFAULT_AUDIT_SORT_FIELD,
        order: str = DEFAULT_AUDIT_SORT_ORDER,
    ) -> List[dict]:
        """A page of *change* events as plain dicts (newest first by default;
        ``sort_by`` one of :attr:`SORTABLE_FIELDS`, ``order`` asc|desc)."""
        return [
            {
                "created_at": r["created_at"],
                "actor": r["actor"],
                "action": r["action"],
                "target": r["target"],
                "before": json.loads(r["before"]) if r["before"] else None,
                "after": json.loads(r["after"]) if r["after"] else None,
            }
            for r in self._select_page(self._table, limit, offset, search, sort_by, order)
        ]

    def read_decisions(
        self,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        sort_by: str = DEFAULT_AUDIT_SORT_FIELD,
        order: str = DEFAULT_AUDIT_SORT_ORDER,
    ) -> List[dict]:
        """A page of *decision* events as plain dicts (newest first by default;
        ``sort_by`` one of :attr:`SORTABLE_FIELDS`, ``order`` asc|desc).
        ``target`` is ``METHOD /path``.

        ``metadata`` is reassembled to the same ``{required, token, scopes}`` shape
        the in-memory event carried, so readers don't care which table it came from.
        """
        return [
            {
                "created_at": r["created_at"],
                "actor": r["actor"],
                "action": r["action"],
                "target": r["target"],
                "metadata": {
                    "required": json.loads(r["required"]) if r["required"] else None,
                    "token": r["token_ref"],
                    "scopes": json.loads(r["scopes"]) if r["scopes"] else None,
                },
            }
            for r in self._select_page(self._decisions, limit, offset, search, sort_by, order)
        ]

    def count(self, search: Optional[str] = None) -> int:
        """Total number of change events (for pagination), honouring ``search``."""
        return self._count(self._table, search)

    def count_decisions(self, search: Optional[str] = None) -> int:
        """Total number of decision events (for pagination), honouring ``search``."""
        return self._count(self._decisions, search)
