"""One object for AgentOS authorization: verification, roles, users, audit, admin API.

Standing up managed roles + a user directory + the admin API by hand means assembling a dozen
objects (a ``DbAuditSink``, a ``ManagedRoleStore``, a ``ManagedUserStore``, an
``AuthorizationConfig``, a ``UserDirectoryConfig``, a ``ScopeAuthorizationProvider``, the store's
provider, two router factories, two ``include_router`` calls) and keeping four of them pointed at
the same database. :class:`Authorization` owns all of that and wires itself into AgentOS:

    from agno.os.authz import Authorization

    authz = Authorization(db=db, audit=True, trust_token_scopes=True,
                          verification_keys=KEYS, audience=OS_ID)
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    authz.define_role("runner", ["agents:*:read", "agents:*:run"])
    authz.seed(admin=ADMIN_SUBJECT, users=[("bob", {"email": "bob@co", "role": "viewer"})])

    agent_os = AgentOS(id=OS_ID, db=db, agents=[...], authorization=authz)

Roles are opt-in. Verification lives here because it already lives under authorization today
(``authorization=True`` + ``AuthorizationConfig(verification_keys=...)``), and plenty of setups
verify tokens with no roles at all (isolation, scope-based access, service accounts). So the
verify-only case is a one-liner:

    Authorization(verification_keys=KEYS, audience=OS_ID)   # no roles, no ceremony

Everything the facade builds is still reachable as a primitive: pass your own ``role_store=`` /
``user_directory=<store>`` / ``authorization_provider=`` / ``engine=`` and the facade uses them instead of
building its own. Simplicity by default, full control when you need it.

The database is borrowed from AgentOS when you don't pass one, so you never write ``db=`` twice --
role and user definitions are buffered and applied once the db binds (the same way
``AgentOS(user_directory=True)`` adopts the OS db).
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from agno.os.authz._db import is_async_authz_db, resolve_authz_db
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink
    from agno.os.authz.engine import PolicyEngine
    from agno.os.authz.provider import AuthorizationProvider
    from agno.os.authz.role_store import ManagedRoleStore
    from agno.os.authz.user_store import ManagedUserStore
    from agno.os.config import AuthorizationConfig, UserDirectoryConfig

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
    "Authorization.define_role()/seed() write roles and users at setup time and need a synchronous "
    "database, but the bound database is async ({db_type}). Give AgentOS a sync db for setup, or "
    "configure roles/users yourself through the async store API (ManagedRoleStore.aset_role_scopes / "
    "ManagedUserStore.aupsert) and pass them via Authorization(role_store=..., user_directory=<store>). A "
    "facade with pre-built stores and no define_role()/seed() calls works against an async db."
)

# A scope entry as accepted by ManagedRoleStore.set_role_scopes.
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
        user_directory: Union[bool, "ManagedUserStore", None] = None,
        auto_provision: bool = True,
        default_role: Optional[str] = None,
        # --- escape hatches (bring your own) ---
        authorization_provider: Optional[Union["AuthorizationProvider", List["AuthorizationProvider"]]] = None,
        engine: Optional["PolicyEngine"] = None,
        role_store: Optional["ManagedRoleStore"] = None,
    ):
        """
        Args:
            db / db_url: the SQL database for roles/users/audit. Optional -- when omitted the
                facade borrows ``AgentOS(db=...)`` at bind time, so you pass a db once.
            verification_keys, jwks_file, algorithm, verify_audience, audience, issuer,
                admin_scope, excluded_route_paths: JWT verification settings. Used with or
                without roles (verify-only / scope-based / isolation deployments set just these).
            audit: ``True`` builds a ``DbAuditSink`` from the bound db (feeds both the change and
                decision trails); pass an ``AuditSink`` to use your own; ``False`` disables it.
            trust_token_scopes: run a scope plane alongside managed roles, so operators authorized
                by their token scopes and end users authorized by the role store both work
                (composed with OR). No effect without roles.
            user_directory: the directory, one knob (mirrors ``AgentOS(user_directory=bool | ...)``).
                ``None`` (default) is auto -- built only when roles are used or users are seeded, so a
                pure verify-only ``Authorization`` builds none. ``True`` always builds one; ``False``
                never; a ``ManagedUserStore`` uses yours.
            auto_provision / default_role: JIT-provision an unknown subject on first valid token,
                and the role to grant them (falls back to the role flagged ``default=True``).
            authorization_provider / engine / role_store: primitives. Supply any and the facade uses
                it instead of building its own (bring your own directory store via
                ``user_directory=<ManagedUserStore>``).
        """
        # Verification settings, splatted into the AuthorizationConfig at build time. Typed Any so
        # the per-key kwarg splat type-checks against AuthorizationConfig's specific field types.
        self._verification: Dict[str, Any] = {
            "verification_keys": verification_keys,
            "jwks_file": jwks_file,
            "algorithm": algorithm,
            "verify_audience": verify_audience,
            "audience": audience,
            "issuer": issuer,
            "admin_scope": admin_scope,
            "excluded_route_paths": excluded_route_paths,
        }
        self._audit_arg = audit
        self._trust_token_scopes = trust_token_scopes
        self._auto_provision = auto_provision
        self._default_role = default_role
        self._provider_override = authorization_provider
        self._engine = engine

        self._role_store: Optional["ManagedRoleStore"] = role_store
        self._audit_sink: Optional["AuditSink"] = None

        # Directory is one knob, user_directory: True/False/None(auto), or a ManagedUserStore to bring
        # your own. None = auto: built only when roles are used or users are seeded, so a pure
        # verify-only Authorization(verification_keys=...) builds NO directory.
        self._user_directory_arg = user_directory
        self._user_store: Optional["ManagedUserStore"] = (
            user_directory if user_directory is not None and not isinstance(user_directory, bool) else None
        )

        # Roles are in play if any were defined, or a store/engine was supplied.
        self._roles_defined = role_store is not None or engine is not None
        # Whether seed() has added directory users -- a signal that a directory is wanted under auto.
        self._users_seeded = False

        # Buffers applied at bind time (used when no db is available yet).
        self._role_defs: List[Tuple[str, List[ScopeInput], bool, Optional[str], Optional[str]]] = []
        self._seed_calls: List[Tuple[Optional[str], str, Optional[List[Tuple[str, Dict[str, Any]]]]]] = []
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
        a role's scopes after first boot, use the admin API (or ``ManagedRoleStore.set_role_scopes``
        directly for a declarative, code-owns-the-role model). Chainable."""
        self._roles_defined = True
        if self._bound:
            self._apply_role_def(slug, scopes, default, name, description)
        else:
            self._role_defs.append((slug, scopes, default, name, description))
        return self

    def seed(
        self,
        *,
        admin: Optional[str] = None,
        admin_role: str = _ADMIN_ROLE,
        users: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
    ) -> "Authorization":
        """Bootstrap an admin and directory users, without ever clobbering runtime state.

        ``admin=<subject>`` grants ``admin_role`` (default ``"admin"`` -- define it first) to that
        subject if they hold no role yet. ``users=[(subject, {"email", "name", "role"})]`` adds each
        to the directory and assigns its role, again only if the subject is new.

        BOOTSTRAP semantics: anything that already exists is left as is, so seeding on every start is
        safe -- an operator who promoted a user or edited a profile through the admin API keeps that
        change across restarts. Manage users/assignments after first boot through the admin API."""
        if users:
            self._users_seeded = True
        if self._bound:
            self._apply_seed(admin, admin_role, users)
        else:
            self._seed_calls.append((admin, admin_role, users))
        return self

    # ------------------------------------------------------------------ binding
    def _bind(self, os_db: Optional[Any] = None) -> "Authorization":
        """Resolve the database (own, else the OS db), build the requested stores, and flush any
        buffered role/user definitions. Idempotent: a second call (e.g. AgentOS re-binding an
        already-bound facade) is a no-op."""
        if self._bound:
            return self
        self._db = self._db or os_db
        if self._db is None:
            raise ValueError(_NEEDS_DB)
        self._db_is_async = is_async_authz_db(self._db)
        self._audit_sink = self._resolve_audit()
        if self._roles_defined or self._role_defs:
            self._ensure_role_store()
        if self._directory_wanted():
            self._ensure_user_store()
        self._bound = True
        self._flush()
        return self

    def _flush(self) -> None:
        for slug, scopes, default, name, description in self._role_defs:
            self._apply_role_def(slug, scopes, default, name, description)
        self._role_defs.clear()
        for admin, admin_role, users in self._seed_calls:
            self._apply_seed(admin, admin_role, users)
        self._seed_calls.clear()

    def _directory_wanted(self) -> bool:
        """Whether a user directory should exist. Auto (``None``) builds one only once roles are used
        or users are seeded, so verify-only stays store-free."""
        if self._user_directory_arg is False:
            return False
        if self._user_directory_arg is True or self._user_store is not None:
            return True
        return self._roles_defined or self._users_seeded

    def _resolve_audit(self) -> Optional["AuditSink"]:
        if self._audit_arg is False or self._audit_arg is None:
            return None
        if self._audit_arg is True:
            from agno.os.authz.audit import DbAuditSink

            return DbAuditSink(db=self._db)
        return self._audit_arg  # an AuditSink instance

    def _ensure_role_store(self) -> "ManagedRoleStore":
        if self._role_store is None:
            from agno.os.authz.role_store import ManagedRoleStore

            self._role_store = ManagedRoleStore(db=self._db, engine=self._engine)
        else:
            self._role_store.attach_db(self._db)
        if self._audit_sink is not None:
            self._role_store.attach_audit(self._audit_sink)
        return self._role_store

    def _ensure_user_store(self) -> "ManagedUserStore":
        if self._user_store is None:
            from agno.os.authz.user_store import ManagedUserStore

            self._user_store = ManagedUserStore(db=self._db)
        else:
            self._user_store.attach_db(self._db)
        if self._audit_sink is not None:
            self._user_store.attach_audit(self._audit_sink)
        return self._user_store

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

    def _apply_seed(
        self, admin: Optional[str], admin_role: str, users: Optional[List[Tuple[str, Dict[str, Any]]]]
    ) -> None:
        self._require_sync_setup()
        role_store = self._ensure_role_store()
        if admin is not None:
            if not role_store.roles_of(admin):  # bootstrap: never override an existing assignment
                role_store.assign(admin, admin_role)
            if self._directory_wanted():
                users_store = self._ensure_user_store()
                if users_store.get(admin) is None:
                    users_store.upsert(admin, name="Bootstrap admin")
            # Checked once at finalize (authorization_config), so the warning never depends on whether
            # define_role ran before or after this seed.
            self._seeded_admins.append((admin, admin_role))
        for subject, info in users or []:
            info = dict(info)
            role = info.pop("role", None)
            if self._directory_wanted():
                users_store = self._ensure_user_store()
                if users_store.get(subject) is None:  # bootstrap: keep an admin's profile edits
                    users_store.upsert(subject, email=info.get("email"), name=info.get("name"))
            if role and not role_store.roles_of(subject):  # bootstrap: keep a runtime promotion
                role_store.assign(subject, role)

    def _require_sync_setup(self) -> None:
        """Setup writes run synchronously; refuse an async db with a clear, facade-level message rather
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

    # ------------------------------------------------------------------ provider
    def _provider(self) -> Optional[Union["AuthorizationProvider", List["AuthorizationProvider"]]]:
        """The provider AgentOS should enforce with, or None to fall back to scope RBAC."""
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
    def _uses_roles(self) -> bool:
        return self._roles_defined

    # ------------------------------------------------------------------ what AgentOS reads
    @property
    def role_store(self) -> Optional["ManagedRoleStore"]:
        """The role store, or None when the facade is verify-only. Mount the ``/authz`` admin API
        only when this is set. Built on demand once a db is bound."""
        if not self._uses_roles:
            return None
        return self._ensure_role_store() if self._bound else self._role_store

    @property
    def user_store(self) -> Optional["ManagedUserStore"]:
        """The directory store, or None when no directory is wanted. Mount the ``/users`` admin API
        only when this is set. Built on demand once a db is bound."""
        if not self._directory_wanted():
            return None
        return self._ensure_user_store() if self._bound else self._user_store

    @property
    def audit_sink(self) -> Optional["AuditSink"]:
        """The resolved audit sink (feeds ``AgentOS.audit`` -- both trails), or None."""
        return self._audit_sink

    def authorization_config(self) -> "AuthorizationConfig":
        """The ``AuthorizationConfig`` AgentOS enforces: verification settings plus the composed
        provider (or none, so AgentOS uses scope RBAC). AgentOS calls this once after all setup, so it
        is where a seeded admin whose role does not grant admin is finally validated."""
        from agno.os.config import AuthorizationConfig

        self._check_seeded_admins()
        return AuthorizationConfig(authorization_provider=self._provider(), **self._verification)

    def user_directory_config(self) -> Optional["UserDirectoryConfig"]:
        """The ``UserDirectoryConfig`` for AgentOS, or None when no directory is configured."""
        store = self.user_store
        if store is None:
            return None
        from agno.os.config import UserDirectoryConfig

        return UserDirectoryConfig(
            user_store=store,
            auto_provision=self._auto_provision,
            default_role=self._default_role,
        )
