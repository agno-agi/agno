"""One object for AgentOS authorization: verification, roles, audit, and the ``/authz`` admin API.

Standing up managed roles by hand means assembling a ``DbAuditSink``, a ``RoleStore``, an
``AuthorizationConfig``, a ``ScopeAuthorizationProvider``, the store's provider, a router factory
and an ``include_router`` call, and keeping them pointed at the same database.
:class:`Authorization` owns all of that and wires itself into AgentOS:

    from agno.os.authz import Authorization

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
auth. Seed people on the ``UserStore`` itself (``users.upsert(...)``) and give them roles with
``assign(subject, role)`` (bootstrap-safe) or the ``/authz`` admin API. Verification lives here because it
already lives under authorization today (``authorization=True`` + ``AuthorizationConfig(...)``), and
plenty of setups verify tokens with no roles (isolation, scope-based access, service accounts). So the
verify-only case is a one-liner:

    Authorization(verification_keys=KEYS, audience=OS_ID)   # no roles, no ceremony

Everything the object builds is still reachable as a primitive: pass your own ``role_store=`` /
``engine=`` and the object uses them instead of building its own. ``authorization_provider=`` is the
full override: your provider decides alone, no store, no ``/authz``. Simplicity by default, full
control when you need it.

The database is borrowed from AgentOS when you don't pass one, so you never write ``db=`` twice --
role definitions and the admin seed are buffered and applied once the db binds (the same way
``AgentOS(user_directory=True)`` adopts the OS db).
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from agno.os.authz._db import is_async_authz_db, resolve_authz_db
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink
    from agno.os.authz.engine import PolicyEngine
    from agno.os.authz.provider import AuthorizationProvider
    from agno.os.authz.role_store import RoleStore
    from agno.os.config import AuthorizationConfig

# The role name :meth:`Authorization.seed` grants to its ``admin=`` subject. Define a role with
# this slug (and the ``agent_os:admin`` scope) for the grant to actually confer admin.
_ADMIN_ROLE = "admin"

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
    "yourself through the async store API (RoleStore.aset_role_scopes) and pass it via "
    "Authorization(role_store=...). An object with a pre-built store and no define_role()/seed() calls "
    "works against an async db."
)

# A scope entry as accepted by RoleStore.set_role_scopes.
ScopeInput = Union[str, Tuple[str, str], Dict[str, str]]


class Authorization:
    """The single AgentOS authorization object. Pass it as ``AgentOS(authorization=...)``.

    Owns token verification, the optional managed-role store, the optional user directory, the
    audit sink, and the admin API mount. Build the common case in a few lines; drop to the
    underlying primitives (``role_store=``, ``authorization_provider=``, ...) for full control.
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
        role_store: Optional["RoleStore"] = None,
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
                and ``/authz`` is not mounted. Cannot be combined with ``role_store``/``engine``; to
                keep the admin API on top of your own backend, pass ``engine=`` instead.
            engine / role_store: primitives. Supply either and the object uses it instead of
                building its own. (The user directory is a top-level ``AgentOS(user_directory=...)``
                concern, a peer of ``user_isolation``, not configured here.)
        """
        if authorization_provider is not None and (role_store is not None or engine is not None):
            raise ValueError(
                "Authorization(authorization_provider=...) is the full override and takes no role_store= "
                "or engine=: the provider decides alone. To keep managed roles and the /authz admin API "
                "on your own backend, pass engine=<PolicyEngine> instead of a provider."
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

        self._role_store: Optional["RoleStore"] = role_store
        self._audit_sink: Optional["AuditSink"] = None

        # The user directory is NOT owned here: it is a top-level AgentOS(user_directory=...) concern,
        # a peer of user_isolation, seeded on the UserStore itself. Authorization never touches
        # it -- seed() below bootstraps the admin ROLE only.

        # Roles are in play if any were defined, or a store/engine was supplied.
        self._roles_defined = role_store is not None or engine is not None or roles_claim is not None

        # Buffers applied at bind time (used when no db is available yet).
        self._role_defs: List[Tuple[str, List[ScopeInput], bool, Optional[str], Optional[str]]] = []
        self._seed_calls: List[Tuple[str, str]] = []
        self._assign_calls: List[Tuple[str, str]] = []
        # Admins seeded, checked once at finalize so a warning never depends on define_role/seed order.
        self._seeded_admins: List[Tuple[str, str]] = []
        self._admins_checked = False

        self._db: Any = resolve_authz_db(db, db_url)
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

        BOOTSTRAP semantics: an existing role is left untouched, so re-running this on every start
        never overwrites scope changes an admin made at runtime through the ``/authz`` API. To change
        a role's scopes after first boot, use the admin API (or ``RoleStore.set_role_scopes``
        directly for a declarative, code-owns-the-role model). Chainable."""
        self._roles_defined = True
        if self._bound:
            self._apply_role_def(slug, scopes, default, name, description)
        else:
            self._role_defs.append((slug, scopes, default, name, description))
        return self

    def seed(self, *, admin: str, admin_role: str = _ADMIN_ROLE) -> "Authorization":
        """Bootstrap the admin: grant ``admin_role`` (default ``"admin"`` -- define it first) to
        ``admin`` if no subject already holds an admin role. A role concern only. The user directory
        is separate: seed people on the ``UserStore`` (``users.upsert(...)``) and give them
        roles with :meth:`assign` or the ``/authz`` admin API.

        BOOTSTRAP semantics: an existing admin is left as is, so seeding on every start is safe. A
        handover to another admin survives restarts; only a true lockout (nobody holds an admin role)
        re-grants ``admin`` here. Applied now if a db is bound, else buffered until AgentOS lends one."""
        if self._bound:
            self._apply_seed(admin, admin_role)
        else:
            self._seed_calls.append((admin, admin_role))
        return self

    def assign(self, subject: str, role: str) -> "Authorization":
        """Give ``subject`` a ``role`` if they hold none yet -- the bootstrap way to grant a seeded
        user their role (define the role first).

        BOOTSTRAP semantics: create-if-absent, so re-running on every start never clobbers a role an
        admin changed at runtime through the ``/authz`` API. That is the difference from
        ``role_store.assign``, which overwrites unconditionally (use it directly for a declarative,
        code-owns-the-assignment model). Applied now if a db is bound, else buffered. Chainable."""
        self._roles_defined = True
        if self._bound:
            self._apply_assign(subject, role)
        else:
            self._assign_calls.append((subject, role))
        return self

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
        for subject, role in self._assign_calls:
            self._apply_assign(subject, role)
        self._assign_calls.clear()

    def _needs_own_db(self) -> bool:
        """Whether binding has to have a database: a role store the object must build (or was handed
        unbound), or a DbAuditSink from audit=True. The directory is AgentOS's concern, so it does not
        figure here."""
        if self._audit_arg is True:
            return True
        if self._roles_defined or self._role_defs:
            if self._role_store is None or getattr(self._role_store, "is_bound", True) is False:
                return True
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
            from agno.os.authz.role_store import RoleStore

            self._role_store = RoleStore(db=self._db, engine=self._engine, roles_claim=self._roles_claim)
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
        scopes, so this must define them rather than skip it as 'already there'."""
        self._require_sync_setup()
        store = self._ensure_role_store()
        if store.get_role_scopes(slug):  # already has scopes -> a definition/edit to preserve
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

    def _apply_assign(self, subject: str, role: str) -> None:
        """Assign a role to a subject, create-if-absent so a runtime promotion survives a restart."""
        self._require_sync_setup()
        role_store = self._ensure_role_store()
        if not role_store.roles_of(subject):  # bootstrap: never clobber an existing (runtime) role
            role_store.assign(subject, role)

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
        store = self.role_store
        if store is None:
            return None  # verify-only / scope-based: AgentOS defaults to ScopeAuthorizationProvider
        if self._trust_token_scopes:
            from agno.os.authz.scope_provider import ScopeAuthorizationProvider

            return [ScopeAuthorizationProvider(), store.provider]
        return store.provider

    @property
    def issuer(self) -> Optional[str]:
        """The pinned token issuer (the ``iss`` claim), or None when not pinned."""
        return self._issuer

    @property
    def _uses_roles(self) -> bool:
        return self._roles_defined

    @property
    def role_store(self) -> Optional["RoleStore"]:
        """The role store, or None when the object is verify-only. Mount the ``/authz`` admin API
        only when this is set. Built on demand once a db is bound."""
        if not self._uses_roles:
            return None
        return self._ensure_role_store() if self._bound else self._role_store

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
