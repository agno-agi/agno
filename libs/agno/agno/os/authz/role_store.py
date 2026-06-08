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

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.os.authz._db import engine_from_db as _engine_from_db
from agno.os.authz.casbin_provider import scope_to_obj_act

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink

_MODEL_TEXT = """
[request_definition]
r = sub, obj, act
[policy_definition]
p = sub, obj, act
[role_definition]
g = _, _
[policy_effect]
e = some(where (p.eft == allow))
[matchers]
m = g(r.sub, p.sub) && (p.obj == "*" || keyMatch2(r.obj, p.obj)) && (p.act == "*" || r.act == p.act)
"""


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

    # ------------------------------------------------------------------ roles
    def set_role_scopes(self, role: str, scopes: List[str], actor: Optional[str] = None) -> None:
        """Define (or replace) what a role can do, in agno scope terms."""
        before = self.get_role_scopes(role) if self._audit else None
        self._enforcer.remove_filtered_policy(0, role)
        for scope in scopes:
            obj, act = scope_to_obj_act(scope)
            self._enforcer.add_policy(role, obj, act)
        self._emit("role.set_scopes", role, before, self.get_role_scopes(role) if self._audit else None, actor)

    def get_role_scopes(self, role: str) -> List[str]:
        """Return a role's scopes in agno terms (best-effort read-back)."""
        return sorted(
            _obj_act_to_scope(p[1], p[2]) for p in self._enforcer.get_filtered_policy(0, role) if len(p) >= 3
        )

    def remove_role(self, role: str, actor: Optional[str] = None) -> None:
        before = self.get_role_scopes(role) if self._audit else None
        self._enforcer.remove_filtered_policy(0, role)
        self._enforcer.remove_filtered_grouping_policy(1, role)
        self._emit("role.removed", role, before, None, actor)

    def list_roles(self) -> List[str]:
        return sorted({p[0] for p in self._enforcer.get_policy()})

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
