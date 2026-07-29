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
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.utils.log import log_debug

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
    metadata: Dict[str, Any] = field(default_factory=dict)

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


def resolve_audit_sink(app_or_request: Any) -> Optional[AuditSink]:
    """The AuditSink recording this AgentOS's decisions, or None if none is configured.

    Accepts a FastAPI ``app``, a ``Request`` or a ``WebSocket`` (``.app`` is read from
    the latter two), mirroring ``resolve_authorization_provider`` so every choke point
    can resolve the sink with whatever object it holds.
    """
    app = getattr(app_or_request, "app", app_or_request)
    return getattr(getattr(app, "state", None), "authz_audit", None)


def token_reference(token: Optional[str], claims: Optional[Dict[str, Any]]) -> Optional[str]:
    """A non-secret reference to the presented token, for the decision trail.

    Prefer the token's ``jti`` (RFC 7519 JWT ID): an opaque identifier the issuer
    already minted, so it correlates to the issuer's own logs and any revocation list.
    When the token has no ``jti``, fall back to a short SHA-256 of the raw token so two
    distinct tokens stay distinguishable -- without ever storing the credential itself.
    """
    if claims:
        jti = claims.get("jti")
        if jti:
            return str(jti)
    if token:
        import hashlib

        return hashlib.sha256(token.encode()).hexdigest()[:12]
    return None


def record_decision(
    app_or_request: Any,
    *,
    allowed: bool,
    target: str,
    principal: Optional[str],
    required_scopes: Optional[List[str]] = None,
    scopes: Optional[List[str]] = None,
    claims: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """Record ONE authorization decision to the configured sink.

    This is shared by every enforcement choke point -- the REST route gate, the
    per-resource gate, the WebSocket gates and the MCP tool gate -- so the access
    trail covers all of them rather than only the transport that happens to run
    inside the JWT middleware. ``target`` is the thing being decided on, formatted
    like the route it corresponds to (e.g. ``"POST /agents/x/runs"``).

    Never raises into the request path: an audit failure must not turn a served
    request into a 500. No-op when no sink is configured, so the default (no audit)
    deployment is untouched.
    """
    sink = resolve_audit_sink(app_or_request)
    if sink is None:
        return
    try:
        metadata: Dict[str, Any] = {
            "required": list(required_scopes or []),
            "token": token_reference(token, claims),
            "scopes": list(scopes or []),
        }
        if reason:
            metadata["reason"] = reason
        sink.record(
            AuditEvent(
                action="access.allowed" if allowed else "access.denied",
                actor=principal,
                target=target,
                timestamp=int(time.time()),
                metadata=metadata,
            )
        )
    except Exception as e:  # pragma: no cover - audit must never break requests
        log_debug(f"decision audit failed: {e}")


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
        from agno.os.authz._db import require_authz_db, resolve_authz_db

        if db is None and db_url is None and engine is None:
            raise ValueError("DbAuditSink needs one of: db (an agno Db), or db_url")
        if engine is not None and db is None and db_url is None:
            raise ValueError(
                "DbAuditSink(engine=...) is no longer supported: audit rows are written through the "
                "agno database contract so they honour its schema and table names. Pass db=<an agno Db> "
                "or db_url=... instead."
            )
        self._db: Any = resolve_authz_db(db, db_url)
        require_authz_db(self._db)

    def record(self, event: AuditEvent) -> None:
        # The AuditSink contract is that record() must NOT raise into the caller's
        # path: a role change (or a request) must still succeed even if its audit row
        # can't be written. Log and swallow DB errors rather than turning a
        # successful mutation into a 500 with no audit row.
        try:
            if _is_decision(event.action):
                self._record_decision(event)
            else:
                self._record_change(event)
        except Exception:
            logging.getLogger("agno.authz.audit").exception("failed to write audit event %r", event.action)

    def _record_change(self, event: AuditEvent) -> None:
        self._db.record_authz_audit_event(
            {
                "event_id": uuid4().hex,
                "created_at": event.timestamp,
                "actor": event.actor,
                "action": event.action,
                "target": event.target,
                "before": json.dumps(event.before) if event.before is not None else None,
                "after": json.dumps(event.after) if event.after is not None else None,
            }
        )

    def _record_decision(self, event: AuditEvent) -> None:
        meta = event.metadata or {}
        self._db.record_authz_decision(
            {
                "event_id": uuid4().hex,
                "created_at": event.timestamp,
                "actor": event.actor,
                "action": event.action,
                "target": event.target,
                "token_ref": meta.get("token"),
                "required": json.dumps(meta.get("required")) if meta.get("required") is not None else None,
                "scopes": json.dumps(meta.get("scopes")) if meta.get("scopes") is not None else None,
            }
        )

    # Both trails read the same way: sortable, searchable pages over the columns
    # the two tables share (AUDIT_SORT_FIELDS / AUDIT_SEARCH_FIELDS). Only the
    # row shape differs, so read()/read_decisions() are thin mappers over these
    # two helpers.
    def _select_page(
        self, decisions: bool, limit: int, offset: int, search: Optional[str], sort_by: str, order: str
    ) -> List[Any]:
        if sort_by not in AUDIT_SORT_FIELDS:
            raise ValueError(f"sort_by must be one of {AUDIT_SORT_FIELDS}, got {sort_by!r}")
        return self._db.read_authz_audit_events(
            limit=limit, offset=offset, search=search, sort_by=sort_by, order=order, decisions=decisions
        )

    def _count(self, decisions: bool, search: Optional[str]) -> int:
        return int(self._db.count_authz_audit_events(search=search, decisions=decisions))

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
            for r in self._select_page(False, limit, offset, search, sort_by, order)
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
            for r in self._select_page(True, limit, offset, search, sort_by, order)
        ]

    def count(self, search: Optional[str] = None) -> int:
        """Total number of change events (for pagination), honouring ``search``."""
        return self._count(False, search)

    def count_decisions(self, search: Optional[str] = None) -> int:
        """Total number of decision events (for pagination), honouring ``search``."""
        return self._count(True, search)
