"""Audit trail for authorization changes.

There are two kinds of "audit" people mean:

1. Decision audit ("was alice allowed to run agent X?") — Casbin already logs
   every ``enforce()`` to the ``casbin.enforcer`` Python logger (deny at WARNING,
   allow at INFO). Route that logger to your sink; ``ManagedRoleStore(decision_log=True)``
   just bumps it to INFO so allows are captured too.

2. Change audit ("who granted alice the admin role, when, before/after?") — Casbin
   cannot provide this: its management API never sees the acting principal, and
   ``casbin_rule`` is overwrite-in-place with no history. So it must be captured at
   the layer that knows the actor — the management API / store. That is what this
   module is for.

Plug an :class:`AuditSink` into :class:`~agno.os.authz.role_store.ManagedRoleStore`
(directly or via ``get_roles_router``) and every role/assignment mutation emits a
structured, append-only :class:`AuditEvent` with the actor and the before/after.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class AuditEvent:
    """One authorization-change record. Append-only; never mutated after emit.

    Attributes:
        action: what happened — ``role.set_scopes`` / ``role.removed`` /
            ``user.assigned`` / ``user.unassigned``.
        actor: the principal who made the change (JWT ``sub`` of the admin), or
            None for changes made in code outside a request (treated as system).
        target: the role name (role changes) or subject id (assignment changes).
        before: prior state (the role's scopes, or the subject's roles), or None.
        after: new state, or None (e.g. on removal).
        timestamp: epoch seconds when the change was recorded.
    """

    action: str
    actor: Optional[str]
    target: str
    before: Optional[List[str]] = None
    after: Optional[List[str]] = None
    timestamp: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ts": self.timestamp,
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


class DbAuditSink(AuditSink):
    """Append-only audit table in your own DB (SQLAlchemy).

    Writes are INSERT-only — rows are never updated or deleted — so the table is a
    tamper-evident trail suitable for SOC2-style evidence. Point it at the same DB
    as the role store or a separate one.
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        engine: Optional[Any] = None,
        table_name: str = "authz_audit",
        create_table: bool = True,
    ):
        import sqlalchemy as sa

        if engine is None and db_url is None:
            raise ValueError("DbAuditSink needs either db_url or engine")
        self._engine = engine if engine is not None else sa.create_engine(db_url)
        metadata = sa.MetaData()
        self._table = sa.Table(
            table_name,
            metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("ts", sa.Integer, nullable=False),
            sa.Column("actor", sa.String(255)),
            sa.Column("action", sa.String(255), nullable=False),
            sa.Column("target", sa.String(255), nullable=False),
            sa.Column("before", sa.Text),
            sa.Column("after", sa.Text),
        )
        if create_table:
            metadata.create_all(self._engine)

    def record(self, event: AuditEvent) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                self._table.insert().values(
                    ts=event.timestamp,
                    actor=event.actor,
                    action=event.action,
                    target=event.target,
                    before=json.dumps(event.before) if event.before is not None else None,
                    after=json.dumps(event.after) if event.after is not None else None,
                )
            )

    def read(self, limit: int = 100) -> List[dict]:
        """Return the most recent events (newest first) as plain dicts."""
        import sqlalchemy as sa

        with self._engine.connect() as conn:
            rows = (
                conn.execute(sa.select(self._table).order_by(self._table.c.id.desc()).limit(limit))
                .mappings()
                .all()
            )
        return [
            {
                "ts": r["ts"],
                "actor": r["actor"],
                "action": r["action"],
                "target": r["target"],
                "before": json.loads(r["before"]) if r["before"] else None,
                "after": json.loads(r["after"]) if r["after"] else None,
            }
            for r in rows
        ]
