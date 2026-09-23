"""One object for AgentOS authorization: verification, roles, audit, and the ``/authz`` admin API.

Standing up managed roles by hand would mean assembling an audit sink, a role store, an
``AuthorizationConfig``, a ``ScopeAuthorizationProvider``, the store's provider, a router factory
and an ``include_router`` call, and keeping them pointed at the same database.
:class:`Authorization` owns all of that and wires itself into AgentOS:

    from agno.os import Authorization

    authz = Authorization(db=db, audit=True, trust_token_scopes=True,
                          verification_keys=KEYS, audience=OS_ID)
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    authz.define_role("runner", ["agents:*:read", "agents:*:run"])
    authz.seed(admin=ADMIN_SUBJECT)   # bootstrap the admin ROLE
    authz.assign("carol", "runner")   # give a specific user a non-default role (bootstrap-safe)

    agent_os = AgentOS(id=OS_ID, db=db, agents=[...], user_directory=True, authorization=authz)

Roles are opt-in: ``define_role`` puts roles in play, and a verify-only Authorization defines none.
The user directory is NOT configured here, and Authorization never touches it. It is a top-level
``AgentOS(user_directory=...)`` concern, a peer of ``user_isolation``, and it works with or without
auth. Seed people on the ``UserDirectory`` itself (``users.upsert(...)``) and give them roles with
``assign(subject, role)`` (bootstrap-safe) or the ``/authz`` admin API. Verification lives here because it
already lives under authorization today (``authorization=True`` + ``AuthorizationConfig(...)``), and
plenty of setups verify tokens with no roles (isolation, scope-based access, service accounts). So the
verify-only case is a one-liner:

    Authorization(verification_keys=KEYS, audience=OS_ID)   # no roles, no ceremony

Roles are managed through this object at runtime too: ``set_role``, ``unassign``, ``roles_of``,
``set_role_scopes``, ``remove_role``, ``list_roles``, ``can_manage``, ``audit_log``, ``decisions``
(each with an async twin). The store underneath is private. ``engine=`` swaps the policy backend
(a :class:`~agno.os.authz.engine.PolicyEngine`) and keeps this API and ``/authz``;
``authorization_provider=`` is the full override: your provider decides alone, no store, no
``/authz``. Simplicity by default, full control when you need it.

The database is borrowed from AgentOS when you don't pass one, so you never write ``db=`` twice --
role definitions and the admin seed are buffered and applied once the db binds (the same way
``AgentOS(user_directory=True)`` adopts the OS db).
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union

from agno.os.authz._db import is_async_authz_db, resolve_authz_db
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.os.authz._role_store import RoleStore
    from agno.os.authz.audit import AuditSink
    from agno.os.authz.engine import PolicyEngine
    from agno.os.authz.provider import AuthorizationProvider
    from agno.os.config import AuthorizationConfig

# The role name :meth:`Authorization.seed` grants to its ``admin=`` subject. Define a role with
# this slug (and the ``agent_os:admin`` scope) for the grant to actually confer admin.
_ADMIN_ROLE = "admin"

_WIRED_WITHOUT_ROLES = (
    "This Authorization was wired into AgentOS without managed roles, so its role API is not live: "
    "AgentOS decided at wiring that no role store is in play and /authz is not mounted, and nothing "
    "would read what is written here. Declare roles before AgentOS(...): define_role / seed / assign, "
    "a runtime write (set_role_scopes, set_role, ...) on the object, or engine= / roles_claim=."
)
_NEEDS_DB = (
    "Authorization needs a SQL database: pass Authorization(db=...) / db_url=..., or hand it to "
    "AgentOS(db=...) so it can adopt the OS database."
)

# define_role()/seed() write at construction time, which is synchronous; an async database can only
# be driven from an event loop, and driving it from a throwaway loop here would bind its connection
# pool to the wrong loop. So setup needs a sync db; async is for request-time enforcement.
_ASYNC_SETUP_MSG = (
    "Authorization.define_role()/seed() write roles at setup time and need a synchronous database, but "
    "the bound database is async ({db_type}). Give AgentOS a sync db for setup, or configure roles "
    "yourself through the async runtime API (Authorization.aset_role_scopes / aset_role) once bound. "
    "An object with no define_role()/seed()/assign() calls works against an async db."
)

# A scope entry as accepted by set_role_scopes: a scope string, a (scope, effect) pair, or a dict.
ScopeInput = Union[str, Tuple[str, str], Dict[str, str]]


class Authorization:
    """The single AgentOS authorization object. Pass it as ``AgentOS(authorization=...)``.

    Owns token verification, managed roles (defined, seeded and edited through this object), the
    audit sink, and the ``/authz`` admin API mount. Build the common case in a few lines; drop to
    ``engine=`` or ``authorization_provider=`` for full control.
    """

    def __init__(
        self,
        *,
        db: Optional[Any] = None,
        db_url: Optional[str] = None,
        # --- token verification (carried into the AuthorizationConfig AgentOS builds) ---
        verification_keys: Optional[List[str]] = None,
        jwks_file: Optional[str] = None,
        algorithm: Optional[str] = None,
        verify_audience: Optional[bool] = None,
        audience: Optional[str] = None,
        issuer: Optional[str] = None,
        admin_scope: Optional[str] = None,
        excluded_route_paths: Optional[List[str]] = None,
        # --- switches ---
        audit: Union[bool, "AuditSink"] = False,
        trust_token_scopes: bool = False,
        roles_claim: Optional[str] = None,
        # --- escape hatches (bring your own) ---
        authorization_provider: Optional[Union["AuthorizationProvider", List["AuthorizationProvider"]]] = None,
        engine: Optional["PolicyEngine"] = None,
    ):
        """
        Args:
            db / db_url: the SQL database for roles/users/audit. Optional -- when omitted the
                object borrows ``AgentOS(db=...)`` at bind time, so you pass a db once.
            verification_keys, jwks_file, algorithm, verify_audience, audience, issuer,
                admin_scope, excluded_route_paths: JWT verification settings. Used with or
                without roles (verify-only / scope-based / isolation deployments set just these).
            audit: ``True`` builds a ``DbAuditSink`` from the bound db (feeds both the change and
                decision trails); pass an ``AuditSink`` to use your own; ``False`` disables it.
            trust_token_scopes: run a scope plane alongside managed roles, so operators authorized
                by their token scopes and end users authorized by the role store both work
                (composed with OR). No effect without roles.
            roles_claim: the external-IdP case -- read the caller's role(s) from this token claim
                (e.g. WorkOS/Auth0 send a ``role`` claim) instead of from stored assignments. You
                still ``define_role`` what each role may do; the token asserts which role the caller
                has, so no per-user ``assign``. Turns managed roles on by itself.
            authorization_provider: full override -- your provider decides alone, no store is built
                and ``/authz`` is not mounted. Cannot be combined with ``engine``; to keep the admin
                API on top of your own backend, pass ``engine=`` instead.
            engine: a custom :class:`~agno.os.authz.engine.PolicyEngine` backend for the roles (OpenFGA,
                SpiceDB, ...); the default is agno's native engine on the bound database. (The user
                directory is a top-level ``AgentOS(user_directory=...)`` concern, a peer of
                ``user_isolation``, not configured here.)
        """
        if authorization_provider is not None and engine is not None:
            raise ValueError(
                "Authorization(authorization_provider=...) is the full override and takes no engine=: the "
                "provider decides alone. To keep managed roles and the /authz admin API on your own backend, "
                "pass engine=<PolicyEngine> instead of a provider."
            )
        # Verification settings, splatted into the AuthorizationConfig at build time. Typed Any so
        # the per-key kwarg splat type-checks against AuthorizationConfig's specific field types.
        # ``issuer`` is handed to AgentOS separately: the released AuthorizationConfig has no such
        # field and stays frozen at its released shape.
        self._verification: Dict[str, Any] = {
            "verification_keys": verification_keys,
            "jwks_file": jwks_file,
            "algorithm": algorithm,
            "verify_audience": verify_audience,
            "audience": audience,
            "admin_scope": admin_scope,
            "excluded_route_paths": excluded_route_paths,
        }
        self._issuer = issuer
        self._audit_arg = audit
        self._trust_token_scopes = trust_token_scopes
        self._roles_claim = roles_claim
        self._provider_override = authorization_provider
        self._engine = engine

        self._role_store: Optional["RoleStore"] = None
        self._audit_sink: Optional["AuditSink"] = None

        # The user directory is NOT owned here: it is a top-level AgentOS(user_directory=...) concern,
        # a peer of user_isolation, seeded on the UserDirectory itself. Authorization never touches
        # it -- seed() below bootstraps the admin ROLE only.

        # Roles are in play if any were defined, or a store/engine was supplied.
        self._roles_defined = engine is not None or roles_claim is not None
        self._wired = False  # set once AgentOS has wired the object; roles cannot be declared after

        # Buffers applied at bind time (used when no db is available yet).
        self._role_defs: List[Tuple[str, List[ScopeInput], bool, Optional[str], Optional[str]]] = []
        self._seed_calls: List[Tuple[str, str]] = []
        self._assign_calls: List[Tuple[str, str, Optional[str]]] = []
        # Admins seeded, checked once at finalize so a warning never depends on define_role/seed order.
        self._seeded_admins: List[Tuple[str, str]] = []
        self._admins_checked = False

        self._db: Any = resolve_authz_db(db, db_url)
        if self._db is not None:
            # A database that cannot store authorization data fails here, at construction, rather
            # than on the first role definition or served request.
            from agno.os.authz._db import require_authz_db

            require_authz_db(self._db)
        self._db_is_async = False
        self._bound = False
        if self._db is not None:
            self._bind()

    # ------------------------------------------------------------------ authoring
    def define_role(
        self,
        slug: str,
        scopes: List[ScopeInput],
        *,
        default: bool = False,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> "Authorization":
        """Define a role's scopes, if it does not already exist. ``default=True`` marks it the role a
        JIT-provisioned user gets. Applied now if a db is bound, else buffered until AgentOS lends one.

        BOOTSTRAP semantics for scopes: an existing role's scopes are left untouched, so re-running
        this on every start never overwrites scope changes an admin made at runtime through the
        ``/authz`` API. To change a role's scopes after first boot, use the admin API (or
        :meth:`set_role_scopes` directly for a declarative, code-owns-the-role model).

        ``default=True`` is applied on every boot, existing role or not: it is the provisioning
        policy, and moving it to another role in code must take effect. Omitting ``default`` never
        clears an existing default. Chainable."""
        self._declare_roles()
        if self._bound:
            self._apply_role_def(slug, scopes, default, name, description)
        else:
            self._role_defs.append((slug, scopes, default, name, description))
        return self

    def seed(self, *, admin: str, admin_role: str = _ADMIN_ROLE) -> "Authorization":
        """Bootstrap the admin: grant ``admin_role`` (default ``"admin"`` -- define it first) to
        ``admin`` if no subject already holds an admin role. A role concern only. The user directory
        is separate: seed people on the ``UserDirectory`` (``users.upsert(...)``) and give them
        roles with :meth:`assign` or the ``/authz`` admin API.

        BOOTSTRAP semantics: an existing admin is left as is, so seeding on every start is safe. A
        handover to another admin survives restarts; only a true lockout (nobody holds an admin role)
        re-grants ``admin`` here. Applied now if a db is bound, else buffered until AgentOS lends one."""
        self._declare_roles()
        if self._bound:
            self._apply_seed(admin, admin_role)
        else:
            self._seed_calls.append((admin, admin_role))
        return self

    def assign(self, subject: str, role: str, actor: Optional[str] = None) -> "Authorization":
        """Give ``subject`` a ``role`` if they hold none yet -- the bootstrap way to grant a seeded
        user their role (define the role first).

        BOOTSTRAP semantics: create-if-absent, so re-running on every start never clobbers a role an
        admin changed at runtime through the ``/authz`` API. That is the difference from
        ``role_store.assign``, which overwrites unconditionally (use it directly for a declarative,
        code-owns-the-assignment model). Applied now if a db is bound, else buffered. Chainable."""
        self._declare_roles()
        if self._bound:
            self._apply_assign(subject, role, actor)
        else:
            self._assign_calls.append((subject, role, actor))
        return self

    async def aassign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Async twin of :meth:`assign` for the request path (JIT provisioning): create-if-absent,
        against a bound store."""
        store = self._store(declare=True)
        if not await store.aroles_of(subject):
            await store.aassign(subject, role, actor=actor)

    # ------------------------------------------------------------------ binding
    def _bind(self, os_db: Optional[Any] = None) -> "Authorization":
        """Resolve the database (own, else the OS db), build the requested stores, and flush any
        buffered role/user definitions. Idempotent: a second call (e.g. AgentOS re-binding an
        already-bound object) is a no-op."""
        if self._bound:
            return self
        self._db = self._db or os_db
        # A database is only needed for things that PERSIST and are not already persisted: a role
        # store or directory the object has to build (or was handed unbound), or a DbAuditSink from
        # audit=True. Verify-only / scope-based / custom-provider setups store nothing, and a store
        # you built with its own db brings its persistence along, so neither needs a db here.
        if self._db is None and self._needs_own_db():
            raise ValueError(_NEEDS_DB)
        self._db_is_async = is_async_authz_db(self._db)
        self._audit_sink = self._resolve_audit()
        if self._roles_defined or self._role_defs:
            self._ensure_role_store()
        # A role store that could not bind (its own db missing AND the OS db not SQL-capable) would
        # run in memory: roles silently lost on restart, never seen by another replica. Fail here, at
        # construction, rather than serve that. (The directory has the same rule, enforced by AgentOS
        # on its own top-level store.)
        if self._role_store is not None and getattr(self._role_store, "is_bound", True) is False:
            raise ValueError(_NEEDS_DB)
        self._bound = True
        self._flush()
        return self

    def _flush(self) -> None:
        for slug, scopes, default, name, description in self._role_defs:
            self._apply_role_def(slug, scopes, default, name, description)
        self._role_defs.clear()
        for admin, admin_role in self._seed_calls:
            self._apply_seed(admin, admin_role)
        self._seed_calls.clear()
        for subject, role, actor in self._assign_calls:
            self._apply_assign(subject, role, actor)
        self._assign_calls.clear()

    def _needs_own_db(self) -> bool:
        """Whether binding has to have a database: a role store the object must build (or was handed
        unbound), or a DbAuditSink from audit=True. The directory is AgentOS's concern, so it does not
        figure here."""
        if self._audit_arg is True:
            return True
        if self._roles_defined or self._role_defs:
            return self._role_store is None or getattr(self._role_store, "is_bound", True) is False
        return False

    def _resolve_audit(self) -> Optional["AuditSink"]:
        if self._audit_arg is False or self._audit_arg is None:
            return None
        if self._audit_arg is True:
            from agno.os.authz.audit import DbAuditSink

            return DbAuditSink(db=self._db)
        return self._audit_arg  # an AuditSink instance

    def _ensure_role_store(self) -> "RoleStore":
        if self._role_store is None:
            from agno.os.authz._role_store import RoleStore

            # The last-admin guard only makes sense when the store is the only place admins
            # live: with a roles_claim or a token-scope plane alongside, an empty stored admin
            # set is not a lockout, so the store must not refuse those changes.
            self._role_store = RoleStore(
                db=self._db,
                engine=self._engine,
                roles_claim=self._roles_claim,
                guard_last_admin=self._roles_claim is None and not self._trust_token_scopes,
            )
        else:
            self._role_store.attach_db(self._db)
        if self._audit_sink is not None:
            self._role_store.attach_audit(self._audit_sink)
        return self._role_store

    def _apply_role_def(
        self,
        slug: str,
        scopes: List[ScopeInput],
        default: bool,
        name: Optional[str],
        description: Optional[str],
    ) -> None:
        """Set a role's scopes, but only if it has none yet -- so a runtime scope edit through the
        admin API is never overwritten by re-running the boot sequence.

        The check is on SCOPES, not mere existence: a role that exists only because someone was
        assigned to it (an assignment-only role, e.g. seeded before its define_role) still has no
        scopes, so this must define them rather than skip it as 'already there'.

        ``default=True`` is a provisioning policy, not part of the definition, so it is applied on
        every boot even when the role exists; setting it clears the flag from the previous holder.
        Omitting ``default`` never clears an existing default: that is left to the admin API."""
        self._require_sync_setup()
        store = self._ensure_role_store()
        if store.get_role_scopes(slug):  # already has scopes -> a definition/edit to preserve
            if default and store.default_role() != slug:  # no write, and no audit event, when unchanged
                store.set_role_meta(slug, is_default=True)
            return
        store.set_role_scopes(slug, scopes, name=name, description=description, is_default=default)

    def _apply_seed(self, admin: str, admin_role: str) -> None:
        """Grant the bootstrap admin role. A role concern only; the directory is separate."""
        self._require_sync_setup()
        role_store = self._ensure_role_store()
        self._restore_bootstrap_admin(role_store, admin, admin_role)
        # Checked once at finalize (authorization_config), so the warning never depends on whether
        # define_role ran before or after this seed.
        self._seeded_admins.append((admin, admin_role))

    def _apply_assign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Assign a role to a subject, create-if-absent so a runtime promotion survives a restart."""
        self._require_sync_setup()
        role_store = self._ensure_role_store()
        if not role_store.roles_of(subject):  # bootstrap: never clobber an existing (runtime) role
            role_store.assign(subject, role, actor=actor)

    @staticmethod
    def _restore_bootstrap_admin(role_store: "RoleStore", admin: str, admin_role: str) -> None:
        """Make the bootstrap subject admin only when nobody else can reach the admin API.

        Any weaker rule undoes an operator's decision. If another subject already holds admin, then a
        missing OR changed role on the bootstrap subject is a deliberate handover, not a lockout, and
        must survive restarts. So the only case that (re)grants is a true lockout: no stored
        assignment confers ``agent_os:admin`` (which also covers a fresh deploy). A role fully removed
        and a role demoted are treated the same, since removing a role is at least as strong a signal
        as changing it.

        On an engine that cannot enumerate a role's holders, fall back to create-if-absent (grant only
        when the subject has no role at all): a fresh deploy still bootstraps, and a handover we cannot
        see is not guessed at."""
        current_roles = role_store.roles_of(admin)
        try:
            holders = role_store.admin_subjects()
        except NotImplementedError:
            log_debug("seed(admin=): the policy engine cannot list a role's holders; using create-if-absent")
            if not current_roles:
                role_store.assign(admin, admin_role)
            return
        if holders:  # someone can still administer -> respect every assignment, including a handover
            return
        if current_roles:  # a real lockout: the subject was demoted or stripped and nobody is admin now
            log_warning(
                f"seed(admin={admin!r}): no subject holds a role that confers 'agent_os:admin', so "
                f"the admin API was unreachable. Re-granted {admin_role!r} to {admin!r}."
            )
        role_store.assign(admin, admin_role)

    def _require_sync_setup(self) -> None:
        """Setup writes run synchronously; refuse an async db with a clear, object-level message rather
        than letting a sync store call fail deep in the engine."""
        if self._db_is_async:
            raise ValueError(_ASYNC_SETUP_MSG.format(db_type=type(self._db).__name__))

    # ------------------------------------------------------------------ runtime role API
    # The role store is private; this is its public face. Everything below reads or writes the
    # persisted roles at runtime (an admin promoting someone, a script listing roles) and needs a
    # bound database. define_role / seed / assign above are the bootstrap-safe boot-time forms.

    def set_role_scopes(
        self,
        role: str,
        scopes: List[Union[str, Tuple[str, str], Dict[str, str]]],
        actor: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> None:
        """Define (or replace) what a role can do, in agno scope terms."""
        return self._store(declare=True).set_role_scopes(role, scopes, actor, name, description, is_default)

    async def aset_role_scopes(
        self,
        role: str,
        scopes: List[Union[str, Tuple[str, str], Dict[str, str]]],
        actor: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> None:
        """Async twin of :meth:`set_role_scopes`."""
        return await self._store(declare=True).aset_role_scopes(role, scopes, actor, name, description, is_default)

    def get_role_scopes(self, role: str) -> List[str]:
        """Return a role's scope strings (allow + deny), for display/read-back."""
        return self._store().get_role_scopes(role)

    async def aget_role_scopes(self, role: str) -> List[str]:
        """Async twin of :meth:`get_role_scopes`."""
        return await self._store().aget_role_scopes(role)

    def remove_role(self, role: str, actor: Optional[str] = None) -> None:
        """remove_role"""
        return self._store(declare=True).remove_role(role, actor)

    async def aremove_role(self, role: str, actor: Optional[str] = None) -> None:
        """Async twin of :meth:`remove_role`."""
        return await self._store(declare=True).aremove_role(role, actor)

    def list_roles(self) -> List[str]:
        """All role slugs (those with policies and/or metadata)."""
        return self._store().list_roles()

    async def alist_roles(self) -> List[str]:
        """Async twin of :meth:`list_roles`."""
        return await self._store().alist_roles()

    def unassign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """unassign"""
        return self._store(declare=True).unassign(subject, role, actor)

    async def aunassign(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Async twin of :meth:`unassign`."""
        return await self._store(declare=True).aunassign(subject, role, actor)

    def roles_of(self, subject: str) -> List[str]:
        """roles_of"""
        return self._store().roles_of(subject)

    async def aroles_of(self, subject: str) -> List[str]:
        """Async twin of :meth:`roles_of`."""
        return await self._store().aroles_of(subject)

    def default_role(self) -> Optional[str]:
        """The role flagged ``is_default``, granted to a user on first JIT provision."""
        return self._store().default_role()

    async def adefault_role(self) -> Optional[str]:
        """Async twin of :meth:`default_role`."""
        return await self._store().adefault_role()

    def can_manage(self, principal_id: Optional[str], claims: Optional[Dict[str, Any]] = None) -> bool:
        """True if the caller may administer roles (i.e. satisfies ``agent_os:admin``)."""
        return self._store().can_manage(principal_id, claims)

    async def acan_manage(self, principal_id: Optional[str], claims: Optional[Dict[str, Any]] = None) -> bool:
        """Async twin of :meth:`can_manage`."""
        return await self._store().acan_manage(principal_id, claims)

    def admin_subjects(self) -> List[str]:
        """Subjects whose STORED role satisfies ``agent_os:admin`` -- everyone who can reach the admin"""
        return self._store().admin_subjects()

    async def aadmin_subjects(self) -> List[str]:
        """Async twin of :meth:`admin_subjects`."""
        return await self._store().aadmin_subjects()

    def audit_log(
        self,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """A page of change-audit events (newest first by default), if the audit"""
        return self._store().audit_log(limit, offset, search, sort_by, order)

    async def aaudit_log(
        self,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """Async twin of :meth:`audit_log`."""
        return await self._store().aaudit_log(limit, offset, search, sort_by, order)

    def set_role(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Give the subject THE role, replacing any current one: the runtime counterpart of the bootstrap-safe :meth:`assign`."""
        return self._store(declare=True).assign(subject, role, actor)

    async def aset_role(self, subject: str, role: str, actor: Optional[str] = None) -> None:
        """Async twin of :meth:`set_role`."""
        return await self._store(declare=True).aassign(subject, role, actor)

    @property
    def _audit_readable(self) -> bool:
        """Whether the change trail can be read back (a db-backed sink); the ``/authz/audit`` route
        404s when it cannot."""
        return bool(getattr(self._store(), "audit_readable", False))

    # Admin-API plumbing: the /authz router's view of the store, not something a user calls.

    def _create_role(
        self,
        role: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Create a role with metadata only — no scopes (add those via"""
        return self._store(declare=True).create_role(role, name, description, is_default, actor)

    async def _acreate_role(
        self,
        role: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Async twin of :meth:`_create_role`."""
        return await self._store(declare=True).acreate_role(role, name, description, is_default, actor)

    def set_role_meta(
        self,
        role: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Update ONLY a role's metadata (display name / description / is_default),"""
        return self._store(declare=True).set_role_meta(role, name, description, is_default, actor)

    async def aset_role_meta(
        self,
        role: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Async twin of :meth:`set_role_meta`."""
        return await self._store(declare=True).aset_role_meta(role, name, description, is_default, actor)

    def _patch_role_scopes(
        self,
        role: str,
        upsert: Optional[List[Union[str, Tuple[str, str], Dict[str, str]]]] = None,
        remove: Optional[List[Union[str, Tuple[str, str], Dict[str, str]]]] = None,
        actor: Optional[str] = None,
    ) -> None:
        """Apply a scope diff: add/flip the ``upsert`` scopes and drop the ``remove``"""
        return self._store(declare=True).patch_role_scopes(role, upsert, remove, actor)

    async def _apatch_role_scopes(
        self,
        role: str,
        upsert: Optional[List[Union[str, Tuple[str, str], Dict[str, str]]]] = None,
        remove: Optional[List[Union[str, Tuple[str, str], Dict[str, str]]]] = None,
        actor: Optional[str] = None,
    ) -> None:
        """Async twin of :meth:`_patch_role_scopes`."""
        return await self._store(declare=True).apatch_role_scopes(role, upsert, remove, actor)

    def get_role(self, role: str) -> Optional[dict]:
        """Full role record: metadata + scope entries, or None if the role has"""
        return self._store().get_role(role)

    async def aget_role(self, role: str) -> Optional[dict]:
        """Async twin of :meth:`get_role`."""
        return await self._store().aget_role(role)

    def _get_role_scope_entries(self, role: str) -> List[dict]:
        """Return a role's scopes with effects: ``[{"scope": ..., "effect": ...}]``."""
        return self._store().get_role_scope_entries(role)

    async def _aget_role_scope_entries(self, role: str) -> List[dict]:
        """Async twin of :meth:`_get_role_scope_entries`."""
        return await self._store().aget_role_scope_entries(role)

    def _list_roles_detailed(self) -> List[dict]:
        """Every role as a full record (metadata + scope entries)."""
        return self._store().list_roles_detailed()

    async def _alist_roles_detailed(self) -> List[dict]:
        """Async twin of :meth:`_list_roles_detailed`."""
        return await self._store().alist_roles_detailed()

    def _role_names(self) -> Dict[str, str]:
        """``{slug: display name}`` for every role with a metadata row, from one read. A role"""
        return self._store().role_names()

    async def _arole_names(self) -> Dict[str, str]:
        """Async twin of :meth:`_role_names`."""
        return await self._store().arole_names()

    def _explicit_denials(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        """Ids of ``resource_type`` the identity is explicitly denied for ``action`` (``{"*"}`` for a
        collection-wide deny). The route gate uses it to name the deny that decided instead of
        reporting a grant as missing."""
        return self._store().explicit_denials(resource_type, action, subject=subject, roles=roles)

    async def _aexplicit_denials(
        self,
        resource_type: str,
        action: Optional[str],
        *,
        subject: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Set[str]:
        """Async twin of :meth:`_explicit_denials`."""
        return await self._store().aexplicit_denials(resource_type, action, subject=subject, roles=roles)

    def _default_role_applied(self, subject: str) -> Optional[str]:
        """The default role the engine applied to ``subject`` at decision time, or None. Asks the
        engine's own subject resolution rather than re-deriving its rules (a directory user it can
        see through ITS db, holding no assignment, whose id does not collide with a role name), so a
        denial explanation reports exactly what decided. Only meaningful for a subject with no
        assignment, which is the only case the gate asks about."""
        default = self.default_role()
        if not default:
            return None
        closure = getattr(self._store()._engine, "_subject_closure", None)
        return default if callable(closure) and default in closure(subject) else None

    async def _adefault_role_applied(self, subject: str) -> Optional[str]:
        """Async twin of :meth:`_default_role_applied`."""
        default = await self.adefault_role()
        if not default:
            return None
        closure = getattr(self._store()._engine, "_asubject_closure", None)
        return default if callable(closure) and default in await closure(subject) else None

    def _roles_of_many(self, subjects: List[str]) -> Dict[str, List[str]]:
        """Roles of each subject in one call; used where a caller needs the whole"""
        return self._store().roles_of_many(subjects)

    async def _aroles_of_many(self, subjects: List[str]) -> Dict[str, List[str]]:
        """Async twin of :meth:`_roles_of_many`."""
        return await self._store().aroles_of_many(subjects)

    def _audit_count(self, search: Optional[str] = None) -> int:
        """Total number of change-audit events (for pagination, honouring"""
        return self._store().audit_count(search)

    async def _aaudit_count(self, search: Optional[str] = None) -> int:
        """Async twin of :meth:`_audit_count`."""
        return await self._store().aaudit_count(search)

    def _attach_audit(self, sink: Optional["AuditSink"]) -> None:
        """Adopt ``sink`` as the change-audit sink if one wasn't set explicitly."""
        return self._store().attach_audit(sink)

    def _check_seeded_admins(self) -> None:
        """Warn (once) about any seeded admin whose role does not actually confer ``agent_os:admin``,
        so a mismatch surfaces at boot instead of as a silent ``can_manage() == False`` at runtime."""
        if self._admins_checked or self._role_store is None:
            return
        self._admins_checked = True
        for subject, admin_role in dict(self._seeded_admins).items():  # de-dupe, last role wins
            if not self._role_store.can_manage(subject):
                log_warning(
                    f"seed(admin={subject!r}) granted role {admin_role!r}, but that role does not confer "
                    "'agent_os:admin', so this subject cannot manage authorization (can_manage is False). "
                    f"Define it, e.g. define_role({admin_role!r}, ['agent_os:admin']), or pass "
                    "seed(admin_role=<your admin role>)."
                )

    # ------------------------------------------------------------------ what AgentOS reads
    @property
    def provider(self) -> Optional[Union["AuthorizationProvider", List["AuthorizationProvider"]]]:
        """The provider AgentOS should enforce with: your override, the role store's provider (with
        the scope plane alongside under ``trust_token_scopes``), or None so AgentOS falls back to
        scope RBAC. A list means several planes composed with OR."""
        if self._provider_override is not None:
            return self._provider_override
        if not self.uses_roles:
            return None  # verify-only / scope-based: AgentOS defaults to ScopeAuthorizationProvider
        store = self._store()
        if self._trust_token_scopes:
            from agno.os.authz.scope_provider import ScopeAuthorizationProvider

            return [ScopeAuthorizationProvider(), store.provider]
        return store.provider

    @property
    def issuer(self) -> Optional[str]:
        """The pinned token issuer (the ``iss`` claim), or None when not pinned."""
        return self._issuer

    @property
    def uses_roles(self) -> bool:
        """Whether managed roles are in play: a role was defined, a subject seeded or assigned, an
        engine or ``roles_claim`` given, or the runtime role API written to before wiring. Decided
        when AgentOS wires the object (it mounts ``/authz`` and provisions default roles only when
        this is True); a read never changes it."""
        return self._roles_defined

    @property
    def roles_decide(self) -> bool:
        """Whether the managed-role engine is the plane that decides requests: roles are in play and
        no ``authorization_provider=`` override was given. False under an override even when roles
        are defined on the object, since the override decides alone."""
        return self.uses_roles and self._provider_override is None

    @property
    def trust_token_scopes(self) -> bool:
        """Whether a scope plane runs alongside managed roles (the ``trust_token_scopes`` switch)."""
        return self._trust_token_scopes

    @property
    def roles_claim(self) -> Optional[str]:
        """The JWT claim a caller's roles are read from (the external-IdP case), or None when roles
        come from this object's own assignments."""
        return self._roles_claim

    @property
    def is_bound(self) -> bool:
        """True once a database is bound and, when roles are in play, the role store persists."""
        return self._bound and (self._role_store is None or getattr(self._role_store, "is_bound", True))

    def attach_db(self, db: Any) -> "Authorization":
        """Bind a database to an object built without one (what AgentOS does with the OS db)."""
        return self._bind(db)

    def _declare_roles(self) -> None:
        """Put managed roles in play. Whether roles are enforced (and /authz mounted) is decided when
        AgentOS wires the object, so a first declaration after wiring would land in a store nothing
        reads: refuse it. Re-declaring on an object already using roles is fine at any time."""
        if self._roles_defined:
            return
        if self._wired:
            raise ValueError(_WIRED_WITHOUT_ROLES)
        self._roles_defined = True

    def _wire(self, os_db: Optional[Any]) -> "Authorization":
        """What AgentOS calls: bind (lending the OS db) and mark the object wired, after which roles
        cannot be newly declared (see :meth:`_declare_roles`)."""
        self._bind(os_db)
        self._wired = True
        return self

    def _store(self, *, declare: bool = False) -> "RoleStore":
        """The private role store behind the runtime API. It needs a bound database, so an unbound
        object says so rather than failing inside the engine. ``declare=True`` (writes) puts roles in
        play, the same declaration as ``define_role``. A read never changes the object's mode: before
        wiring it answers from the database as it is (a fresh object on an existing store sees the
        roles there); after AgentOS wired the object without roles it is refused, since the OS is not
        using that store and an answer would be mistaken for a live one."""
        if not self._bound:
            raise ValueError(_NEEDS_DB)
        if declare:
            self._declare_roles()
        elif self._wired and not self._roles_defined:
            raise ValueError(_WIRED_WITHOUT_ROLES)
        return self._ensure_role_store()

    def decisions(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """The decision trail (every allow/deny the OS recorded), newest first. Empty when the audit
        sink is off or cannot be read (a logging sink)."""
        sink = self._audit_sink
        fn = getattr(sink, "read_decisions", None)
        return list(fn(limit=limit, offset=offset)) if callable(fn) else []

    async def adecisions(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Async twin of :meth:`decisions`."""
        sink = self._audit_sink
        fn = getattr(sink, "aread_decisions", None)
        if callable(fn):
            return list(await fn(limit=limit, offset=offset))
        return self.decisions(limit=limit, offset=offset)

    @property
    def audit_sink(self) -> Optional["AuditSink"]:
        """The resolved audit sink (feeds ``AgentOS.audit`` -- both trails), or None."""
        return self._audit_sink

    def authorization_config(self) -> "AuthorizationConfig":
        """The verification settings as the ``AuthorizationConfig`` the JWT middleware reads (its
        released field set, nothing more; the provider, issuer and audit sink travel separately).
        AgentOS calls this once after all setup, so it is where a seeded admin whose role does not
        grant admin is finally validated."""
        from agno.os.config import AuthorizationConfig

        self._check_seeded_admins()
        return AuthorizationConfig(**self._verification)
