"""Managed roles for AgentOS — agno-native API, native policy engine inside.

This is the "governance product" middle tier: create roles, assign them, and
change them at runtime, persisted to your own DB. You work entirely in agno
scope terms (``agents:*:read``, ``agents:research-agent:run``,
``agent_os:admin``). The decision engine underneath is agno's own
:class:`~agno.os.authz.native_engine.NativePolicyEngine` (deny-overrides RBAC, no
third-party dependency). The engine is swappable behind the :class:`PolicyEngine`
port. A change persists and takes effect on the next request — and, when DB-backed,
across every worker/replica, because decisions read the DB fresh (no in-process
cache to go stale).

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

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.os.authz.engine import EngineAuthorizationProvider, PolicyEngine, normalize_roles_claim

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink


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
            db: an agno database (the same object you pass to ``AgentOS(db=...)``).
                Its SQLAlchemy engine is reused, so roles live in the same database
                as your agent data. Takes precedence over ``db_url``.
            engine: a custom :class:`~agno.os.authz.engine.PolicyEngine` backend.
                Defaults to the native engine built from ``db``/``db_url``.
        """
        if engine is not None:
            self._engine: PolicyEngine = engine
        else:
            from agno.os.authz.native_engine import NativePolicyEngine

            self._engine = NativePolicyEngine(db_url=db_url, db=db)
        self._roles_claim = roles_claim
        self._audit = audit

        if decision_log:
            import logging

            logging.getLogger("agno.authz.engine").setLevel(logging.INFO)

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
        self._engine.set_role_scopes(role, [(scope, "allow") for scope in scopes])
        self._emit("role.set_scopes", role, before, self.get_role_scopes(role) if self._audit else None, actor)

    def get_role_scopes(self, role: str) -> List[str]:
        """Return a role's scopes in agno terms (best-effort read-back)."""
        return sorted(scope for scope, _effect in self._engine.get_role_scopes(role))

    def remove_role(self, role: str, actor: Optional[str] = None) -> None:
        before = self.get_role_scopes(role) if self._audit else None
        self._engine.remove_role(role)
        self._emit("role.removed", role, before, None, actor)

    def list_roles(self) -> List[str]:
        return sorted(self._engine.list_roles())

    # ------------------------------------------------------------- assignments
    def assign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Give a subject THE role (runtime, persisted).

        A subject holds at most ONE role at a time — assigning replaces any
        current role rather than accumulating. This mirrors the cloud RBAC model
        (a membership has one role). No-op if the subject already holds exactly
        this role.
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

        An admin can be defined two ways, both handled here:
          - by a role in this store, or
          - by a role carried on the token, when ``roles_claim`` is set.
        Note this is intentionally NOT the generic provider ``check`` (which
        defers non-resource decisions to route scope mappings and would let any
        authenticated caller through).
        """
        roles = normalize_roles_claim(claims, self._roles_claim)
        if roles and self._engine.check_scope("agent_os:admin", roles=roles):
            return True
        if principal_id:
            return self._engine.check_scope("agent_os:admin", subject=principal_id)
        return False

    # --------------------------------------------------------------- provider
    @property
    def provider(self) -> EngineAuthorizationProvider:
        """The AuthorizationProvider to plug into AuthorizationConfig."""
        return EngineAuthorizationProvider(self._engine, roles_claim=self._roles_claim)
