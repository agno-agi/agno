"""The role store behind ``Authorization`` (private: use ``agno.os.authz.Authorization``).

Managed roles for AgentOS — agno-native API, native policy engine inside.

This is the "governance product" middle tier: create roles, assign them, and
change them at runtime, persisted to your own DB. You work entirely in agno
scope terms (``agents:*:read``, ``agents:research-agent:run``,
``agent_os:admin``). The decision engine underneath is agno's own
:class:`~agno.os.authz.native_engine.NativePolicyEngine` (deny-overrides RBAC, no
third-party dependency). The engine is swappable behind the :class:`PolicyEngine`
port. A change persists and takes effect on the next request across every
worker/replica, because decisions read the DB fresh (no in-process cache to go
stale).

A DB is **required** — managed roles must be persisted, and an in-memory store
can't stay consistent across the replicas an AgentOS deployment runs. Give the
store a DB directly (``db=``/``db_url=``) or let AgentOS lend the OS DB via
``Authorization(role_store=...)``; without one, every operation raises.
Persistence to a DB needs SQLAlchemy: ``pip install "agno[os]"``.

Example::

    store = RoleStore(db_url="postgresql+psycopg://...", roles_claim="roles")
    store.set_role_scopes("member", ["agents:*:read", "agents:research-agent:run"])
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("bob", "member")           # runtime, persisted

    agent_os = AgentOS(
        agents=[...],
        authorization=Authorization(verification_keys=[...], role_store=store),  # plug it in
    )

    # later, live (no redeploy, same token):
    store.assign("carol", "member")
    store.unassign("bob", "member")
"""

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union

from agno.os.authz._db import NO_DB_MESSAGE, is_async_authz_db, resolve_authz_db, supports_authz
from agno.os.authz._scope_policy import ADMIN_SCOPE
from agno.os.authz.audit import DEFAULT_AUDIT_SORT_FIELD, DEFAULT_AUDIT_SORT_ORDER
from agno.os.authz.engine import EngineAuthorizationProvider, PolicyEngine, normalize_roles_claim

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink

# A scope plus its effect. Inputs accept a bare string (= allow), a (scope, effect)
# tuple, or a {"scope": ..., "effect"|"value": ...} dict.
ScopeInput = Union[str, Tuple[str, str], Dict[str, str]]


class RoleChangeRefused(ValueError):
    """A role or assignment change the store refuses on safety grounds.

    Raised for the changes that are valid input but must not happen: removing the last
    stored admin (a lockout nothing but database surgery repairs), making an admin role
    the default (every provisioned user becomes an admin), or naming a role after an
    existing user (their assignments become inheritance edges). The admin API maps it to
    409, not 422, since the request was well formed."""


_LAST_ADMIN_MSG = (
    "Refused: this change would leave no subject holding a role that confers 'agent_os:admin', "
    "so nobody could administer authorization afterwards. Grant another subject an admin role first."
)

_ADMIN_DEFAULT_MSG = (
    "Refused: role {role!r} confers 'agent_os:admin' and cannot be the default role. The default "
    "is granted to every provisioned user, so this would make every valid token an administrator. "
    "Flag a non-admin role as the default and assign admin explicitly."
)

_ROLE_NAMED_AFTER_USER_MSG = (
    "Refused: {slug!r} is an existing user id, so it cannot also be a role. Subjects and roles share "
    "one namespace: a role by that name would turn the user's assignments into role inheritance (every "
    "holder of the new role would inherit that user's role) and the user would be denied on every "
    "request. Pick another slug."
)

_USER_AS_ROLE_MSG = (
    "Refused: {role!r} is a user, not a role, so it cannot be assigned as one. That would make the "
    "subject inherit the user's role and deny the user on every request. Did you swap the arguments?"
)


def _confers_admin(entries: List[Tuple[str, str]]) -> bool:
    """Whether a normalized scope set grants ``agent_os:admin`` directly (allow, no deny)."""
    return any(scope == ADMIN_SCOPE and effect == "allow" for scope, effect in entries)


