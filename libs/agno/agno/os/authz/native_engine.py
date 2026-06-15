"""The native managed-roles policy engine — agno's default, zero third-party deps.

A :class:`~agno.os.authz.engine.PolicyEngine` implemented directly in agno: roles
hold scopes (with allow/deny), subjects are assigned roles, and decisions use
**deny-overrides** matching the cloud RBAC semantics. No external policy engine.

Storage is in-memory by default (``ManagedRoleStore()``); pass a ``db`` (an agno
``Db``) or ``db_url`` and policy + assignments persist to two SQLAlchemy tables
(``authz_policy``, ``authz_grouping``) and are loaded back on startup. The
in-memory caches are the read path either way; mutations write through to the DB.

The decision model, in agno terms:

- a role's scopes are stored as ``(resource, action, effect)`` via the shared
  :mod:`~agno.os.authz._scope_policy` convention (deduped per
  ``(role, resource, action)``),
- a subject (or a token-carried role) is allowed an action on a resource iff some
  matching grant says *allow* and none says *deny* — evaluated per identity root
  and OR'd across token-carried roles, so a deny on one role can't silently veto
  an allow carried by another.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from agno.os.authz._db import engine_from_db as _engine_from_db
from agno.os.authz._scope_policy import resource_action_to_scope, resource_matches, scope_to_resource_action
from agno.os.authz.engine import PolicyEngine, ScopeEntry

_DENY = "deny"
_ALLOW = "allow"
# A policy key: (role, resource, action). The value is the effect ("allow" | "deny").
_PolicyKey = Tuple[str, str, str]


class NativePolicyEngine(PolicyEngine):
    """agno-native :class:`PolicyEngine`. In-memory, or SQLAlchemy-persisted when
    given ``db``/``db_url``."""

    def __init__(self, db_url: Optional[str] = None, db: Optional[Any] = None):
        # Read path: in-memory caches, authoritative for decisions either way.
        self._policies: Dict[_PolicyKey, str] = {}  # (role, resource, action) -> effect
        self._grouping: Dict[str, Set[str]] = {}  # subject -> {role, ...}
        self._engine: Any = None  # SQLAlchemy Engine when persisted, else None
        self._policy_tbl: Any = None
        self._group_tbl: Any = None
        self._log = logging.getLogger("agno.authz.engine")

        target = _engine_from_db(db) if db is not None else (self._make_engine(db_url) if db_url else None)
        if target is not None:
            self._setup_db(target)

    # --- persistence -----------------------------------------------------
    @staticmethod
    def _make_engine(db_url: str) -> Any:
        import sqlalchemy as sa

        return sa.create_engine(db_url)

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
        # Load persisted state into the in-memory caches (the read path).
        with self._engine.connect() as conn:
            for row in conn.execute(sa.select(self._policy_tbl)).mappings():
                self._policies[(row["role"], row["resource"], row["action"])] = row["effect"]
            for row in conn.execute(sa.select(self._group_tbl)).mappings():
                self._grouping.setdefault(row["subject"], set()).add(row["role"])

    def _persist_policies_set(self, role: str, rows: List[Tuple[str, str, str]]) -> None:
        """Replace a role's persisted policy rows with ``rows`` ((resource, action, effect))."""
        if self._engine is None:
            return
        import sqlalchemy as sa

        with self._engine.begin() as conn:
            conn.execute(sa.delete(self._policy_tbl).where(self._policy_tbl.c.role == role))
            if rows:
                conn.execute(
                    sa.insert(self._policy_tbl),
                    [{"role": role, "resource": res, "action": act, "effect": eff} for res, act, eff in rows],
                )

    def _persist_policy(self, role: str, resource: str, action: str, effect: str) -> None:
        if self._engine is None:
            return
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
        if self._engine is None:
            return
        import sqlalchemy as sa

        clause = [self._policy_tbl.c.role == role]
        if resource is not None:
            clause.append(self._policy_tbl.c.resource == resource)
        if action is not None:
            clause.append(self._policy_tbl.c.action == action)
        with self._engine.begin() as conn:
            conn.execute(sa.delete(self._policy_tbl).where(*clause))

    def _persist_grouping(self, subject: str, role: str, add: bool) -> None:
        if self._engine is None:
            return
        import sqlalchemy as sa

        with self._engine.begin() as conn:
            conn.execute(
                sa.delete(self._group_tbl).where(self._group_tbl.c.subject == subject, self._group_tbl.c.role == role)
            )
            if add:
                conn.execute(sa.insert(self._group_tbl).values(subject=subject, role=role))

    def _delete_grouping_role(self, role: str) -> None:
        if self._engine is None:
            return
        import sqlalchemy as sa

        with self._engine.begin() as conn:
            conn.execute(sa.delete(self._group_tbl).where(self._group_tbl.c.role == role))

    # --- authoring: roles -> scopes -------------------------------------
    def set_role_scopes(self, role: str, entries: List[ScopeEntry]) -> None:
        for key in [k for k in self._policies if k[0] == role]:
            del self._policies[key]
        rows: List[Tuple[str, str, str]] = []
        for scope, effect in entries:
            resource, action = scope_to_resource_action(scope)
            self._policies[(role, resource, action)] = effect  # dedup per (role, resource, action)
            rows.append((resource, action, effect))
        self._persist_policies_set(role, rows)

    def add_scope(self, role: str, scope: str, effect: str = _ALLOW) -> None:
        resource, action = scope_to_resource_action(scope)
        self._policies[(role, resource, action)] = effect
        self._persist_policy(role, resource, action, effect)

    def remove_scope(self, role: str, scope: str) -> None:
        resource, action = scope_to_resource_action(scope)
        self._policies.pop((role, resource, action), None)
        self._delete_policy(role, resource, action)

    def get_role_scopes(self, role: str) -> List[ScopeEntry]:
        return [
            (resource_action_to_scope(resource, action), effect)
            for (r, resource, action), effect in self._policies.items()
            if r == role
        ]

    def remove_role(self, role: str) -> None:
        for key in [k for k in self._policies if k[0] == role]:
            del self._policies[key]
        for subject in list(self._grouping):
            self._grouping[subject].discard(role)
        self._delete_policy(role)
        self._delete_grouping_role(role)

    def list_roles(self) -> List[str]:
        # Roles defined by scope policies PLUS roles that only exist as assignments,
        # so an assignment-only role is still inspectable/cleanable.
        roles = {key[0] for key in self._policies}
        for assigned in self._grouping.values():
            roles |= assigned
        return sorted(roles)

    # --- assignments: subject -> roles ----------------------------------
    def assign(self, subject: str, role: str) -> None:
        self._grouping.setdefault(subject, set()).add(role)
        self._persist_grouping(subject, role, add=True)

    def unassign(self, subject: str, role: str) -> None:
        self._grouping.get(subject, set()).discard(role)
        self._persist_grouping(subject, role, add=False)

    def roles_of(self, subject: str) -> List[str]:
        return sorted(self._grouping.get(subject, set()))

    # --- decisions -------------------------------------------------------
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
            stack.extend(self._grouping.get(node, ()))
        return seen

    def _allowed_for_root(self, root: str, request_resource: str, request_action: str) -> bool:
        """deny-overrides within one identity root: allowed iff some grant in the
        root's closure matches and allows, and none matches and denies."""
        principals = self._closure(root)
        allow = deny = False
        for (role, resource, action), effect in self._policies.items():
            if role not in principals:
                continue
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
        roots = list(roles) if roles else ([subject] if subject else [])
        if not roots:
            return set()
        principals: Set[str] = set()
        for root in roots:
            principals |= self._closure(root)

        ids: Set[str] = set()
        for (role, resource, policy_action), effect in self._policies.items():
            if role not in principals or effect == _DENY:
                continue
            if action is not None and policy_action != action and policy_action != "*":
                continue
            if resource in ("*", f"{resource_type}/*", resource_type):
                return {"*"}
            prefix = f"{resource_type}/"
            if resource.startswith(prefix):
                ids.add(resource[len(prefix) :])
        return ids
