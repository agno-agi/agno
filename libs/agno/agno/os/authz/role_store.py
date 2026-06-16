"""Managed roles for AgentOS — agno-native API, native policy engine inside.

This is the "governance product" middle tier: create roles, assign them, and
change them at runtime, persisted to your own DB. You work entirely in agno
scope terms (``agents:*:read``, ``agents:research-agent:run``,
``agent_os:admin``). The decision engine underneath is agno's own
:class:`~agno.os.authz.native_engine.NativePolicyEngine` (deny-overrides RBAC, no
third-party dependency). The engine is swappable behind the :class:`PolicyEngine`
port. A change persists and takes effect on the next request **in that process**;
across multiple workers/replicas the others pick it up on reload — pass
``reload_interval=<seconds>`` for bounded auto-refresh, or call :meth:`reload`.

Persistence to a DB needs SQLAlchemy: ``pip install "agno[roles]"`` (or ``agno[os]``).

Example::

    store = ManagedRoleStore(db_url="postgresql+psycopg://...", roles_claim="roles")
    store.set_role_scopes("member", ["agents:*:read", "agents:research-agent:run"])
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("bob", "member")           # runtime, persisted

    agent_os = AgentOS(
        agents=[...],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[...],
            authorization_provider=store.provider,   # plug it in
        ),
    )

    # later, live (no redeploy, same token):
    store.assign("carol", "member")
    store.unassign("bob", "member")
"""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from agno.os.authz._db import engine_from_db as _engine_from_db
from agno.os.authz.audit import DEFAULT_AUDIT_SORT_FIELD, DEFAULT_AUDIT_SORT_ORDER
from agno.os.authz.engine import EngineAuthorizationProvider, PolicyEngine

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink

# A scope plus its effect. Inputs accept a bare string (= allow), a (scope, effect)
# tuple, or a {"scope": ..., "effect"|"value": ...} dict.
ScopeInput = Union[str, Tuple[str, str], Dict[str, str]]


def _normalize_scope(entry: ScopeInput) -> Tuple[str, str]:
    """Coerce a scope input into ``(scope, effect)`` with effect in {allow, deny}."""
    if isinstance(entry, str):
        scope, effect = entry, "allow"
    elif isinstance(entry, dict):
        scope = entry.get("scope") or entry.get("raw")  # type: ignore[assignment]
        effect = entry.get("effect") or entry.get("value") or "allow"
    else:  # tuple/list
        scope, effect = entry[0], (entry[1] if len(entry) > 1 else "allow")
    if not scope:
        raise ValueError(f"Unrecognised scope entry: {entry!r}")
    effect = str(effect).lower()
    if effect not in ("allow", "deny"):
        raise ValueError(f"scope effect must be 'allow' or 'deny', got {effect!r}")
    return scope, effect


