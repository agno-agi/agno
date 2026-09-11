"""The user directory: WHO the users are, and whether they are active.

A peer of :class:`~agno.os.authz.authorization.Authorization`, not a part of it. It stores no
policy, only a roster of people with a ``disabled`` off switch (a revocation that outlives a
valid token) and optional just-in-time provisioning from token claims. Identity is still asserted
by the token; this never stores credentials. Pass it as ``AgentOS(user_directory=...)``:

    AgentOS(db=db, agents=[...], authorization=authz, user_directory=True)
    AgentOS(db=db, agents=[...], authorization=authz,
            user_directory=UserDirectory(auto_provision=False, fail_closed=True))

``True`` builds the roster on the OS db with JIT provisioning on. The object gives you the
knobs, and takes a :class:`UserStore` of your own via ``user_store=`` (or ``db=`` / ``db_url=``
to build one somewhere other than the OS db). It works with no authorization at all, as an
advisory roster keyed off the run's user id; under authorization the off switch is enforced by
the middleware and ``/users`` is mounted for admins.
"""

from typing import TYPE_CHECKING, Any, Optional

from agno.os.authz._db import resolve_authz_db

if TYPE_CHECKING:
    from agno.os.authz.user_store import UserStore

_NEEDS_DB = (
    "AgentOS(user_directory=...) needs a SQL database: the user directory backs the disabled-user "
    "kill switch, and an in-memory one cannot stay consistent across replicas (a revocation would be "
    "lost on restart and never seen by other workers). Pass a SQL-capable db to AgentOS(db=...) for it "
    "to adopt, or give the directory one (UserDirectory(db=...) / user_store=UserStore(db=...))."
)


class UserDirectory:
    """Roster + off switch + JIT provisioning settings, bound to a :class:`UserStore`.

    Args:
        db / db_url: where the roster persists. Optional -- when omitted (and no ``user_store``)
            the directory borrows ``AgentOS(db=...)`` at bind time.
        user_store: bring your own :class:`UserStore`; the directory adopts it as is.
        auto_provision: create a row from the token claims on a subject's first valid request.
            The role they get is the one flagged ``define_role(..., default=True)``; a subject
            who already holds a role keeps it. On by default, since a roster that has to be
            filled by hand before anyone can log in is rarely what a deployment wants.
        email_claim / name_claim: the token claims JIT provisioning reads the profile from.
        fail_closed: how to treat a directory read that errors while checking the off switch.
            False (default) lets the request through -- availability over the kill switch.
            True rejects with 503, so a directory outage cannot silently re-enable a
            disabled account.
    """

    def __init__(
        self,
        *,
        db: Optional[Any] = None,
        db_url: Optional[str] = None,
        user_store: Optional["UserStore"] = None,
        auto_provision: bool = True,
        email_claim: str = "email",
        name_claim: str = "name",
        fail_closed: bool = False,
    ):
        if user_store is not None and (db is not None or db_url is not None):
            raise ValueError("UserDirectory takes either user_store= or db=/db_url=, not both.")
        self.auto_provision = auto_provision
        self.email_claim = email_claim
        self.name_claim = name_claim
        self.fail_closed = fail_closed
        self._user_store: Optional["UserStore"] = user_store
        db = resolve_authz_db(db, db_url)
        if db is not None:
            from agno.os.authz.user_store import UserStore

            self._user_store = UserStore(db=db)

    def _bind(self, os_db: Optional[Any]) -> "UserDirectory":
        """Give the directory a persisted store: build one on the OS db, or adopt the OS db into a
        store created without one. A store that still cannot persist afterwards is refused: the
        directory backs the disabled-user kill switch, and an in-memory one silently loses a
        revocation on restart and never reaches another replica."""
        if self._user_store is None:
            if os_db is None:
                raise ValueError(_NEEDS_DB)
            from agno.os.authz.user_store import UserStore

            self._user_store = UserStore(db=os_db)
        else:
            self._user_store.attach_db(os_db)
        if getattr(self._user_store, "is_bound", True) is False:
            raise ValueError(_NEEDS_DB)
        return self

    @property
    def user_store(self) -> "UserStore":
        """The roster store. Available once AgentOS has bound the directory (or immediately when
        built with a db of its own)."""
        if self._user_store is None:
            raise ValueError(_NEEDS_DB)
        return self._user_store