def _check_removable(role: str, scope: str) -> None:
    """Validate a PATCH ``remove`` entry, and when the parser refuses it say how to clean the row:
    a legacy entry that the parser no longer accepts (an ``agent_os/*`` row reads back as
    ``agent_os:*:admin``) cannot be named here, but PUT of the role's scopes without it drops it."""
    from agno.os.authz._scope_policy import scope_to_resource_action

    try:
        scope_to_resource_action(scope)
    except ValueError as exc:
        raise ValueError(
            f"{exc} A stored entry that the parser no longer accepts cannot be removed by name; replace "
            f"the role's scopes without it via PUT /authz/roles/{role}/scopes."
        ) from None


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
    if scope == ADMIN_SCOPE and effect == "deny":
        # Deny overrides, so a deny on the admin super-scope strips admin from every holder of
        # the role at once, and a boot-time define_role() leaves it in place (an existing role's
        # scopes are preserved). Nothing but database surgery recovers. There is no legitimate
        # use: to take admin away, remove the allow.
        raise ValueError(
            f"A deny on {ADMIN_SCOPE!r} is refused: deny overrides, so it would lock every holder of the "
            "role out of administration, and the lockout survives restarts. Remove the allow instead."
        )
    return scope, effect


class RoleStore:
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
        guard_last_admin: bool = True,
    ):
        """
        Args:
            db_url: SQLAlchemy URL for the DB that holds the policy (e.g.
                ``postgresql+psycopg://...`` or ``sqlite:///roles.db``). Use your
                own database. If omitted (and no ``db``/``engine``), the store is
                unbound and must be bound before use — by AgentOS adopting the OS DB
                via ``role_store=``, or it raises. A DB is required; there is no
                in-memory mode (it couldn't stay consistent across replicas).
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
            guard_last_admin: refuse a change that would leave no STORED admin assignment
                (the default). Turn it off when admins come from somewhere the store cannot
                see, i.e. a ``roles_claim`` or a token-scope plane alongside, where an empty
                stored admin set is not a lockout.
        """
        self._guard_last_admin = guard_last_admin
        if engine is not None:
            self._engine: PolicyEngine = engine
        else:
            from agno.os.authz.native_engine import NativePolicyEngine

            self._engine = NativePolicyEngine(db_url=db_url, db=db)
        self._roles_claim = roles_claim
        self._audit = audit

        # Role metadata (display name / description / is_default / timestamps).
        # The policy engine only stores policies, so metadata needs its own table in
        # the same DB. Like the engine, it requires a DB — it may arrive later via
        # attach_db(), so it stays unbound (engine None) until then.
        self._meta_db: Any = resolve_authz_db(db, db_url)
        self._meta_db_is_async: bool = is_async_authz_db(self._meta_db)

        if decision_log:
            import logging

            logging.getLogger("agno.authz.engine").setLevel(logging.INFO)

    def explicit_denials(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        """Ids of ``resource_type`` the identity is explicitly DENIED for ``action`` (``{"*"}`` for
        a collection-wide deny). Deny-overrides means such a row refuses a request even when a
        wider allow would grant it; a gate explaining a denial uses this to name the deny rather
        than report a grant as missing."""
        return self._engine.denied_resource_ids(resource_type, action, subject=subject, roles=roles)

    def attach_audit(self, sink: Optional["AuditSink"]) -> None:
        """Adopt ``sink`` as the change-audit sink if one wasn't set explicitly.

        Mirrors :meth:`attach_db`: ``Authorization(audit=...)`` is a single switch that feeds both the
        decision trail and this change trail, but an ``audit=`` passed to the store directly wins.
        No-op when the store already has a sink or ``sink`` is None."""
        if self._audit is None and sink is not None:
            self._audit = sink

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
    def _require_meta(self) -> None:
        if self._meta_db is None:
            raise RuntimeError(NO_DB_MESSAGE)

    def _meta_get(self, slug: str) -> Optional[dict]:
        self._require_meta()
        return self._meta_db.get_authz_role_meta(slug)

    def _meta_get_all(self) -> dict:
        """All metadata rows as ``{slug: row}`` in a single read, so list views don't do
        one SELECT per role (N+1)."""
        self._require_meta()
        return {row["slug"]: row for row in self._meta_db.list_authz_role_meta()}

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
        self._meta_write(row)
        if is_default is True:
            # Single-default model: only one role may carry the flag, so ``default_role()``
            # is unambiguous (mirrors assign()'s one-role-per-subject). Clear it elsewhere.
            self._clear_other_defaults(slug, now)
        return row

    def _clear_other_defaults(self, keep: str, now: int) -> None:
        """Unset ``is_default`` on every role except ``keep`` (single-default model)."""
        if self._meta_db is None:
            return
        for slug, row in self._meta_get_all().items():
            if slug != keep and row.get("is_default"):
                self._meta_write({**row, "slug": slug, "is_default": False, "updated_at": now})

    def _meta_write(self, row: dict) -> None:
        self._require_meta()
        values = {k: v for k, v in row.items() if k != "slug"}
        self._meta_db.upsert_authz_role_meta(row["slug"], values)

    def _meta_delete(self, slug: str) -> None:
        self._require_meta()
        self._meta_db.delete_authz_role_meta(slug)

    def _meta_or_default(self, slug: str) -> dict:
        """Metadata for a role, synthesising defaults for rows defined before
        metadata existed (or via the raw enforcer)."""
        meta = self._meta_get(slug)
        if meta is not None:
            return meta
        return {"slug": slug, "name": slug, "description": None, "is_default": False, "created_at": 0, "updated_at": 0}

    # ------------------------------------------------------------------ guards
    def _admin_subjects_excluding(
        self, *, without_role: Optional[str] = None, without_subject: Optional[str] = None
    ) -> List[str]:
        """:meth:`admin_subjects` as it would read after dropping ``without_role`` (its policy
        and every assignment to it) and ``without_subject``. Nested inheritance through the
        dropped role is not followed, which can only under-refuse, never over-refuse."""
        roles = self.list_roles()
        holders: set = set()
        for role in roles:
            if role == without_role or not self._engine.check_scope(ADMIN_SCOPE, roles=[role]):
                continue
            holders.update(name for name in self._engine.subjects_of(role) if name not in roles)
        holders.discard(without_subject)
        return sorted(holders)

    def _refuse_if_locks_out(
        self, *, without_role: Optional[str] = None, without_subject: Optional[str] = None
    ) -> None:
        """Refuse a change that would leave nobody holding a stored admin role.

        Only when someone holds one now: a store that is already locked out (or a fresh one)
        must not block the bootstrap that repairs it. Skipped on an engine that cannot list a
        role's holders, and when the operator declared that admins live elsewhere."""
        if not self._guard_last_admin:
            return
        try:
            if not self.admin_subjects():
                return
            remaining = self._admin_subjects_excluding(without_role=without_role, without_subject=without_subject)
        except NotImplementedError:
            return
        if not remaining:
            raise RoleChangeRefused(_LAST_ADMIN_MSG)

    def _refuse_admin_default(self, role: str, entries: Optional[List[Tuple[str, str]]] = None) -> None:
        """Refuse flagging an admin-conferring role as the default. ``entries`` are the scopes
        about to be written (checked directly); without them the stored policy decides."""
        if entries is not None:
            confers = _confers_admin(entries)
        else:
            confers = self._engine.check_scope(ADMIN_SCOPE, roles=[role])
        if confers:
            raise RoleChangeRefused(_ADMIN_DEFAULT_MSG.format(role=role))

    def _is_directory_user(self, name: str) -> bool:
        getter = getattr(self._meta_db, "get_authz_user", None) if self._meta_db is not None else None
        if not callable(getter):
            return False
        try:
            return getter(name) is not None
        except Exception:
            return False

    def _refuse_role_named_after_user(self, slug: str) -> None:
        """Refuse a NEW role whose slug is an existing user: a directory user, or a subject that
        holds an assignment. An existing role of that name is left alone (the collision guard
        already refuses the user at decision time; deleting the role is the fix)."""
        if slug in self.list_roles():
            return
        if self._is_directory_user(slug) or self._engine.roles_of(slug):
            raise RoleChangeRefused(_ROLE_NAMED_AFTER_USER_MSG.format(slug=slug))

    def _refuse_user_as_role(self, role: str) -> None:
        """Refuse assigning a ROLE argument that is a user: a directory user, or a subject with
        an assignment that is not itself a role."""
        if role in self.list_roles():
            return
        if self._is_directory_user(role) or self._engine.roles_of(role):
            raise RoleChangeRefused(_USER_AS_ROLE_MSG.format(role=role))

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
        entries = [_normalize_scope(e) for e in scopes]
        self._refuse_role_named_after_user(role)
        if is_default is True or (is_default is None and self.default_role() == role):
            self._refuse_admin_default(role, entries)
        if not _confers_admin(entries) and self._engine.check_scope(ADMIN_SCOPE, roles=[role]):
            self._refuse_if_locks_out(without_role=role)
        before = self.get_role_scope_entries(role) if self._audit else None
        self._engine.set_role_scopes(role, entries)
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
        self._refuse_role_named_after_user(role)
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
        if is_default is True:
            self._refuse_admin_default(role)
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
        from agno.os.authz._scope_policy import scope_to_resource_action

        before = self.get_role_scope_entries(role) if self._audit else None
        # Stage the upsert deny-wins by policy key, mirroring set_role_scopes: `agents:read`
        # and `agents:*:read` collapse to one key, so applying add_scope per entry (plain
        # last-write-wins) would let an allow silently OVERWRITE a deny the same diff also
        # lists. Deny must survive so PATCH and PUT cannot diverge into a grant.
        staged: dict = {}  # (resource, action) -> (scope_string, effect)
        for entry in upsert or []:
            scope, effect = _normalize_scope(entry)
            key = scope_to_resource_action(scope)  # validates + collapses aliasing spellings
            eff = "deny" if str(effect).lower() == "deny" else "allow"
            prev = staged.get(key)
            if prev is not None and (prev[1] == "deny" or eff == "deny"):
                staged[key] = (scope, "deny") if eff == "deny" else prev
            else:
                staged[key] = (scope, eff)
        # Validate the removes BEFORE the first write. Each add_scope commits on its own, so a bad
        # remove entry that only failed inside remove_scope left every upsert persisted, the
        # caller with a 422, and no audit event for the grants that did land.
        removals = [_normalize_scope(entry)[0] for entry in remove or []]
        for scope in removals:
            _check_removable(role, scope)  # raises on an unrecognised scope, with nothing written yet
        self._refuse_role_named_after_user(role)
        staged_entries = list(staged.values())
        if _confers_admin(staged_entries) and self.default_role() == role:
            self._refuse_admin_default(role, staged_entries)
        if ADMIN_SCOPE in removals and not _confers_admin(staged_entries):
            self._refuse_if_locks_out(without_role=role)
        for scope, effect in staged.values():
            self._engine.add_scope(role, scope, effect)
        for scope in removals:
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
        self._refuse_if_locks_out(without_role=role)
        before = self.get_role_scopes(role) if self._audit else None
        self._engine.remove_role(role)
        self._meta_delete(role)
        self._emit("role.removed", role, before, None, actor)

    def list_roles(self) -> List[str]:
        """All role slugs (those with policies and/or metadata)."""
        slugs = set(self._engine.list_roles())
        if self._meta_db is not None:
            # A role can exist as metadata only (created in the UI, no scopes yet).
            slugs |= {row["slug"] for row in self._meta_db.list_authz_role_meta()}
        return sorted(slugs)

    def role_names(self) -> Dict[str, str]:
        """``{slug: display name}`` for every role with a metadata row, from one read. A role
        whose name was never set maps to its slug. Roles with no metadata row (defined through
        the raw engine) are absent, so callers fall back to the slug. Lets a directory view
        show names without one metadata read per user. Empty when no metadata db is bound."""
        if self._meta_db is None:
            return {}
        return {slug: row.get("name") or slug for slug, row in self._meta_get_all().items()}

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

    def default_role(self) -> Optional[str]:
        """The role flagged ``is_default``, granted to a user on first JIT provision.

        Single-role model (mirrors :meth:`assign`, one role per subject): at most one role
        should carry the flag -- the metadata setters clear it from the others when a new
        default is set. If legacy data somehow has several, the lowest slug wins so the
        choice is deterministic. Returns ``None`` when no default is set (or no metadata db)."""
        if self._meta_db is None:
            return None
        defaults = sorted(slug for slug, row in self._meta_get_all().items() if row.get("is_default"))
        return defaults[0] if defaults else None

    # ------------------------------------------------------------- assignments
    @staticmethod
    def _refuse_role_as_subject(subject: str, roles: List[str]) -> None:
        """Subjects and roles share the grouping table, so a role slug used as the subject of an
        assignment is not a user grant but role inheritance: every holder of that role gains the
        assigned role's permissions. Refuse it at the one write path every caller goes through
        (the admin API, ``Authorization.assign``/``seed``, and the store itself)."""
        if subject in roles:
            raise ValueError(
                f"{subject!r} is a role, not a user, so it cannot be assigned a role: that would make every "
                f"holder of {subject!r} inherit the assigned role's permissions. Did you swap the arguments?"
            )

    def assign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Give a subject THE role (runtime, persisted).

        A subject holds at most ONE role at a time — assigning replaces any
        current role rather than accumulating. This mirrors the cloud RBAC model
        (a membership has one role) so role management is a select, not a
        multi-grant. Compose permissions in the role's scopes, not by stacking
        roles on a user. No-op if the subject already holds exactly this role.

        Refuses a ``subject`` that is itself a role slug. Subjects and roles share one
        grouping table, so ``assign("viewer", "admin")`` (the arguments transposed) would
        make the role ``viewer`` inherit ``admin`` and promote every viewer to admin.
        """
        self._refuse_role_as_subject(subject, self.list_roles())
        self._refuse_user_as_role(role)
        before = self.roles_of(subject)
        if before == [role]:
            return  # already exactly this role; no change, no audit noise
        if not self._engine.check_scope(ADMIN_SCOPE, roles=[role]):
            self._refuse_if_locks_out(without_subject=subject)
        replace = getattr(self._engine, "replace_subject_roles", None)
        if callable(replace):
            # One transaction: no window where the subject holds nothing, and two
            # concurrent assigns cannot each clear only what they saw and leave the
            # subject holding both roles.
            replace(subject, role)
        else:
            # Third-party PolicyEngine backends that don't offer an atomic replace.
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
        self._refuse_if_locks_out(without_subject=subject)
        before = self.roles_of(subject) if self._audit else None
        self._engine.unassign(subject, role)
        self._emit("user.unassigned", subject, before, self.roles_of(subject) if self._audit else None, actor)

    def roles_of(self, subject: str) -> List[str]:
        return self._engine.roles_of(subject)

    def roles_of_many(self, subjects: List[str]) -> Dict[str, List[str]]:
        """Roles of each subject in one call; used where a caller needs the whole
        directory's roles (metrics) rather than one page of it."""
        return self._engine.roles_of_many(subjects)

    def admin_subjects(self) -> List[str]:
        """Subjects whose STORED role satisfies ``agent_os:admin`` -- everyone who can reach the admin
        API without an admin claim on their token. Empty means the store has locked itself out.

        Only stored assignments count: a role carried on a token (``roles_claim``) is per-request and
        cannot be enumerated. Raises ``NotImplementedError`` on an engine that cannot list a role's
        holders (``subjects_of``)."""
        roles = self.list_roles()
        admin_roles = [r for r in roles if self._engine.check_scope("agent_os:admin", roles=[r])]
        holders: set = set()
        for role in admin_roles:
            # Assignments share one namespace with role-to-role inheritance, so drop names that are
            # themselves roles: those are nested roles, not people.
            holders.update(name for name in self._engine.subjects_of(role) if name not in roles)
        return sorted(holders)

    @property
    def is_bound(self) -> bool:
        """True once the store has a DB for both its policy engine and its role
        metadata (passed directly or adopted via :meth:`attach_db`). A custom
        ``engine=`` is assumed to manage its own persistence, but the store still
        needs a DB for the metadata (authz_roles) it owns."""
        flag = getattr(self._engine, "is_bound", None)
        engine_bound = bool(flag) if flag is not None else True
        return engine_bound and self._meta_db is not None

    def attach_db(self, db: Any) -> None:
        """Bind an agno ``Db`` to a store created without one, so managed roles
        persist in (and read fresh from) that DB. No-op if the store already has its
        own DB, or the db isn't SQL-capable. The Authorization object calls this to default a
        managed store to the OS database when you pass ``Authorization(role_store=...)``."""
        attach = getattr(self._engine, "attach_db", None)
        if callable(attach):
            attach(db)

        # Bind the metadata table (authz_roles) to the same DB, mirroring the
        # engine's own attach so policy, assignments, and metadata all land together.
        # No-op if metadata is already bound or the db isn't SQL-capable.
        if self._meta_db is None and db is not None and supports_authz(db):
            self._meta_db = db
            self._meta_db_is_async = is_async_authz_db(db)

    # ------------------------------------------------------------------ audit
    @property
    def audit_readable(self) -> bool:
        """True when a readable change-audit sink is configured (e.g. ``DbAuditSink``), so
        ``audit_log`` returns real events rather than always ``[]``. The ``/authz/audit`` route uses
        this to 404 when the change trail is off, rather than serve an empty 200 a frontend cannot
        tell apart from an enabled-but-empty trail."""
        sink = self._audit
        return sink is not None and hasattr(sink, "read")

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
        roles = normalize_roles_claim(claims, self._roles_claim)
        return self._engine.check_scope("agent_os:admin", subject=principal_id, roles=roles)

    # --------------------------------------------------------------- provider
    @property
    def provider(self):
        """The AuthorizationProvider to plug into AuthorizationConfig (engine-backed)."""
        return EngineAuthorizationProvider(self._engine, roles_claim=self._roles_claim)

    # =====================================================================
    # Async variants
    #
    # Twins of every public method, so managed roles work on an async request path and the
    # whole surface has both forms (the CLAUDE.md "both variants" rule). Role/assignment
    # work delegates to the engine's async methods; role metadata goes through
    # :meth:`_ameta_call`, which awaits an async DB and threads a sync one; audit emits
    # through the sink's async ``arecord``. The pure staging/normalisation logic is shared.
    # =====================================================================
    async def _ameta_call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self._require_meta()
        fn = getattr(self._meta_db, name)
        if self._meta_db_is_async:
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _aemit(
        self,
        action: str,
        target: str,
        before: Optional[List[Any]],
        after: Optional[List[Any]],
        actor: Optional[str],
    ) -> None:
        if self._audit is None:
            return
        from agno.os.authz.audit import AuditEvent

        await self._audit.arecord(
            AuditEvent(
                action=action, actor=actor, target=target, before=before, after=after, timestamp=int(time.time())
            )
        )

    # --- async role metadata ---
    async def _ameta_get(self, slug: str) -> Optional[dict]:
        return await self._ameta_call("get_authz_role_meta", slug)

    async def _ameta_get_all(self) -> dict:
        return {row["slug"]: row for row in await self._ameta_call("list_authz_role_meta")}

    async def _ameta_write(self, row: dict) -> None:
        values = {k: v for k, v in row.items() if k != "slug"}
        await self._ameta_call("upsert_authz_role_meta", row["slug"], values)

    async def _ameta_delete(self, slug: str) -> None:
        await self._ameta_call("delete_authz_role_meta", slug)

    async def _aclear_other_defaults(self, keep: str, now: int) -> None:
        if self._meta_db is None:
            return
        for slug, row in (await self._ameta_get_all()).items():
            if slug != keep and row.get("is_default"):
                await self._ameta_write({**row, "slug": slug, "is_default": False, "updated_at": now})

    async def _ameta_upsert(
        self,
        slug: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> dict:
        existing = await self._ameta_get(slug)
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
        await self._ameta_write(row)
        if is_default is True:
            await self._aclear_other_defaults(slug, now)
        return row

    async def _ameta_or_default(self, slug: str) -> dict:
        meta = await self._ameta_get(slug)
        if meta is not None:
            return meta
        return {"slug": slug, "name": slug, "description": None, "is_default": False, "created_at": 0, "updated_at": 0}

    # --- async guards ---
    async def _aadmin_subjects_excluding(
        self, *, without_role: Optional[str] = None, without_subject: Optional[str] = None
    ) -> List[str]:
        """Async twin of :meth:`_admin_subjects_excluding`."""
        roles = await self.alist_roles()
        holders: set = set()
        for role in roles:
            if role == without_role or not await self._engine.acheck_scope(ADMIN_SCOPE, roles=[role]):
                continue
            holders.update(name for name in await self._engine.asubjects_of(role) if name not in roles)
        holders.discard(without_subject)
        return sorted(holders)

    async def _arefuse_if_locks_out(
        self, *, without_role: Optional[str] = None, without_subject: Optional[str] = None
    ) -> None:
        """Async twin of :meth:`_refuse_if_locks_out`."""
        if not self._guard_last_admin:
            return
        try:
            if not await self.aadmin_subjects():
                return
            remaining = await self._aadmin_subjects_excluding(
                without_role=without_role, without_subject=without_subject
            )
        except NotImplementedError:
            return
        if not remaining:
            raise RoleChangeRefused(_LAST_ADMIN_MSG)

    async def _arefuse_admin_default(self, role: str, entries: Optional[List[Tuple[str, str]]] = None) -> None:
        """Async twin of :meth:`_refuse_admin_default`."""
        if entries is not None:
            confers = _confers_admin(entries)
        else:
            confers = await self._engine.acheck_scope(ADMIN_SCOPE, roles=[role])
        if confers:
            raise RoleChangeRefused(_ADMIN_DEFAULT_MSG.format(role=role))

    async def _ais_directory_user(self, name: str) -> bool:
        if self._meta_db is None or not hasattr(self._meta_db, "get_authz_user"):
            return False
        try:
            return (await self._ameta_call("get_authz_user", name)) is not None
        except Exception:
            return False

    async def _arefuse_role_named_after_user(self, slug: str) -> None:
        """Async twin of :meth:`_refuse_role_named_after_user`."""
        if slug in await self.alist_roles():
            return
        if await self._ais_directory_user(slug) or await self._engine.aroles_of(slug):
            raise RoleChangeRefused(_ROLE_NAMED_AFTER_USER_MSG.format(slug=slug))

    async def _arefuse_user_as_role(self, role: str) -> None:
        """Async twin of :meth:`_refuse_user_as_role`."""
        if role in await self.alist_roles():
            return
        if await self._ais_directory_user(role) or await self._engine.aroles_of(role):
            raise RoleChangeRefused(_USER_AS_ROLE_MSG.format(role=role))

    # --- async roles ---
    async def aset_role_scopes(
        self,
        role: str,
        scopes: List[ScopeInput],
        actor: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> None:
        """Async twin of :meth:`set_role_scopes`."""
        entries = [_normalize_scope(e) for e in scopes]
        await self._arefuse_role_named_after_user(role)
        if is_default is True or (is_default is None and await self.adefault_role() == role):
            await self._arefuse_admin_default(role, entries)
        if not _confers_admin(entries) and await self._engine.acheck_scope(ADMIN_SCOPE, roles=[role]):
            await self._arefuse_if_locks_out(without_role=role)
        before = await self.aget_role_scope_entries(role) if self._audit else None
        await self._engine.aset_role_scopes(role, entries)
        await self._ameta_upsert(role, name=name, description=description, is_default=is_default)
        after = await self.aget_role_scope_entries(role) if self._audit else None
        await self._aemit("role.set_scopes", role, before, after, actor)

    async def aget_role_scopes(self, role: str) -> List[str]:
        """Async twin of :meth:`get_role_scopes`."""
        return sorted(scope for scope, _ in await self._engine.aget_role_scopes(role))

    async def aget_role_scope_entries(self, role: str) -> List[dict]:
        """Async twin of :meth:`get_role_scope_entries`."""
        entries = [{"scope": scope, "effect": effect} for scope, effect in await self._engine.aget_role_scopes(role)]
        return sorted(entries, key=lambda e: (e["scope"], e["effect"]))

    async def acreate_role(
        self,
        role: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Async twin of :meth:`create_role`."""
        if await self.aget_role(role) is not None:
            raise FileExistsError(role)
        await self._arefuse_role_named_after_user(role)
        rec = await self._ameta_upsert(role, name=name, description=description, is_default=is_default)
        await self._aemit("role.created", role, None, [self._meta_summary(rec)], actor)
        return rec

    async def aset_role_meta(
        self,
        role: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Async twin of :meth:`set_role_meta`."""
        if await self.aget_role(role) is None:
            raise KeyError(role)
        if is_default is True:
            await self._arefuse_admin_default(role)
        before = await self._ameta_or_default(role)
        rec = await self._ameta_upsert(role, name=name, description=description, is_default=is_default)
        await self._aemit("role.updated", role, [self._meta_summary(before)], [self._meta_summary(rec)], actor)
        return rec

    async def apatch_role_scopes(
        self,
        role: str,
        upsert: Optional[List[ScopeInput]] = None,
        remove: Optional[List[ScopeInput]] = None,
        actor: Optional[str] = None,
    ) -> None:
        """Async twin of :meth:`patch_role_scopes`."""
        from agno.os.authz._scope_policy import scope_to_resource_action

        before = await self.aget_role_scope_entries(role) if self._audit else None
        staged: dict = {}
        for entry in upsert or []:
            scope, effect = _normalize_scope(entry)
            key = scope_to_resource_action(scope)
            eff = "deny" if str(effect).lower() == "deny" else "allow"
            prev = staged.get(key)
            if prev is not None and (prev[1] == "deny" or eff == "deny"):
                staged[key] = (scope, "deny") if eff == "deny" else prev
            else:
                staged[key] = (scope, eff)
        removals = [_normalize_scope(entry)[0] for entry in remove or []]
        for scope in removals:
            _check_removable(role, scope)  # validate before the first write (see the sync twin)
        await self._arefuse_role_named_after_user(role)
        staged_entries = list(staged.values())
        if _confers_admin(staged_entries) and await self.adefault_role() == role:
            await self._arefuse_admin_default(role, staged_entries)
        if ADMIN_SCOPE in removals and not _confers_admin(staged_entries):
            await self._arefuse_if_locks_out(without_role=role)
        for scope, effect in staged.values():
            await self._engine.aadd_scope(role, scope, effect)
        for scope in removals:
            await self._engine.aremove_scope(role, scope)
        await self._ameta_upsert(role)
        after = await self.aget_role_scope_entries(role) if self._audit else None
        await self._aemit("role.set_scopes", role, before, after, actor)

    async def aget_role(self, role: str) -> Optional[dict]:
        """Async twin of :meth:`get_role`."""
        scopes = await self.aget_role_scope_entries(role)
        meta = await self._ameta_get(role)
        if meta is None and not scopes and role not in await self._engine.alist_roles():
            return None
        return {**(await self._ameta_or_default(role)), "scopes": scopes}

    async def aremove_role(self, role: str, actor: Optional[str] = None) -> None:
        """Async twin of :meth:`remove_role`."""
        await self._arefuse_if_locks_out(without_role=role)
        before = await self.aget_role_scopes(role) if self._audit else None
        await self._engine.aremove_role(role)
        await self._ameta_delete(role)
        await self._aemit("role.removed", role, before, None, actor)

    async def alist_roles(self) -> List[str]:
        """Async twin of :meth:`list_roles`."""
        slugs = set(await self._engine.alist_roles())
        if self._meta_db is not None:
            slugs |= {row["slug"] for row in await self._ameta_call("list_authz_role_meta")}
        return sorted(slugs)

    async def arole_names(self) -> Dict[str, str]:
        """Async twin of :meth:`role_names`."""
        if self._meta_db is None:
            return {}
        return {slug: row.get("name") or slug for slug, row in (await self._ameta_get_all()).items()}

    async def alist_roles_detailed(self) -> List[dict]:
        """Async twin of :meth:`list_roles_detailed`."""
        meta_all = await self._ameta_get_all()
        default = {"name": None, "description": None, "is_default": False, "created_at": 0, "updated_at": 0}
        out: List[dict] = []
        for slug in await self.alist_roles():
            meta = meta_all.get(slug) or {"slug": slug, **default, "name": slug}
            out.append({**meta, "scopes": await self.aget_role_scope_entries(slug)})
        return out

    async def adefault_role(self) -> Optional[str]:
        """Async twin of :meth:`default_role`."""
        if self._meta_db is None:
            return None
        defaults = sorted(slug for slug, row in (await self._ameta_get_all()).items() if row.get("is_default"))
        return defaults[0] if defaults else None

    # --- async assignments ---
    async def aassign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Async twin of :meth:`assign`."""
        self._refuse_role_as_subject(subject, await self.alist_roles())
        await self._arefuse_user_as_role(role)
        before = await self.aroles_of(subject)
        if before == [role]:
            return
        if not await self._engine.acheck_scope(ADMIN_SCOPE, roles=[role]):
            await self._arefuse_if_locks_out(without_subject=subject)
        try:
            await self._engine.areplace_subject_roles(subject, role)
        except NotImplementedError:
            for existing in before:
                await self._engine.aunassign(subject, existing)
            await self._engine.aassign(subject, role)
        after = await self.aroles_of(subject) if self._audit else None
        await self._aemit("user.assigned", subject, before if self._audit else None, after, actor)

    async def aunassign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Async twin of :meth:`unassign`."""
        await self._arefuse_if_locks_out(without_subject=subject)
        before = await self.aroles_of(subject) if self._audit else None
        await self._engine.aunassign(subject, role)
        after = await self.aroles_of(subject) if self._audit else None
        await self._aemit("user.unassigned", subject, before, after, actor)

    async def aroles_of(self, subject: str) -> List[str]:
        """Async twin of :meth:`roles_of`."""
        return await self._engine.aroles_of(subject)

    async def aroles_of_many(self, subjects: List[str]) -> Dict[str, List[str]]:
        """Async twin of :meth:`roles_of_many`."""
        return await self._engine.aroles_of_many(subjects)

    async def aexplicit_denials(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        """Async twin of :meth:`explicit_denials`."""
        return await self._engine.adenied_resource_ids(resource_type, action, subject=subject, roles=roles)

    async def aadmin_subjects(self) -> List[str]:
        """Async twin of :meth:`admin_subjects`."""
        roles = await self.alist_roles()
        holders: set = set()
        for role in roles:
            if await self._engine.acheck_scope("agent_os:admin", roles=[role]):
                holders.update(name for name in await self._engine.asubjects_of(role) if name not in roles)
        return sorted(holders)

    # --- async audit + gating ---
    async def aaudit_log(
        self,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        sort_by: str = DEFAULT_AUDIT_SORT_FIELD,
        order: str = DEFAULT_AUDIT_SORT_ORDER,
    ) -> List[Dict[str, Any]]:
        """Async twin of :meth:`audit_log`."""
        sink = self._audit
        if sink is not None and hasattr(sink, "aread"):
            return await sink.aread(limit, offset=offset, search=search, sort_by=sort_by, order=order)
        return []

    async def aaudit_count(self, search: Optional[str] = None) -> int:
        """Async twin of :meth:`audit_count`."""
        sink = self._audit
        if sink is not None and hasattr(sink, "acount"):
            return int(await sink.acount(search=search))
        return 0

    async def acan_manage(self, principal_id: Optional[str], claims: Optional[Dict[str, Any]] = None) -> bool:
        """Async twin of :meth:`can_manage`."""
        roles = normalize_roles_claim(claims, self._roles_claim)
        return await self._engine.acheck_scope("agent_os:admin", subject=principal_id, roles=roles)
