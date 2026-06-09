"""Managed roles for AgentOS — agno-native API, Casbin hidden inside.

This is the "governance product" middle tier: create roles, assign them, and
change them at runtime, persisted to your own DB. You work entirely in agno
scope terms (``agents:*:read``, ``agents:research-agent:run``,
``agent_os:admin``); you never write a Casbin model or policy. Casbin + a DB
adapter is the engine under the hood (so changes persist and take effect on the
next request, no token re-mint), but it is an implementation detail.

Requires the optional extra: ``pip install "agno[roles]"``.

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
from agno.os.authz.casbin_provider import scope_to_obj_act

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink

# Policies carry an effect (``eft``) so a role can explicitly DENY a scope, not
# just grant it. Deny overrides allow (``some(allow) && !some(deny)``), matching
# the cloud RBAC semantics where a scope's ``value`` is allow|deny.
_MODEL_TEXT = """
[request_definition]
r = sub, obj, act
[policy_definition]
p = sub, obj, act, eft
[role_definition]
g = _, _
[policy_effect]
e = some(where (p.eft == allow)) && !some(where (p.eft == deny))
[matchers]
m = g(r.sub, p.sub) && (p.obj == "*" || keyMatch2(r.obj, p.obj)) && (p.act == "*" || r.act == p.act)
"""

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


def _obj_act_to_scope(obj: str, act: str) -> str:
    """Best-effort reverse of :func:`scope_to_obj_act`, for display/read-back.

    Lossy where two scope spellings collapse to the same policy (``agents:read``
    and ``agents:*:read`` both store as ``("agents/*", "read")``); we render the
    global ``resource:action`` form in that case.
    """
    if obj == "*":
        return "agent_os:admin"
    if obj.endswith("/*"):
        return f"{obj[:-2]}:{act}"
    resource, _, rid = obj.partition("/")
    return f"{resource}:{rid}:{act}"


class ManagedRoleStore:
    """Runtime-mutable, persisted role store. agno-native in, Casbin hidden."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        roles_claim: Optional[str] = None,
        audit: Optional["AuditSink"] = None,
        decision_log: bool = False,
        db: Optional[Any] = None,
    ):
        """
        Args:
            db_url: SQLAlchemy URL for the DB that holds the policy (e.g.
                ``postgresql+psycopg://...`` or ``sqlite:///roles.db``). Use your
                own database. If omitted (and no ``db``), the store is in-memory
                (not persisted) — fine for tests, not for production.
            roles_claim: JWT claim carrying a caller's roles (the external-IdP
                case). When absent, roles come from this store's own assignments
                (the no-IdP case). Both are served by the same store.
            audit: optional :class:`~agno.os.authz.audit.AuditSink`. When set,
                every role/assignment change emits an append-only AuditEvent with
                the acting principal and the before/after (the change audit the
                policy engine can't give you, since it never sees the actor).
            decision_log: when True, bump the ``casbin.enforcer`` logger to INFO so
                *allow* decisions are logged too (denies are already at WARNING).
                Off by default so we don't touch global logging behind your back.
            db: an agno database (the same object you pass to ``AgentOS(db=...)``,
                e.g. ``SqliteDb``/``PostgresDb``). Its SQLAlchemy engine is reused,
                so roles live in the same database as your agent data with one
                connection pool — no second ``db_url`` to keep in sync. Takes
                precedence over ``db_url``.
        """
        try:
            import casbin  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "ManagedRoleStore needs the optional managed-roles extra. "
                'Install it with: pip install "agno[roles]"'
            ) from e

        import casbin

        model = casbin.Model()
        model.load_model_from_text(_MODEL_TEXT)
        adapter_target = _engine_from_db(db) if db is not None else db_url
        if adapter_target is not None:
            from casbin_sqlalchemy_adapter import Adapter

            self._enforcer = casbin.Enforcer(model, Adapter(adapter_target))
        else:
            self._enforcer = casbin.Enforcer(model)
        self._enforcer.enable_auto_save(True)  # mutations persist immediately
        self._roles_claim = roles_claim
        self._audit = audit

        # Role metadata (display name / description / is_default / timestamps).
        # Casbin only stores policies, so metadata needs its own table; reuse the
        # same DB when one is configured, else keep it in memory.
        self._meta_mem: Optional[Dict[str, dict]] = None
        self._meta_engine = None
        self._meta_table = None
        if db is not None:
            self._init_meta_table(_engine_from_db(db))
        elif db_url is not None:
            import sqlalchemy as sa

            self._init_meta_table(sa.create_engine(db_url))
        else:
            self._meta_mem = {}

        if decision_log:
            import logging

            logging.getLogger("casbin.enforcer").setLevel(logging.INFO)

    def _emit(
        self,
        action: str,
        target: str,
        before: Optional[List[str]],
        after: Optional[List[str]],
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
        before = self.get_role_scopes(role) if self._audit else None
        self._enforcer.remove_filtered_policy(0, role)
        for entry in scopes:
            scope, effect = _normalize_scope(entry)
            obj, act = scope_to_obj_act(scope)
            self._enforcer.add_policy(role, obj, act, effect)
        self._meta_upsert(role, name=name, description=description, is_default=is_default)
        self._emit("role.set_scopes", role, before, self.get_role_scopes(role) if self._audit else None, actor)

    def get_role_scopes(self, role: str) -> List[str]:
        """Return a role's scope strings (allow + deny), for display/read-back."""
        return sorted(
            _obj_act_to_scope(p[1], p[2]) for p in self._enforcer.get_filtered_policy(0, role) if len(p) >= 3
        )

    def get_role_scope_entries(self, role: str) -> List[dict]:
        """Return a role's scopes with effects: ``[{"scope": ..., "effect": ...}]``."""
        entries = []
        for p in self._enforcer.get_filtered_policy(0, role):
            if len(p) >= 3:
                effect = p[3] if len(p) >= 4 else "allow"
                entries.append({"scope": _obj_act_to_scope(p[1], p[2]), "effect": effect})
        return sorted(entries, key=lambda e: (e["scope"], e["effect"]))

    def get_role(self, role: str) -> Optional[dict]:
        """Full role record: metadata + scope entries, or None if the role has
        neither policies nor metadata."""
        scopes = self.get_role_scope_entries(role)
        meta = self._meta_get(role)
        if meta is None and not scopes:
            return None
        return {**self._meta_or_default(role), "scopes": scopes}

    def remove_role(self, role: str, actor: Optional[str] = None) -> None:
        before = self.get_role_scopes(role) if self._audit else None
        self._enforcer.remove_filtered_policy(0, role)
        self._enforcer.remove_filtered_grouping_policy(1, role)
        self._meta_delete(role)
        self._emit("role.removed", role, before, None, actor)

    def list_roles(self) -> List[str]:
        """All role slugs (those with policies and/or metadata)."""
        slugs = {p[0] for p in self._enforcer.get_policy()}
        if self._meta_mem is not None:
            slugs |= set(self._meta_mem.keys())
        elif self._meta_engine is not None:
            import sqlalchemy as sa

            with self._meta_engine.connect() as conn:
                slugs |= {r[0] for r in conn.execute(sa.select(self._meta_table.c.slug))}  # type: ignore[union-attr]
        return sorted(slugs)

    def list_roles_detailed(self) -> List[dict]:
        """Every role as a full record (metadata + scope entries)."""
        return [self.get_role(slug) for slug in self.list_roles()]  # type: ignore[misc]

    # ------------------------------------------------------------- assignments
    def assign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Give a subject a role (runtime, persisted)."""
        before = self.roles_of(subject) if self._audit else None
        self._enforcer.add_role_for_user(subject, role)
        self._emit("user.assigned", subject, before, self.roles_of(subject) if self._audit else None, actor)

    def unassign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        before = self.roles_of(subject) if self._audit else None
        self._enforcer.delete_role_for_user(subject, role)
        self._emit("user.unassigned", subject, before, self.roles_of(subject) if self._audit else None, actor)

    def roles_of(self, subject: str) -> List[str]:
        return list(self._enforcer.get_roles_for_user(subject))

    # ------------------------------------------------------------------ audit
    def audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Recent change-audit events (newest first), if the audit sink supports
        reading (e.g. ``DbAuditSink``). Returns ``[]`` when no readable sink is
        configured (e.g. a logging-only sink, or no audit at all)."""
        sink = self._audit
        if sink is not None and hasattr(sink, "read"):
            return sink.read(limit)
        return []

    # ----------------------------------------------------------------- gating
    def can_manage(self, principal_id: Optional[str], claims: Optional[Dict[str, Any]] = None) -> bool:
        """True if the caller may administer roles (i.e. satisfies ``agent_os:admin``).

        Only full admins manage the role store. An admin can be defined two ways,
        both handled here:
          - by a role in this store (``enforce(sub, "*", "*")``), or
          - by a role carried on the token, when ``roles_claim`` is set.
        Note this is intentionally NOT the generic provider ``check`` (which
        defers non-resource decisions to route scope mappings and would let any
        authenticated caller through).
        """
        if self._roles_claim and claims:
            roles = claims.get(self._roles_claim)
            if isinstance(roles, str):  # e.g. WorkOS sends a single "role" string
                roles = [roles]
            if isinstance(roles, list):
                if any(bool(self._enforcer.enforce(r, "*", "*")) for r in roles):
                    return True
        if principal_id:
            return bool(self._enforcer.enforce(principal_id, "*", "*"))
        return False

    # --------------------------------------------------------------- provider
    @property
    def provider(self):
        """The AuthorizationProvider to plug into AuthorizationConfig."""
        from agno.os.authz.casbin_provider import CasbinAuthorizationProvider

        return CasbinAuthorizationProvider(self._enforcer, roles_claim=self._roles_claim)