class ManagedRoleStore:
    """Runtime-mutable, persisted role store. agno-native API; the policy engine
    (the native engine by default) is a swappable backend behind the
    :class:`PolicyEngine` port — pass ``engine=`` to use a different one."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        roles_claim: Optional[str] = None,
        audit: Optional["AuditSink"] = None,
        decision_log: bool = False,
        db: Optional[Any] = None,
        engine: Optional[PolicyEngine] = None,
        reload_interval: Optional[float] = None,
    ):
        """
        Args:
            db_url: SQLAlchemy URL for the DB that holds the policy (e.g.
                ``postgresql+psycopg://...`` or ``sqlite:///roles.db``). Use your
                own database. If omitted (and no ``db``/``engine``), the store is
                in-memory (not persisted) — fine for tests, not for production.
            roles_claim: JWT claim carrying a caller's roles (the external-IdP
                case). When absent, roles come from this store's own assignments
                (the no-IdP case). Both are served by the same store.
            audit: optional :class:`~agno.os.authz.audit.AuditSink`. When set,
                every role/assignment change emits an append-only AuditEvent with
                the acting principal and the before/after (the change audit the
                policy engine can't give you, since it never sees the actor).
            decision_log: when True, bump the ``agno.authz.engine`` logger to INFO
                so every allow/deny decision is logged. Off by default so we don't
                touch global logging behind your back.
            db: an agno database (the same object you pass to ``AgentOS(db=...)``,
                e.g. ``SqliteDb``/``PostgresDb``). Its SQLAlchemy engine is reused,
                so roles live in the same database as your agent data with one
                connection pool — no second ``db_url`` to keep in sync. Takes
                precedence over ``db_url``.
            engine: a custom :class:`~agno.os.authz.engine.PolicyEngine` backend.
                Defaults to the native engine built from ``db``/``db_url``. Supply
                your own to swap the backend (OpenFGA/SpiceDB/...) without changing
                anything else.
            reload_interval: for the native engine, seconds after which a worker
                auto-reloads policy/assignments from the DB so multi-worker /
                multi-replica deployments pick up changes made by another process.
                None (default) = no auto-reload (single-process; or call
                :meth:`reload`). Ignored when a custom ``engine`` is supplied.
        """
        if engine is not None:
            self._engine: PolicyEngine = engine
        else:
            from agno.os.authz.native_engine import NativePolicyEngine

            self._engine = NativePolicyEngine(db_url=db_url, db=db, reload_interval=reload_interval)
        self._roles_claim = roles_claim
        self._audit = audit

        # Role metadata (display name / description / is_default / timestamps).
        # The policy engine only stores policies, so metadata needs its own table;
        # reuse the same DB when one is configured, else keep it in memory.
        self._meta_mem: Optional[Dict[str, dict]] = None
        self._meta_engine: Any = None  # SQLAlchemy Engine when db-backed, else None
        self._meta_table: Any = None  # SQLAlchemy Table for authz_roles metadata
        if db is not None:
            self._init_meta_table(_engine_from_db(db))
        elif db_url is not None:
            import sqlalchemy as sa

            self._init_meta_table(sa.create_engine(db_url))
        else:
            self._meta_mem = {}

        if decision_log:
            import logging

            logging.getLogger("agno.authz.engine").setLevel(logging.INFO)

    def _emit(
        self,
        action: str,
        target: str,
        before: Optional[List[Any]],
        after: Optional[List[Any]],
        actor: Optional[str],
    ) -> None:
        """Record one change to the audit sink (no-op when no sink is configured)."""
        if self._audit is None:
            return
        import time

        from agno.os.authz.audit import AuditEvent

        self._audit.record(
            AuditEvent(
                action=action,
                actor=actor,
                target=target,
                before=before,
                after=after,
                timestamp=int(time.time()),
            )
        )

    # --------------------------------------------------------- role metadata
    def _init_meta_table(self, engine: Any) -> None:
        import sqlalchemy as sa

        self._meta_engine = engine
        metadata = sa.MetaData()
        self._meta_table = sa.Table(
            "authz_roles",
            metadata,
            sa.Column("slug", sa.String(255), primary_key=True),  # = the role id/name
            sa.Column("name", sa.String(255)),  # human-readable display name
            sa.Column("description", sa.Text),
            sa.Column("is_default", sa.Boolean, nullable=False, default=False),
            sa.Column("created_at", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.Integer, nullable=False),
        )
        metadata.create_all(self._meta_engine)

    def _meta_get(self, slug: str) -> Optional[dict]:
        if self._meta_mem is not None:
            row = self._meta_mem.get(slug)
            return dict(row) if row else None
        import sqlalchemy as sa

        with self._meta_engine.connect() as conn:  # type: ignore[union-attr]
            r = conn.execute(sa.select(self._meta_table).where(self._meta_table.c.slug == slug)).mappings().first()  # type: ignore[union-attr]
        return dict(r) if r else None

    def _meta_get_all(self) -> dict:
        """All metadata rows as ``{slug: row}`` in a single read, so list views
        don't do one SELECT per role (N+1)."""
        if self._meta_mem is not None:
            return {slug: dict(row) for slug, row in self._meta_mem.items()}
        import sqlalchemy as sa

        with self._meta_engine.connect() as conn:  # type: ignore[union-attr]
            rows = conn.execute(sa.select(self._meta_table)).mappings().all()  # type: ignore[union-attr]
        return {r["slug"]: dict(r) for r in rows}

    def _meta_upsert(
        self,
        slug: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> dict:
        existing = self._meta_get(slug)
        now = int(time.time())
        if existing is None:
            row = {
                "slug": slug,
                "name": name or slug,
                "description": description,
                "is_default": bool(is_default) if is_default is not None else False,
                "created_at": now,
                "updated_at": now,
            }
        else:
            row = dict(existing)
            if name is not None:
                row["name"] = name
            if description is not None:
                row["description"] = description
            if is_default is not None:
                row["is_default"] = bool(is_default)
            row["updated_at"] = now
        self._meta_write(row, insert=existing is None)
        return row

    def _meta_write(self, row: dict, insert: bool) -> None:
        if self._meta_mem is not None:
            self._meta_mem[row["slug"]] = dict(row)
            return
        import sqlalchemy as sa

        with self._meta_engine.begin() as conn:  # type: ignore[union-attr]
            if insert:
                conn.execute(sa.insert(self._meta_table).values(**row))  # type: ignore[union-attr]
            else:
                conn.execute(sa.update(self._meta_table).where(self._meta_table.c.slug == row["slug"]).values(**row))  # type: ignore[union-attr]

    def _meta_delete(self, slug: str) -> None:
        if self._meta_mem is not None:
            self._meta_mem.pop(slug, None)
            return
        import sqlalchemy as sa

        with self._meta_engine.begin() as conn:  # type: ignore[union-attr]
            conn.execute(sa.delete(self._meta_table).where(self._meta_table.c.slug == slug))  # type: ignore[union-attr]

    def _meta_or_default(self, slug: str) -> dict:
        """Metadata for a role, synthesising defaults for rows defined before
        metadata existed (or via the raw enforcer)."""
        meta = self._meta_get(slug)
        if meta is not None:
            return meta
        return {"slug": slug, "name": slug, "description": None, "is_default": False, "created_at": 0, "updated_at": 0}

    # ------------------------------------------------------------------ roles
    def set_role_scopes(
        self,
        role: str,
        scopes: List[ScopeInput],
        actor: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> None:
        """Define (or replace) what a role can do, in agno scope terms.

        ``scopes`` items may be plain strings (granted/allow), ``(scope, effect)``
        tuples, or ``{"scope": ..., "effect": "allow"|"deny"}`` dicts. Also creates
        / updates the role's metadata (display ``name`` / ``description`` /
        ``is_default``)."""
        # Audit the full entries (scope + effect) so an allow<->deny flip is visible
        # in the trail; plain scope strings would show no change.
        before = self.get_role_scope_entries(role) if self._audit else None
        self._engine.set_role_scopes(role, [_normalize_scope(e) for e in scopes])
        self._meta_upsert(role, name=name, description=description, is_default=is_default)
        self._emit("role.set_scopes", role, before, self.get_role_scope_entries(role) if self._audit else None, actor)

    def get_role_scopes(self, role: str) -> List[str]:
        """Return a role's scope strings (allow + deny), for display/read-back."""
        return sorted(scope for scope, _ in self._engine.get_role_scopes(role))

    def get_role_scope_entries(self, role: str) -> List[dict]:
        """Return a role's scopes with effects: ``[{"scope": ..., "effect": ...}]``."""
        entries = [{"scope": scope, "effect": effect} for scope, effect in self._engine.get_role_scopes(role)]
        return sorted(entries, key=lambda e: (e["scope"], e["effect"]))

    def create_role(
        self,
        role: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Create a role with metadata only — no scopes (add those via
        set_role_scopes / patch_role_scopes). Raises FileExistsError if it exists."""
        if self.get_role(role) is not None:
            raise FileExistsError(role)
        rec = self._meta_upsert(role, name=name, description=description, is_default=is_default)
        self._emit("role.created", role, None, [self._meta_summary(rec)], actor)
        return rec

    def set_role_meta(
        self,
        role: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Update ONLY a role's metadata (display name / description / is_default),
        leaving its scopes untouched. Raises KeyError if the role doesn't exist."""
        if self.get_role(role) is None:
            raise KeyError(role)
        before = self._meta_or_default(role)
        rec = self._meta_upsert(role, name=name, description=description, is_default=is_default)
        self._emit("role.updated", role, [self._meta_summary(before)], [self._meta_summary(rec)], actor)
        return rec

    def patch_role_scopes(
        self,
        role: str,
        upsert: Optional[List[ScopeInput]] = None,
        remove: Optional[List[ScopeInput]] = None,
        actor: Optional[str] = None,
    ) -> None:
        """Apply a scope diff: add/flip the ``upsert`` scopes and drop the ``remove``
        scopes, leaving every other scope (and the metadata) intact."""
        before = self.get_role_scope_entries(role) if self._audit else None
        for entry in upsert or []:
            scope, effect = _normalize_scope(entry)
            self._engine.add_scope(role, scope, effect)
        for entry in remove or []:
            scope, _ = _normalize_scope(entry)
            self._engine.remove_scope(role, scope)
        self._meta_upsert(role)  # touch updated_at / ensure metadata row exists
        self._emit("role.set_scopes", role, before, self.get_role_scope_entries(role) if self._audit else None, actor)

    @staticmethod
    def _meta_summary(rec: dict) -> str:
        bits = [rec.get("name") or rec["slug"]]
        if rec.get("description"):
            bits.append(str(rec["description"]))
        if rec.get("is_default"):
            bits.append("default")
        return " · ".join(bits)

    def get_role(self, role: str) -> Optional[dict]:
        """Full role record: metadata + scope entries, or None if the role has
        neither policies nor metadata."""
        scopes = self.get_role_scope_entries(role)
        meta = self._meta_get(role)
        if meta is None and not scopes and role not in self._engine.list_roles():
            # No metadata, no scopes, and not even an assignment-only role -> absent.
            return None
        return {**self._meta_or_default(role), "scopes": scopes}

    def remove_role(self, role: str, actor: Optional[str] = None) -> None:
        before = self.get_role_scopes(role) if self._audit else None
        self._engine.remove_role(role)
        self._meta_delete(role)
        self._emit("role.removed", role, before, None, actor)

    def list_roles(self) -> List[str]:
        """All role slugs (those with policies and/or metadata)."""
        slugs = set(self._engine.list_roles())
        if self._meta_mem is not None:
            slugs |= set(self._meta_mem.keys())
        elif self._meta_engine is not None:
            import sqlalchemy as sa

            with self._meta_engine.connect() as conn:
                slugs |= {r[0] for r in conn.execute(sa.select(self._meta_table.c.slug))}  # type: ignore[union-attr]
        return sorted(slugs)

    def list_roles_detailed(self) -> List[dict]:
        """Every role as a full record (metadata + scope entries).

        Metadata is fetched in one read (not one SELECT per role), and
        assignment-only roles (a subject is assigned but no scopes/metadata exist
        yet) are surfaced with an empty scope list rather than dropped."""
        meta_all = self._meta_get_all()
        default = {"name": None, "description": None, "is_default": False, "created_at": 0, "updated_at": 0}
        out: List[dict] = []
        for slug in self.list_roles():
            meta = meta_all.get(slug) or {"slug": slug, **default, "name": slug}
            out.append({**meta, "scopes": self.get_role_scope_entries(slug)})
        return out

    # ------------------------------------------------------------- assignments
    def assign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Give a subject THE role (runtime, persisted).

        A subject holds at most ONE role at a time — assigning replaces any
        current role rather than accumulating. This mirrors the cloud RBAC model
        (a membership has one role) so role management is a select, not a
        multi-grant. Compose permissions in the role's scopes, not by stacking
        roles on a user. No-op if the subject already holds exactly this role.
        """
        before = self.roles_of(subject)
        if before == [role]:
            return  # already exactly this role; no change, no audit noise
        for existing in before:
            self._engine.unassign(subject, existing)
        self._engine.assign(subject, role)
        self._emit(
            "user.assigned",
            subject,
            before if self._audit else None,
            self.roles_of(subject) if self._audit else None,
            actor,
        )

    def unassign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        before = self.roles_of(subject) if self._audit else None
        self._engine.unassign(subject, role)
        self._emit("user.unassigned", subject, before, self.roles_of(subject) if self._audit else None, actor)

    def roles_of(self, subject: str) -> List[str]:
        return self._engine.roles_of(subject)

    def reload(self) -> None:
        """Reload roles/assignments from the DB into the engine's cache. Use in
        multi-worker / multi-replica deployments so this process picks up changes
        another process made (or set ``reload_interval`` for automatic refresh).
        No-op for in-memory or engines that don't support reloading."""
        reload_fn = getattr(self._engine, "reload", None)
        if callable(reload_fn):
            reload_fn()

    # ------------------------------------------------------------------ audit
    def audit_log(
        self,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        sort_by: str = DEFAULT_AUDIT_SORT_FIELD,
        order: str = DEFAULT_AUDIT_SORT_ORDER,
    ) -> List[Dict[str, Any]]:
        """A page of change-audit events (newest first by default), if the audit
        sink supports reading (e.g. ``DbAuditSink``). ``search`` filters over
        actor/action/target; ``sort_by`` is any of the sink's sortable fields.
        Returns ``[]`` when no readable sink is configured (e.g. a logging-only
        sink, or no audit at all)."""
        sink = self._audit
        if sink is not None and hasattr(sink, "read"):
            return sink.read(limit, offset=offset, search=search, sort_by=sort_by, order=order)
        return []

    def audit_count(self, search: Optional[str] = None) -> int:
        """Total number of change-audit events (for pagination, honouring
        ``search``); 0 when the sink isn't readable."""
        sink = self._audit
        if sink is not None and hasattr(sink, "count"):
            return int(sink.count(search=search))
        return 0

    # ----------------------------------------------------------------- gating
    def can_manage(self, principal_id: Optional[str], claims: Optional[Dict[str, Any]] = None) -> bool:
        """True if the caller may administer roles (i.e. satisfies ``agent_os:admin``).

        Admin can be defined two ways, both handled via the engine:
          - by a role in this store (subject -> agent_os:admin), or
          - by a role carried on the token, when ``roles_claim`` is set.
        Intentionally NOT the generic provider ``check`` (which defers non-resource
        decisions and would let any authenticated caller through).
        """
        roles: Optional[List[str]] = None
        if self._roles_claim and claims:
            raw = claims.get(self._roles_claim)
            if isinstance(raw, str):  # WorkOS sends a single "role" string
                raw = [raw]
            if isinstance(raw, list) and raw:
                roles = raw
        return self._engine.check_scope("agent_os:admin", subject=principal_id, roles=roles)

    # --------------------------------------------------------------- provider
    @property
    def provider(self):
        """The AuthorizationProvider to plug into AuthorizationConfig (engine-backed)."""
        return EngineAuthorizationProvider(self._engine, roles_claim=self._roles_claim)
