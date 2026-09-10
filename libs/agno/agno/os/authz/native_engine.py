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
  an allow carried by another,
- a subject with NO role of its own (no assignment and no token-carried role) is
  treated as holding the ``is_default`` role, so "no role" is equivalent to the
  default role's permissions rather than an automatic deny (``disabled`` — not zero
  roles — is the lockout). This is decision-time only: nothing is written.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from agno.os.authz._db import (
    NO_DB_MESSAGE,
    is_async_authz_db,
    require_authz_db,
    resolve_authz_db,
    supports_authz,
)
from agno.os.authz._request_scope import amemoize, memoize
from agno.os.authz._request_scope import invalidate as _invalidate_request_cache
from agno.os.authz._scope_policy import resource_action_to_scope, resource_matches, scope_to_resource_action
from agno.os.authz.engine import PolicyEngine, ScopeEntry

# Message shown when a sync engine method is used against an async database: the
# async ``*_authz_*`` methods return coroutines, so the sync path cannot drive them.
_ASYNC_DB_SYNC_CALL_MESSAGE = (
    "This managed-roles operation was called synchronously against an async database "
    "({db_type}). Use the async variant (the a-prefixed method, e.g. acheck_resource / "
    "aassign), which AgentOS's request path uses automatically."
)

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
        # A DB is required. It may arrive later via attach_db() (the AgentOS role_store=
        # shortcut), so an engine built with neither starts "unbound" and raises on use
        # until bound — it is never an operating mode.
        self._db: Any = resolve_authz_db(db, db_url)
        self._db_is_async: bool = is_async_authz_db(self._db)
        self._log = logging.getLogger("agno.authz.engine")
        if self._db is not None:
            require_authz_db(self._db)

    # --- storage ---------------------------------------------------------
    @property
    def is_bound(self) -> bool:
        """True once a DB is bound (directly or via :meth:`attach_db`)."""
        return self._db is not None

    def _require_engine(self) -> None:
        if self._db is None:
            raise RuntimeError(NO_DB_MESSAGE)
        if self._db_is_async:
            # A sync method reached the DB layer on an async backend: its *_authz_* methods
            # return coroutines, so driving them synchronously would silently misbehave.
            # Fail loudly and point at the async variant instead.
            raise RuntimeError(_ASYNC_DB_SYNC_CALL_MESSAGE.format(db_type=type(self._db).__name__))

    def _arequire_engine(self) -> None:
        """Async-path guard: only requires a bound DB (async OR sync -- the async helpers
        drive a sync DB in a worker thread, so both are valid here)."""
        if self._db is None:
            raise RuntimeError(NO_DB_MESSAGE)

    async def _acall(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Call a ``*_authz_*`` DB method from the async path, whichever kind of DB is bound.

        Async backend: ``await`` the coroutine. Sync backend: run the blocking call in a
        worker thread so the event loop is never blocked on DB I/O. One dispatch point, so
        every async helper stays agnostic to which DB it is talking to."""
        self._arequire_engine()
        fn = getattr(self._db, name)
        if self._db_is_async:
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    def attach_db(self, db: Any) -> None:
        """Bind an agno ``Db`` to a still-unbound engine, then read it fresh.

        No-op if a DB is already bound (the caller's explicit choice wins) or the db does
        not implement the authorization contract — in which case the engine stays unbound
        and the next operation raises. Lets AgentOS lend the OS database to a managed
        store created without one."""
        if self._db is not None:
            return  # already bound — respect the explicit choice
        if db is not None and supports_authz(db):
            self._db = db
            self._db_is_async = is_async_authz_db(db)

    # --- read helpers (through the BaseDb authorization contract) ----------
    def _direct_roles(self, node: str) -> Set[str]:
        """Roles directly assigned to ``node`` (a subject, or a role when nesting)."""
        self._require_engine()
        return set(self._db.get_authz_direct_roles(node))

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

    def _subject_closure(self, subject: str) -> Set[str]:
        """Policy roots for a *subject*: only the roles it is (transitively) assigned.

        Subjects and roles share one namespace in the grouping table: role inheritance and
        a user's assignment are both written by :meth:`assign`, so an edge out of a name
        cannot be attributed to one or the other. Two consequences, both handled here, and
        neither reachable through :meth:`_closure` (which is for token-carried roles, where
        the seed IS legitimately a role):

        1. The subject is never a policy root, so a ``sub`` equal to a role slug cannot
           pick up that role's own rows.
        2. A ``sub`` equal to a name used as a role is refused outright. Otherwise the
           traversal would follow that role's INHERITANCE edges and hand the caller
           everything the role inherits -- ``sub="senior"`` collecting ``base``'s policy
           with no assignment at all.

        (2) fails closed: a real user whose id collides with a role name loses access
        rather than gaining someone else's. Keep subject ids and role slugs disjoint
        (emails or opaque ids for users) and the case never arises.
        """
        self._require_engine()

        def resolve() -> Set[str]:
            if self._db.authz_name_is_role(subject):
                self._log.warning(
                    "authz: subject %r collides with a role name and was refused. Subject ids and role "
                    "slugs share one namespace, so this identity is ambiguous and is denied rather than "
                    "resolved. Rename the role or use opaque subject ids (e.g. emails).",
                    subject,
                )
                return set()

            principals: Set[str] = set()
            stack = list(self._db.get_authz_direct_roles(subject))
            while stack:
                role = stack.pop()
                if role in principals:
                    continue
                principals.add(role)
                stack.extend(self._db.get_authz_direct_roles(role))
            if not principals:
                # No role of its own: a subject with no assigned role is treated as holding the
                # default (``is_default``) role -- BUT only when it is a known directory user. The
                # default is a floor for people the operator ONBOARDED, never for an arbitrary
                # authenticated ``sub``: a valid token for a subject that was never provisioned stays
                # denied, not handed the default role's permissions (which could be admin). This only
                # reaches here when the caller carries no token role either (``_enforce`` consults
                # assignments only then). ``disabled`` -- not zero roles -- is the lockout. Decision-
                # time only: nothing is written, so ``roles_of`` stays truthful. The directory must
                # share the role store's db for this check to see it; on a split db it fails closed.
                default = self._default_role()
                if default is not None and self._subject_in_directory(subject):
                    principals.add(default)
            return principals

        return memoize(("subject", id(self), subject), resolve)

    def _subject_in_directory(self, subject: str) -> bool:
        """Whether ``subject`` is a known directory user (an ``authz_users`` row).

        Gates the no-role default-role fallback: the default applies only to people the operator
        onboarded, so an arbitrary authenticated ``sub`` that was never provisioned is denied rather
        than granted the default. Reads through the engine's own db, so the directory must share it
        (the default ``AgentOS(db=...)`` shape does); with no directory / a split db this returns
        False and the fallback stays closed -- the safe direction."""
        getter = getattr(self._db, "get_authz_user", None)
        if not callable(getter):
            return False
        try:
            return getter(subject) is not None
        except Exception:
            return False

    def _default_role(self) -> Optional[str]:
        """The role flagged ``is_default`` -- the fallback for a subject with no assigned role.

        Mirrors :meth:`ManagedRoleStore.default_role`: at most one role carries the flag (the
        metadata setters clear the others); the lowest slug wins if legacy data has several, so
        the choice is deterministic. Returns ``None`` when no default is set or the db cannot
        list role metadata (e.g. a third-party backend)."""
        lister = getattr(self._db, "list_authz_role_meta", None)
        if not callable(lister):
            return None
        try:
            defaults = sorted(m["slug"] for m in lister() if m.get("is_default"))
        except Exception:
            return None
        return defaults[0] if defaults else None

    def _policies_for(self, principals: Set[str]) -> List[_PolicyRow]:
        """All (role, resource, action, effect) rows whose role is in ``principals``."""
        if not principals:
            return []
        self._require_engine()
        return memoize(
            ("policies", id(self), frozenset(principals)),
            lambda: [tuple(row) for row in self._db.get_authz_policies(sorted(principals))],  # type: ignore[misc]
        )

    # --- persistence (through the BaseDb authorization contract) -----------
    def _persist_policies_set(self, role: str, rows: List[Tuple[str, str, str]]) -> None:
        """Replace a role's persisted policy rows with ``rows`` ((resource, action, effect))."""
        self._require_engine()
        _invalidate_request_cache()  # a write must be visible to the rest of this request
        self._db.set_authz_role_policies(role, rows)

    def _persist_policy(self, role: str, resource: str, action: str, effect: str) -> None:
        self._require_engine()
        _invalidate_request_cache()  # a write must be visible to the rest of this request
        self._db.upsert_authz_policy(role=role, resource=resource, action=action, effect=effect)

    def _delete_policy(self, role: str, resource: Optional[str] = None, action: Optional[str] = None) -> None:
        self._require_engine()
        _invalidate_request_cache()  # a write must be visible to the rest of this request
        self._db.delete_authz_policy(role=role, resource=resource, action=action)

    def _persist_grouping(self, subject: str, role: str, add: bool) -> None:
        self._require_engine()
        _invalidate_request_cache()  # a write must be visible to the rest of this request
        if add:
            self._db.assign_authz_role(subject, role)
        else:
            self._db.unassign_authz_role(subject, role)

    def _delete_grouping_role(self, role: str) -> None:
        """Drop the role entirely: its policy, its assignments, and its metadata."""
        self._require_engine()
        _invalidate_request_cache()  # a write must be visible to the rest of this request
        self._db.delete_authz_role(role)

    # --- authoring: roles -> scopes -------------------------------------
    def set_role_scopes(self, role: str, entries: List[ScopeEntry]) -> None:
        # Stage + validate EVERY entry first: a bad scope raises before anything is
        # written, and mapping to a dict dedups colliding (resource, action) pairs
        # (e.g. agents:read & agents:*:read) so the insert can't hit a duplicate PK.
        staged: Dict[Tuple[str, str], str] = {}
        for scope, effect in entries:
            resource, action = scope_to_resource_action(scope)
            eff = _normalize_effect(effect)
            key = (resource, action)
            # Deny-WINS on a spelling collision. `agents:read` and `agents:*:read` map to
            # the same policy key, so a plain last-write-wins here would let an allow the
            # author also listed silently OVERWRITE a deny -- turning an explicit denial
            # into a grant with no error. Deny-overrides is the whole model, so a deny in
            # the same payload always survives, regardless of order.
            staged[key] = _DENY if (eff == _DENY or staged.get(key) == _DENY) else _ALLOW
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
        # One call: the db drops policy, assignments and metadata in a single transaction,
        # so a decision can never observe a half-deleted role.
        self._delete_grouping_role(role)

    def list_roles(self) -> List[str]:
        # Roles defined by scope policies PLUS roles that only exist as assignments,
        # so an assignment-only role is still inspectable/cleanable.
        self._require_engine()
        return sorted(self._db.list_authz_roles())

    # --- assignments: subject -> roles ----------------------------------
    def assign(self, subject: str, role: str) -> None:
        self._persist_grouping(subject, role, add=True)

    def unassign(self, subject: str, role: str) -> None:
        self._persist_grouping(subject, role, add=False)

    def replace_subject_roles(self, subject: str, role: str) -> None:
        """Atomically make ``role`` the subject's only role.

        One transaction, so there is no instant at which the subject holds zero roles
        (a request in flight during a promote/demote would be denied) and no interleaving
        in which two concurrent assigns each clear only the roles they saw and leave the
        subject holding both. Doing it as read-then-unassign-then-assign gives both.
        """
        self._require_engine()
        _invalidate_request_cache()  # a write must be visible to the rest of this request
        self._db.replace_authz_subject_roles(subject, role)

    def roles_of(self, subject: str) -> List[str]:
        return sorted(self._direct_roles(subject))

    def subjects_of(self, role: str) -> List[str]:
        self._require_engine()
        return sorted(self._db.list_authz_role_subjects(role))

    # --- decisions -------------------------------------------------------
    def _allowed_for_root(
        self, root: str, request_resource: str, request_action: str, *, is_subject: bool = False
    ) -> bool:
        """deny-overrides within one identity root: allowed iff some grant in the
        root's closure matches and allows, and none matches and denies.

        ``is_subject`` marks ``root`` as a subject id rather than a role, so it is
        resolved through its assignments only (see :meth:`_subject_closure`)."""
        allow = deny = False
        principals = self._subject_closure(root) if is_subject else self._closure(root)
        for _role, resource, action, effect in self._policies_for(principals):
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
            decision = self._allowed_for_root(subject, resource, action, is_subject=True)
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
        """Mirrors :meth:`_enforce`: token-carried roles are their own policy roots,
        while a subject resolves only through its assignments."""
        if roles:
            principals: Set[str] = set()
            for role in roles:
                principals |= self._closure(role)
            return principals
        return self._subject_closure(subject) if subject else set()

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
        """Ids of ``resource_type`` explicitly denied for ``action`` (``{"*"}`` = a
        collection/global deny, i.e. every id of this type). Lets the provider carve
        denials out of a wildcard-allow list so list endpoints honour deny-overrides
        like the per-resource gate does."""
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
            # A collection/global deny (``agents/*``, the bare type, or the admin
            # ``*`` wildcard) denies every id of this type -- mirror
            # accessible_resource_ids and signal it with the ``"*"`` sentinel.
            # Without this the deny was stripped to the literal id ``"*"``, which
            # never equals a real resource id, so it was silently dropped from list
            # filtering while the per-resource gate still enforced it.
            if resource in ("*", f"{resource_type}/*", resource_type):
                return {"*"}
            if resource.startswith(prefix):
                ids.add(resource[len(prefix) :])
        return ids

    # =====================================================================
    # Async variants
    #
    # Twins of every DB-touching public method, so the whole managed-roles surface has
    # both a sync and an async form (the CLAUDE.md "both variants" rule) and so authz can
    # run against an async database. Each awaits the DB through :meth:`_acall`, which drives
    # an async backend natively and a sync one in a worker thread -- so an async decision
    # path never blocks the event loop on DB I/O, whichever DB is bound. The pure decision
    # logic (deny-overrides, resource matching, scope mapping) is shared with the sync path.
    # =====================================================================

    # --- async read helpers ---
    async def _adirect_roles(self, node: str) -> Set[str]:
        return set(await self._acall("get_authz_direct_roles", node))

    async def _aclosure(self, seed: str) -> Set[str]:
        """``seed`` plus the roles it is (transitively) assigned (for token-carried roles)."""
        seen: Set[str] = set()
        stack = [seed]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(await self._adirect_roles(node))
        return seen

    async def _asubject_in_directory(self, subject: str) -> bool:
        """Async twin of :meth:`_subject_in_directory`."""
        if not hasattr(self._db, "get_authz_user"):
            return False
        try:
            return (await self._acall("get_authz_user", subject)) is not None
        except Exception:
            return False

    async def _adefault_role(self) -> Optional[str]:
        """Async twin of :meth:`_default_role`."""
        if not hasattr(self._db, "list_authz_role_meta"):
            return None
        try:
            rows = await self._acall("list_authz_role_meta")
            defaults = sorted(m["slug"] for m in rows if m.get("is_default"))
        except Exception:
            return None
        return defaults[0] if defaults else None

    async def _asubject_closure(self, subject: str) -> Set[str]:
        """Async twin of :meth:`_subject_closure` (same closure + no-role default fallback)."""
        self._arequire_engine()

        async def resolve() -> Set[str]:
            if await self._acall("authz_name_is_role", subject):
                self._log.warning(
                    "authz: subject %r collides with a role name and was refused. Subject ids and role "
                    "slugs share one namespace, so this identity is ambiguous and is denied rather than "
                    "resolved. Rename the role or use opaque subject ids (e.g. emails).",
                    subject,
                )
                return set()

            principals: Set[str] = set()
            stack = list(await self._acall("get_authz_direct_roles", subject))
            while stack:
                role = stack.pop()
                if role in principals:
                    continue
                principals.add(role)
                stack.extend(await self._acall("get_authz_direct_roles", role))
            if not principals:
                default = await self._adefault_role()
                if default is not None and await self._asubject_in_directory(subject):
                    principals.add(default)
            return principals

        return await amemoize(("subject", id(self), subject), resolve)

    async def _apolicies_for(self, principals: Set[str]) -> List[_PolicyRow]:
        if not principals:
            return []
        self._arequire_engine()

        async def resolve() -> List[_PolicyRow]:
            rows = await self._acall("get_authz_policies", sorted(principals))
            return [tuple(row) for row in rows]  # type: ignore[misc]

        return await amemoize(("policies", id(self), frozenset(principals)), resolve)

    async def _aprincipals_for(self, subject: Optional[str], roles: Optional[List[str]]) -> Set[str]:
        if roles:
            principals: Set[str] = set()
            for role in roles:
                principals |= await self._aclosure(role)
            return principals
        return await self._asubject_closure(subject) if subject else set()

    # --- async persistence helpers ---
    async def _apersist_policies_set(self, role: str, rows: List[Tuple[str, str, str]]) -> None:
        _invalidate_request_cache()
        await self._acall("set_authz_role_policies", role, rows)

    async def _apersist_policy(self, role: str, resource: str, action: str, effect: str) -> None:
        _invalidate_request_cache()
        await self._acall("upsert_authz_policy", role=role, resource=resource, action=action, effect=effect)

    async def _adelete_policy(self, role: str, resource: Optional[str] = None, action: Optional[str] = None) -> None:
        _invalidate_request_cache()
        await self._acall("delete_authz_policy", role=role, resource=resource, action=action)

    async def _apersist_grouping(self, subject: str, role: str, add: bool) -> None:
        _invalidate_request_cache()
        await self._acall("assign_authz_role" if add else "unassign_authz_role", subject, role)

    async def _adelete_grouping_role(self, role: str) -> None:
        _invalidate_request_cache()
        await self._acall("delete_authz_role", role)

    # --- async authoring: roles -> scopes ---
    async def aset_role_scopes(self, role: str, entries: List[ScopeEntry]) -> None:
        staged: Dict[Tuple[str, str], str] = {}
        for scope, effect in entries:
            resource, action = scope_to_resource_action(scope)
            eff = _normalize_effect(effect)
            key = (resource, action)
            staged[key] = _DENY if (eff == _DENY or staged.get(key) == _DENY) else _ALLOW
        await self._apersist_policies_set(role, [(res, act, eff) for (res, act), eff in staged.items()])

    async def aadd_scope(self, role: str, scope: str, effect: str = _ALLOW) -> None:
        resource, action = scope_to_resource_action(scope)
        effect = _normalize_effect(effect)
        await self._apersist_policy(role, resource, action, effect)

    async def aremove_scope(self, role: str, scope: str) -> None:
        resource, action = scope_to_resource_action(scope)
        await self._adelete_policy(role, resource, action)

    async def aget_role_scopes(self, role: str) -> List[ScopeEntry]:
        return [(resource_action_to_scope(res, act), eff) for (r, res, act, eff) in await self._apolicies_for({role})]

    async def aremove_role(self, role: str) -> None:
        await self._adelete_grouping_role(role)

    async def alist_roles(self) -> List[str]:
        return sorted(await self._acall("list_authz_roles"))

    # --- async assignments: subject -> roles ---
    async def aassign(self, subject: str, role: str) -> None:
        await self._apersist_grouping(subject, role, add=True)

    async def aunassign(self, subject: str, role: str) -> None:
        await self._apersist_grouping(subject, role, add=False)

    async def areplace_subject_roles(self, subject: str, role: str) -> None:
        _invalidate_request_cache()
        await self._acall("replace_authz_subject_roles", subject, role)

    async def aroles_of(self, subject: str) -> List[str]:
        return sorted(await self._adirect_roles(subject))

    async def asubjects_of(self, role: str) -> List[str]:
        return sorted(await self._acall("list_authz_role_subjects", role))

    # --- async decisions ---
    async def _aallowed_for_root(
        self, root: str, request_resource: str, request_action: str, *, is_subject: bool = False
    ) -> bool:
        allow = deny = False
        principals = await self._asubject_closure(root) if is_subject else await self._aclosure(root)
        for _role, resource, action, effect in await self._apolicies_for(principals):
            if action != "*" and action != request_action:
                continue
            if not resource_matches(resource, request_resource):
                continue
            if effect == _DENY:
                deny = True
            else:
                allow = True
        return allow and not deny

    async def _aenforce(self, resource: str, action: str, subject: Optional[str], roles: Optional[List[str]]) -> bool:
        if roles:
            decision = False
            for role in roles:
                if await self._aallowed_for_root(role, resource, action):
                    decision = True
                    break
        elif subject:
            decision = await self._aallowed_for_root(subject, resource, action, is_subject=True)
        else:
            decision = False
        if self._log.isEnabledFor(logging.INFO):
            who = f"roles={roles}" if roles else f"subject={subject!r}"
            self._log.info("authz decision: %s resource=%r action=%r -> %s", who, resource, action, decision)
        return decision

    async def acheck_resource(
        self,
        resource_type: Optional[str],
        resource_id: Optional[str],
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> bool:
        if not resource_type or not action:
            return True
        resource = f"{resource_type}/{resource_id}" if resource_id else resource_type
        return await self._aenforce(resource, action, subject, roles)

    async def acheck_scope(
        self, scope: str, *, subject: Optional[str] = None, roles: Optional[List[str]] = None
    ) -> bool:
        try:
            resource, action = scope_to_resource_action(scope)
        except ValueError:
            return False
        return await self._aenforce(resource, action, subject, roles)

    async def aaccessible_resource_ids(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        if not resource_type:
            return set()
        principals = await self._aprincipals_for(subject, roles)
        if not principals:
            return set()
        ids: Set[str] = set()
        prefix = f"{resource_type}/"
        for _role, resource, policy_action, effect in await self._apolicies_for(principals):
            if effect == _DENY:
                continue
            if action is not None and policy_action != action and policy_action != "*":
                continue
            if resource in ("*", f"{resource_type}/*", resource_type):
                return {"*"}
            if resource.startswith(prefix):
                ids.add(resource[len(prefix) :])
        return ids

    async def adenied_resource_ids(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        if not resource_type:
            return set()
        principals = await self._aprincipals_for(subject, roles)
        if not principals:
            return set()
        ids: Set[str] = set()
        prefix = f"{resource_type}/"
        for _role, resource, policy_action, effect in await self._apolicies_for(principals):
            if effect != _DENY:
                continue
            if action is not None and policy_action != action and policy_action != "*":
                continue
            if resource in ("*", f"{resource_type}/*", resource_type):
                return {"*"}
            if resource.startswith(prefix):
                ids.add(resource[len(prefix) :])
        return ids
