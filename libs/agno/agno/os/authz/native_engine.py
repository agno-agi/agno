"""The native managed-roles policy engine — agno's default, zero third-party deps.

A :class:`~agno.os.authz.engine.PolicyEngine` implemented directly in agno: roles
hold scopes (with allow/deny), subjects are assigned roles, and decisions use
**deny-overrides** matching the cloud RBAC semantics. No external policy engine.

Storage is **always a database** (``db`` / ``db_url``): policy + assignments live in
two SQLAlchemy tables (``authz_policy``, ``authz_grouping``) and every decision reads
them **fresh** with small indexed queries. There is no in-process cache, so a change
on one worker/replica is visible to all of them on their very next request — the
right default for AgentOS's multi-container deployments. Authz is a tiny,
index-served part of a request (which is otherwise an agent run), so the round-trips
are negligible, and a DB outage fails closed. A DB is *required*: an in-memory store
can't stay consistent across replicas, so an engine with no DB raises on any use
(see :data:`~agno.os.authz._db.NO_DB_MESSAGE`).

The decision model, in agno terms:

- a role's scopes are stored as ``(resource, action, effect)`` via the shared
  :mod:`~agno.os.authz._scope_policy` convention (deduped per ``(role, resource, action)``),
- a subject (or a token-carried role) is allowed an action on a resource iff some
  matching grant says *allow* and none says *deny* — evaluated per identity root
  and OR'd across token-carried roles, so a deny on one role can't silently veto
  an allow carried by another.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from agno.os.authz._db import NO_DB_MESSAGE
from agno.os.authz._db import engine_from_db as _engine_from_db
from agno.os.authz._db import engine_from_url as _engine_from_url
from agno.os.authz._scope_policy import resource_action_to_scope, resource_matches, scope_to_resource_action
from agno.os.authz.engine import PolicyEngine, ScopeEntry

_DENY = "deny"
_ALLOW = "allow"
# A policy row carried through the decision logic: (role, resource, action, effect).
_PolicyRow = Tuple[str, str, str, str]


def _normalize_effect(effect: str) -> str:
    """Validate/lowercase a policy effect. Reject anything but allow/deny so a
    typo'd effect can't silently become an *allow* (deny-overrides keys off the
    exact string ``"deny"``)."""
    e = effect.lower() if isinstance(effect, str) else effect
    if e not in (_ALLOW, _DENY):
        raise ValueError(f"effect must be 'allow' or 'deny', got {effect!r}")
    return e


class NativePolicyEngine(PolicyEngine):
    """agno-native :class:`PolicyEngine`. Queries the DB fresh per decision. A DB is
    required (``db`` or ``db_url``); without one — and until AgentOS adopts the OS DB
    via :meth:`attach_db` — every operation raises, because an in-memory store can't
    stay consistent across the workers/replicas an AgentOS deployment runs."""

    def __init__(self, db_url: Optional[str] = None, db: Optional[Any] = None):
        # A DB is required. It may arrive later via attach_db() (the AgentOS
        # role_store= shortcut), so an engine built with neither db nor db_url starts
        # "unbound" and raises on use until bound — it is never an operating mode.
        self._engine: Any = None  # SQLAlchemy Engine once bound, else None (unbound)
        self._policy_tbl: Any = None
        self._group_tbl: Any = None
        self._log = logging.getLogger("agno.authz.engine")

        target = _engine_from_db(db) if db is not None else (_engine_from_url(db_url) if db_url else None)
        if target is not None:
            self._setup_db(target)

    # --- storage ---------------------------------------------------------
    @property
    def is_bound(self) -> bool:
        """True once a DB is bound (directly or via :meth:`attach_db`)."""
        return self._engine is not None

    def _require_engine(self) -> None:
        if self._engine is None:
            raise RuntimeError(NO_DB_MESSAGE)

    def _setup_db(self, engine: Any) -> None:
        import sqlalchemy as sa

        self._engine = engine
        metadata = sa.MetaData()
        self._policy_tbl = sa.Table(
            "authz_policy",
            metadata,
            sa.Column("role", sa.String(255), primary_key=True),
            sa.Column("resource", sa.String(512), primary_key=True),
            sa.Column("action", sa.String(255), primary_key=True),
            sa.Column("effect", sa.String(16), nullable=False),
        )
        self._group_tbl = sa.Table(
            "authz_grouping",
            metadata,
            sa.Column("subject", sa.String(255), primary_key=True),
            sa.Column("role", sa.String(255), primary_key=True),
        )
        metadata.create_all(self._engine)

    def attach_db(self, db: Any) -> None:
        """Bind an agno ``Db`` to a still-unbound engine, then read the DB fresh.

        No-op if a DB is already bound (the caller's explicit choice wins) or the db
        isn't SQL-capable (e.g. a NoSQL agno Db) — in which case the engine stays
        unbound and the next operation raises. Lets AgentOS adopt the OS database for
        a managed store created without one."""
        if self._engine is not None:
            return  # already bound — respect the explicit choice
        try:
            engine = _engine_from_db(db)
        except Exception:
            return  # not a SQL-capable db; stay unbound (use will raise)
        self._setup_db(engine)

    # --- read helpers (DB-backed) ----------------------------------------
    def _direct_roles(self, node: str) -> Set[str]:
        """Roles directly assigned to ``node`` (a subject, or a role when nesting).
        Indexed point-lookup on the grouping PK."""
        self._require_engine()
        import sqlalchemy as sa

        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(self._group_tbl.c.role).where(self._group_tbl.c.subject == node))
            return {r[0] for r in rows}

    def _closure(self, seed: str) -> Set[str]:
        """``seed`` plus the roles it is (transitively) assigned. The seed itself is
        included so a token-carried role matches policies written for that role."""
        seen: Set[str] = set()
        stack = [seed]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self._direct_roles(node))
        return seen

    def _policies_for(self, principals: Set[str]) -> List[_PolicyRow]:
        """All (role, resource, action, effect) rows whose role is in ``principals``."""
        if not principals:
            return []
        self._require_engine()
        import sqlalchemy as sa

        t = self._policy_tbl
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(t).where(t.c.role.in_(principals))).mappings()
            return [(row["role"], row["resource"], row["action"], row["effect"]) for row in rows]

    # --- persistence (db-backed mutations) -------------------------------
    def _persist_policies_set(self, role: str, rows: List[Tuple[str, str, str]]) -> None:
        """Replace a role's persisted policy rows with ``rows`` ((resource, action, effect))."""
        self._require_engine()
        import sqlalchemy as sa

        with self._engine.begin() as conn:
            conn.execute(sa.delete(self._policy_tbl).where(self._policy_tbl.c.role == role))
            if rows:
                conn.execute(
                    sa.insert(self._policy_tbl),
                    [{"role": role, "resource": res, "action": act, "effect": eff} for res, act, eff in rows],
                )

    def _persist_policy(self, role: str, resource: str, action: str, effect: str) -> None:
        self._require_engine()
        import sqlalchemy as sa

        with self._engine.begin() as conn:
            conn.execute(
                sa.delete(self._policy_tbl).where(
                    self._policy_tbl.c.role == role,
                    self._policy_tbl.c.resource == resource,
                    self._policy_tbl.c.action == action,
                )
            )
            conn.execute(sa.insert(self._policy_tbl).values(role=role, resource=resource, action=action, effect=effect))

    def _delete_policy(self, role: str, resource: Optional[str] = None, action: Optional[str] = None) -> None:
        self._require_engine()
        import sqlalchemy as sa

        clause = [self._policy_tbl.c.role == role]
        if resource is not None:
            clause.append(self._policy_tbl.c.resource == resource)
        if action is not None:
            clause.append(self._policy_tbl.c.action == action)
        with self._engine.begin() as conn:
            conn.execute(sa.delete(self._policy_tbl).where(*clause))

    def _persist_grouping(self, subject: str, role: str, add: bool) -> None:
        self._require_engine()
        import sqlalchemy as sa

        with self._engine.begin() as conn:
            conn.execute(
                sa.delete(self._group_tbl).where(self._group_tbl.c.subject == subject, self._group_tbl.c.role == role)
            )
            if add:
                conn.execute(sa.insert(self._group_tbl).values(subject=subject, role=role))

    def _delete_grouping_role(self, role: str) -> None:
        self._require_engine()
        import sqlalchemy as sa

        with self._engine.begin() as conn:
            conn.execute(sa.delete(self._group_tbl).where(self._group_tbl.c.role == role))

    # --- authoring: roles -> scopes -------------------------------------
    def set_role_scopes(self, role: str, entries: List[ScopeEntry]) -> None:
        # Stage + validate EVERY entry first: a bad scope raises before anything is
        # written, and mapping to a dict dedups colliding (resource, action) pairs
        # (e.g. agents:read & agents:*:read) so the insert can't hit a duplicate PK.
        staged: Dict[Tuple[str, str], str] = {}
        for scope, effect in entries:
            resource, action = scope_to_resource_action(scope)
            staged[(resource, action)] = _normalize_effect(effect)
        self._persist_policies_set(role, [(res, act, eff) for (res, act), eff in staged.items()])

    def add_scope(self, role: str, scope: str, effect: str = _ALLOW) -> None:
        resource, action = scope_to_resource_action(scope)  # validate before mutating
        effect = _normalize_effect(effect)
        self._persist_policy(role, resource, action, effect)

    def remove_scope(self, role: str, scope: str) -> None:
        resource, action = scope_to_resource_action(scope)  # validate before mutating
        self._delete_policy(role, resource, action)

    def get_role_scopes(self, role: str) -> List[ScopeEntry]:
        return [(resource_action_to_scope(res, act), eff) for (r, res, act, eff) in self._policies_for({role})]

    def remove_role(self, role: str) -> None:
        self._delete_policy(role)
        self._delete_grouping_role(role)

    def list_roles(self) -> List[str]:
        # Roles defined by scope policies PLUS roles that only exist as assignments,
        # so an assignment-only role is still inspectable/cleanable.
        self._require_engine()
        import sqlalchemy as sa

        with self._engine.connect() as conn:
            roles = {r[0] for r in conn.execute(sa.select(self._policy_tbl.c.role).distinct())}
            roles |= {r[0] for r in conn.execute(sa.select(self._group_tbl.c.role).distinct())}
        return sorted(roles)

    # --- assignments: subject -> roles ----------------------------------
    def assign(self, subject: str, role: str) -> None:
        self._persist_grouping(subject, role, add=True)

    def unassign(self, subject: str, role: str) -> None:
        self._persist_grouping(subject, role, add=False)

    def roles_of(self, subject: str) -> List[str]:
        return sorted(self._direct_roles(subject))

    # --- decisions -------------------------------------------------------
    def _allowed_for_root(self, root: str, request_resource: str, request_action: str) -> bool:
        """deny-overrides within one identity root: allowed iff some grant in the
        root's closure matches and allows, and none matches and denies."""
        allow = deny = False
        for _role, resource, action, effect in self._policies_for(self._closure(root)):
            if action != "*" and action != request_action:
                continue
            if not resource_matches(resource, request_resource):
                continue
            if effect == _DENY:
                deny = True
            else:
                allow = True
        return allow and not deny

    def _enforce(self, resource: str, action: str, subject: Optional[str], roles: Optional[List[str]]) -> bool:
        """One decision for ``(resource, action)``. Token-carried roles take precedence
        (each evaluated as its own root and OR'd); else the subject's assignments."""
        if roles:
            decision = any(self._allowed_for_root(role, resource, action) for role in roles)
        elif subject:
            decision = self._allowed_for_root(subject, resource, action)
        else:
            decision = False
        if self._log.isEnabledFor(logging.INFO):
            who = f"roles={roles}" if roles else f"subject={subject!r}"
            self._log.info("authz decision: %s resource=%r action=%r -> %s", who, resource, action, decision)
        return decision

    def check_resource(
        self,
        resource_type: Optional[str],
        resource_id: Optional[str],
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> bool:
        if not resource_type or not action:
            return True  # non-resource check: defer (the route gate handles it)
        resource = f"{resource_type}/{resource_id}" if resource_id else resource_type
        return self._enforce(resource, action, subject, roles)

    def check_scope(self, scope: str, *, subject: Optional[str] = None, roles: Optional[List[str]] = None) -> bool:
        try:
            resource, action = scope_to_resource_action(scope)
        except ValueError:
            return False  # unmappable scope -> not satisfied
        return self._enforce(resource, action, subject, roles)

    def _principals_for(self, subject: Optional[str], roles: Optional[List[str]]) -> Set[str]:
        roots = list(roles) if roles else ([subject] if subject else [])
        principals: Set[str] = set()
        for root in roots:
            principals |= self._closure(root)
        return principals

    def accessible_resource_ids(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        """Resource ids of ``resource_type`` the identity may access for ``action``
        (``{"*"}`` = wildcard/collection grant). Mirrors :meth:`_enforce`: roles
        take precedence, else the subject's stored assignments; deny rows skipped."""
        if not resource_type:
            return set()
        principals = self._principals_for(subject, roles)
        if not principals:
            return set()
        ids: Set[str] = set()
        prefix = f"{resource_type}/"
        for _role, resource, policy_action, effect in self._policies_for(principals):
            if effect == _DENY:
                continue
            if action is not None and policy_action != action and policy_action != "*":
                continue
            if resource in ("*", f"{resource_type}/*", resource_type):
                return {"*"}
            if resource.startswith(prefix):
                ids.add(resource[len(prefix) :])
        return ids

    def denied_resource_ids(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        """Concrete ids of ``resource_type`` explicitly denied for ``action`` (the
        deny rows). Lets the provider carve denials out of a wildcard-allow list so
        list endpoints honour deny-overrides like the per-resource gate does."""
        if not resource_type:
            return set()
        principals = self._principals_for(subject, roles)
        if not principals:
            return set()
        ids: Set[str] = set()
        prefix = f"{resource_type}/"
        for _role, resource, policy_action, effect in self._policies_for(principals):
            if effect != _DENY:
                continue
            if action is not None and policy_action != action and policy_action != "*":
                continue
            if resource.startswith(prefix):
                ids.add(resource[len(prefix) :])
        return ids
