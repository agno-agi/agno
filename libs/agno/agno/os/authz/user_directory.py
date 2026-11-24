"""Managed users for AgentOS — a credential-less user directory.

This is the "no IdP" tier. When a customer has no external identity provider,
their app still authenticates users its own way and mints a JWT that AgentOS
verifies (see :class:`~agno.os.middleware.jwt.JWTValidator`). agno does NOT store
passwords and is NOT an authenticator — it owns a *directory* of the users the
app asserts, plus their roles (via :class:`~agno.os.authz.authorization.Authorization`) and enforcement.

What this store buys you over "roles only":
    - **Enumeration / management UX**: list the users that exist, not just react
      to whatever ``sub`` shows up in a token. Pick a user to assign a role.
    - **A real off-switch**: ``disabled`` is checked at the enforcement point, so
      a disabled user is denied *even with a still-valid token* — instant
      revocation you can't get from token expiry alone.
    - **Audit/identity enrichment**: map an opaque ``sub`` to an email/name in the
      decision and change trails.

It is deliberately small: a user is ``id`` (the JWT ``sub``), optional ``email``
/ ``name``, a ``disabled`` flag, timestamps, and free-form ``metadata``. No
credentials, ever.

Two ways users land in the directory:
    - **Explicit**: an admin creates them up front (``upsert``) and assigns roles.
    - **Just-in-time**: on the first valid token from an unknown subject, AgentOS
      can auto-provision a row from the token's claims (opt-in; see
      ``provision_from_claims`` and ``AuthorizationConfig``).

Backed by your own DB (pass ``db``/``db_url``); falls back to
in-memory when neither is given (fine for tests, not for production).
"""

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink

# The directory's list contract: which fields a page can be sorted by / searched
# over, and the defaults. The roles router validates request params against
# these, so they have one owner.
USER_SORT_FIELDS = ("created_at", "updated_at", "id", "email", "name")
USER_SEARCH_FIELDS = ("id", "email", "name")
DEFAULT_USER_SORT_FIELD = "created_at"
DEFAULT_USER_SORT_ORDER = "desc"

# Who a directory user is. A member of the organization that owns the OS on os.agno.com is an org user,
# recorded from their platform-signed token; anyone else (an app's end user, a Slack sender who never
# opened the OS) is an end user. Only ORG_USER is ever written, so a row that predates the column, or a
# stale write racing the token's, still reads as an end user and can never demote an org user.
ORG_USER = "org_user"
END_USER = "end_user"

# Where an org user's platform role and scopes are kept in their metadata, for requests that carry no
# token, such as a Slack message
ORG_ACCESS_KEY = "org_access"
DEFAULT_ORG_ACCESS_MAX_AGE = 7 * 24 * 3600
# Unchanged access is written again at most this often (or half the max age, when shorter), which keeps its age
# current without a write per request
_ORG_ACCESS_REFRESH = 3600
_ORG_ACTOR = "system:os.agno.com"


def user_type_of(row: Optional[dict]) -> str:
    """A row's user type, with a row written before the column existed read as an end user."""
    return ORG_USER if row and row.get("user_type") == ORG_USER else END_USER


def is_platform_token(claims: Optional[Dict[str, Any]]) -> bool:
    """Whether verified claims are an os.agno.com token for an OS: the platform signs its org id and OS id in."""
    if not claims:
        return False
    return isinstance(claims.get("org_id"), str) and isinstance(claims.get("os_id"), str)


def _now() -> int:
    return int(time.time())


def _keep_org_access(existing: Optional[dict], metadata: dict) -> dict:
    """Metadata an app writes, with the os.agno.com access saved on the user kept, since only their token writes it."""
    saved = (existing or {}).get(ORG_ACCESS_KEY)
    if saved is None or ORG_ACCESS_KEY in metadata:
        return metadata
    return {**metadata, ORG_ACCESS_KEY: saved}


def _user_type_value(row: dict) -> Dict[str, str]:
    """The user type a write stores: only ORG_USER, so no write ever turns an org user back into an end user."""
    return {"user_type": ORG_USER} if row.get("user_type") == ORG_USER else {}


_NEEDS_DB = (
    "AgentOS(user_directory=...) needs a SQL database: the user directory backs the disabled-user "
    "kill switch, and an in-memory one cannot stay consistent across replicas (a revocation would be "
    "lost on restart and never seen by other workers). Pass a SQL-capable db to AgentOS(db=...) for it "
    "to adopt, or give the directory one (UserDirectory(db=...) / db_url=...)."
)


class UserDirectory:
    """The user directory: WHO the users are, whether they are active, and how they get in.

    A peer of :class:`~agno.os.authz.authorization.Authorization`, not a part of it. It stores no
    policy, only a roster of people with a ``disabled`` off switch (a revocation that outlives a
    valid token) and the settings for just-in-time provisioning from token claims. Identity is
    still asserted by the token; this never stores credentials. Pass it as
    ``AgentOS(user_directory=...)``:

        AgentOS(db=db, agents=[...], authorization=authz, user_directory=True)
        AgentOS(db=db, agents=[...], authorization=authz,
                user_directory=UserDirectory(auto_provision=False, fail_closed=False))

    ``True`` builds the roster on the OS db with JIT provisioning on. Build it yourself to set the
    knobs, or to persist it somewhere other than the OS db (``db=`` / ``db_url=``); one built with
    neither is in memory until AgentOS lends it the OS db. It works with no authorization at all,
    as an advisory roster keyed off the run's user id; under authorization the off switch is
    enforced by the middleware and ``/users`` is mounted for admins.

    The roster itself is managed here: ``upsert``, ``get``, ``list``, ``set_disabled``, ``remove``
    (and their async twins). Audit is owned by ``Authorization``: at wiring, AgentOS hands this
    directory the ``Authorization(audit=...)`` sink, so every directory change (``user.created``,
    ``user.disabled``, ...) lands in the same change trail as role changes.
    """

    def __init__(
        self,
        *,
        db: Optional[Any] = None,
        db_url: Optional[str] = None,
        auto_provision: bool = True,
        email_claim: str = "email",
        name_claim: str = "name",
        fail_closed: bool = True,
        org_access_max_age: Optional[int] = DEFAULT_ORG_ACCESS_MAX_AGE,
    ):
        """
        Args:
            db / db_url: where the roster persists. ``db`` is an agno database (the same object
                you pass to ``AgentOS(db=...)``); ``db_url`` a SQLAlchemy URL. Omit both and the
                directory is in memory until AgentOS lends it the OS db.
            auto_provision: create a row from the token claims on a subject's first valid request.
                The role they get is the one flagged ``define_role(..., default=True)``; a subject
                who already holds a role keeps it. On by default, since a roster that has to be
                filled by hand before anyone can log in is rarely what a deployment wants.
            email_claim / name_claim: the token claims JIT provisioning reads the profile from.
            fail_closed: how to treat a directory read that errors while checking the off switch.
                True (default) rejects with 503, so a directory outage cannot silently re-enable
                a disabled account: the off switch is a revocation, and a revocation that lapses
                whenever its store is unreachable is not one. False lets the request through,
                availability over the kill switch, for a deployment that accepts that trade.
            org_access_max_age: seconds an org user's platform access counts where no token is sent, such
                as a Slack message. Each os.agno.com token the OS verifies marks its user an org user and
                saves the role and scopes it carries, so Slack grants what os.agno.com last granted; they
                stop counting this long after that user's last request with a token (7 days by default),
                so a member removed from the organization loses Slack access by then. ``None`` saves and
                reads none.
        """
        self.auto_provision = auto_provision
        self.email_claim = email_claim
        self.name_claim = name_claim
        self.fail_closed = fail_closed
        self.org_access_max_age = org_access_max_age
        # The access this process last saved per user and when, so an unchanged token reads nothing
        self._org_access_saved: Dict[str, Tuple[Tuple[Any, ...], int]] = {}
        # Whether this process has seen an os.agno.com token or org user, so a refusal only points at os.agno.com
        # on an OS that is opened there
        self._org_users_seen = False
        self._warned_unmigrated = False
        self._audit: Optional["AuditSink"] = None  # handed over by AgentOS from Authorization(audit=)
        self._mem: Optional[Dict[str, dict]] = None
        from agno.os.authz._db import is_async_authz_db, require_authz_db, resolve_authz_db

        self._db: Any = resolve_authz_db(db, db_url)
        self._db_is_async: bool = is_async_authz_db(self._db)
        if self._db is None:
            # In-memory directory (not persisted). Fine for tests/dev, and AgentOS
            # upgrades it in place via attach_db() when it has a usable db -- see the
            # guard there for why a live one must not stay in-memory.
            self._mem = {}
        else:
            # A db that cannot store the directory fails here, at construction, rather than on
            # the first read or write of a served request.
            require_authz_db(self._db)

    def _bind(self, os_db: Optional[Any]) -> "UserDirectory":
        """Make sure the roster persists before it is served: adopt the OS db into a directory
        built without one, and refuse one that still cannot persist. The directory backs the
        disabled-user kill switch, and an in-memory one silently loses a revocation on restart
        and never reaches another replica."""
        self.attach_db(os_db)
        if not self.is_bound:
            raise ValueError(_NEEDS_DB)
        return self

    @property
    def is_bound(self) -> bool:
        """True once the directory is backed by a database rather than a process-local
        dict (passed in at construction, or adopted later via :meth:`attach_db`)."""
        return self._db is not None

    def attach_db(self, db: Any) -> None:
        """Bind an agno ``Db`` to a store created without one, so the directory persists
        in (and reads fresh from) that DB.

        No-op if the store already has its own DB, or the db isn't SQL-capable. AgentOS
        calls this to default the directory to the OS database, mirroring what it does
        for roles. Any rows written while the directory was in-memory are
        migrated across, so adoption never silently drops a disabled user.
        """
        from agno.os.authz._db import is_async_authz_db, supports_authz

        if self._db is not None or db is None or not supports_authz(db):
            return
        pending = list((self._mem or {}).values())
        self._db = db
        self._db_is_async = is_async_authz_db(db)
        self._mem = None
        # Carry rows written before adoption across verbatim -- including ``disabled``,
        # which upsert() deliberately refuses to set, so a revoked user stays revoked.
        for row in pending:
            self._write(row, insert=True)

    def _attach_audit(self, sink: Optional["AuditSink"]) -> None:
        """What AgentOS calls at wiring: adopt the ``Authorization(audit=...)`` sink as this
        directory's change-audit sink, so one switch records directory changes too. Idempotent."""
        if sink is not None:
            self._audit = sink

    # ------------------------------------------------------------------ audit
    def _emit(
        self,
        action: str,
        target: str,
        before: Optional[List[str]],
        after: Optional[List[str]],
        actor: Optional[str],
    ) -> None:
        if self._audit is None:
            return
        from agno.os.authz.audit import AuditEvent

        self._audit.record(
            AuditEvent(action=action, actor=actor, target=target, before=before, after=after, timestamp=_now())
        )

    # ------------------------------------------------------------------ writes
    def upsert(
        self,
        id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        metadata: Optional[dict] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Create a user, or update the provided fields of an existing one.

        A new user is an end user; only a verified os.agno.com token makes a user an org user
        (:meth:`remember_org_access`).

        Only fields you pass are changed; omitted fields are left as-is on an
        existing user (so a metadata-light update can't blank out an email).
        ``metadata`` replaces the user's metadata, except an org user's saved
        os.agno.com access (its ``org_access`` key), which only their own token writes.
        ``disabled`` is intentionally NOT settable here — use
        :meth:`set_disabled` so enable/disable is an explicit, audited action.
        """
        existing = self.get(id)
        now = _now()
        if existing is None:
            row = {
                "id": id,
                "email": email,
                "name": name,
                "disabled": False,
                "created_at": now,
                "updated_at": now,
                "metadata": metadata or None,
                "user_type": END_USER,
            }
            self._write(row, insert=True)
            self._emit("user.created", id, None, [self._summary(row)], actor)
            return row

        row = dict(existing)
        if email is not None:
            row["email"] = email
        if name is not None:
            row["name"] = name
        if metadata is not None:
            row["metadata"] = _keep_org_access(existing.get("metadata"), metadata)
        row["updated_at"] = now
        self._write(row, insert=False)
        self._emit("user.updated", id, [self._summary(existing)], [self._summary(row)], actor)
        return row

    def set_disabled(self, id: str, disabled: bool, actor: Optional[str] = None) -> dict:
        """Disable (or re-enable) a user. A disabled user is denied at the
        enforcement point even with a valid token — this is the revocation hook."""
        existing = self.get(id)
        if existing is None:
            # Unknown subject: write a single durable tombstone in the TARGET state
            # (the app may mint tokens for a sub we've not seen) and emit only the
            # disable/enable event — no spurious "user.created … active" round-trip.
            now = _now()
            row = {
                "id": id,
                "email": None,
                "name": None,
                "disabled": bool(disabled),
                "created_at": now,
                "updated_at": now,
                "metadata": None,
                "user_type": END_USER,
            }
            self._persist_disabled(id, disabled, tombstone=row)
            self._emit("user.disabled" if disabled else "user.enabled", id, None, [self._summary(row)], actor)
            return row

        if bool(existing["disabled"]) == bool(disabled):
            return existing  # no-op, no event

        row = dict(existing)
        row["disabled"] = bool(disabled)
        row["updated_at"] = _now()
        self._persist_disabled(id, disabled)
        self._emit(
            "user.disabled" if disabled else "user.enabled", id, [self._summary(existing)], [self._summary(row)], actor
        )
        return row

    def _persist_disabled(self, id: str, disabled: bool, tombstone: Optional[dict] = None) -> None:
        """Write ONLY the ``disabled`` flag, atomically. Never a read-modify-write of the
        whole row, so a concurrent profile edit / JIT provision cannot revert it (the lost
        update that would silently un-revoke a user). ``tombstone`` is the full row to seed
        an unknown subject in the in-memory store."""
        if self._mem is not None:
            row = self._mem.get(id)
            if row is not None:
                row["disabled"] = bool(disabled)
                row["updated_at"] = _now()
            elif tombstone is not None:
                self._mem[id] = dict(tombstone)
            return
        self._db.set_authz_user_disabled(id, bool(disabled))

    def remove(self, id: str, actor: Optional[str] = None) -> bool:
        """Delete a user from the directory. Does NOT remove role assignments —
        those live in the role store; remove them there if needed.

        NOTE: delete is NOT a revocation primitive. With JIT auto-provisioning on
        (``UserDirectory(auto_provision=True)``), the next valid token
        from this subject re-creates the row as *active*, and any surviving role
        assignments come back with it. To revoke access, use :meth:`set_disabled`
        (a durable tombstone enforced at every request), not :meth:`remove`."""
        existing = self.get(id)
        if existing is None:
            return False
        if self._mem is not None:
            self._mem.pop(id, None)
        else:
            self._db.delete_authz_user(id)
        self._emit("user.removed", id, [self._summary(existing)], None, actor)
        return True

    def provision_from_claims(
        self,
        subject: str,
        claims: Dict[str, Any],
        email_claim: str = "email",
        name_claim: str = "name",
        actor: Optional[str] = None,
    ) -> Tuple[dict, bool]:
        """Just-in-time: create a directory row for ``subject`` from token claims if it
        doesn't exist yet.

        Returns ``(user, created)``. ``created`` is True only when a new row was made, so a
        caller can grant a default role exactly once (on first login, not every request). If
        the user is already present this is a no-op that returns ``(existing_row, False)``.
        """
        existing = self.get(subject)
        if existing is not None:
            return existing, False
        user = self.upsert(
            subject,
            email=claims.get(email_claim),
            name=claims.get(name_claim),
            actor=actor or "system:jit",
        )
        return user, True

    # ------------------------------------------------------------------ reads
    def get(self, id: str) -> Optional[dict]:
        if self._mem is not None:
            row = self._mem.get(id)
            return dict(row) if row else None

        return self._db.get_authz_user(id)

    def _filtered_mem_rows(
        self, include_disabled: bool, search: Optional[str], user_type: Optional[str] = None
    ) -> List[dict]:
        """The in-memory equivalent of the SQL filters, for the unbound dev/test store."""
        rows = list((self._mem or {}).values())
        if user_type is not None:
            rows = [r for r in rows if user_type_of(r) == user_type]
        if not include_disabled:
            rows = [r for r in rows if not r["disabled"]]
        if search:
            needle = search.casefold()
            rows = [
                r for r in rows if any(str(r.get(f) or "").casefold().find(needle) >= 0 for f in USER_SEARCH_FIELDS)
            ]
        return rows

    def list(
        self,
        limit: int = 1000,
        include_disabled: bool = True,
        offset: int = 0,
        search: Optional[str] = None,
        sort_by: str = DEFAULT_USER_SORT_FIELD,
        order: str = DEFAULT_USER_SORT_ORDER,
        user_type: Optional[str] = None,
    ) -> List[dict]:
        """A page of users, optionally excluding disabled ones.

        ``offset``/``limit`` page in the store so callers don't materialise the
        whole directory; pair with :meth:`count` for the total. ``search``
        filters case-insensitively by substring across id, email, and name;
        ``user_type`` (:data:`ORG_USER` or :data:`END_USER`) keeps that type only;
        ``sort_by`` is any of :data:`USER_SORT_FIELDS` (newest first by default)."""
        if sort_by not in USER_SORT_FIELDS:
            raise ValueError(f"sort_by must be one of {USER_SORT_FIELDS}, got {sort_by!r}")
        descending = order != "asc"
        if self._mem is not None:
            # Rows missing the field (email/name are optional) go last in either
            # direction, matching the nullslast() on the SQL path.
            rows = self._filtered_mem_rows(include_disabled, search, user_type)
            present = sorted(
                (r for r in rows if r.get(sort_by) is not None), key=lambda r: r[sort_by], reverse=descending
            )
            missing = [r for r in rows if r.get(sort_by) is None]
            return [dict(r) for r in (present + missing)[offset : offset + limit]]

        return self._db.list_authz_users(
            limit=limit,
            offset=offset,
            include_disabled=include_disabled,
            search=search,
            sort_by=sort_by,
            order=order,
            user_type=user_type,
        )

    def count(
        self, include_disabled: bool = True, search: Optional[str] = None, user_type: Optional[str] = None
    ) -> int:
        """Total number of users (for pagination), with the same filters as
        :meth:`list`."""
        if self._mem is not None:
            return len(self._filtered_mem_rows(include_disabled, search, user_type))

        return int(self._db.count_authz_users(include_disabled=include_disabled, search=search, user_type=user_type))

    def _mem_count_by_status(self) -> Dict[str, int]:
        rows = list((self._mem or {}).values())
        return {"total": len(rows), "disabled": sum(1 for r in rows if r.get("disabled"))}

    def _mem_ids(self, include_disabled: bool) -> List[str]:
        return sorted(r["id"] for r in self._filtered_mem_rows(include_disabled, None))

    def _mem_created_by_day(self, starting_at: Optional[int], ending_before: Optional[int]) -> List[Dict[str, int]]:
        seconds_per_day = 24 * 60 * 60
        counts: Dict[int, int] = {}
        for row in (self._mem or {}).values():
            created_at = int(row["created_at"])
            if starting_at is not None and created_at < starting_at:
                continue
            if ending_before is not None and created_at >= ending_before:
                continue
            day = created_at - (created_at % seconds_per_day)
            counts[day] = counts.get(day, 0) + 1
        return [{"date": day, "count": counts[day]} for day in sorted(counts)]

    def count_by_status(self) -> Dict[str, int]:
        """``{"total": n, "disabled": n}`` from one read, so the pair is consistent."""
        if self._mem is not None:
            return self._mem_count_by_status()

        return dict(self._db.count_authz_users_by_status())

    def ids(self, include_disabled: bool = True) -> List[str]:
        """Every user id, sorted. For bulk lookups keyed on the id (resolving roles for
        the whole directory) where :meth:`list` would fetch profile columns nobody reads."""
        if self._mem is not None:
            return self._mem_ids(include_disabled)

        return list(self._db.list_authz_user_ids(include_disabled=include_disabled))

    def created_by_day(
        self, starting_at: Optional[int] = None, ending_before: Optional[int] = None
    ) -> List[Dict[str, int]]:
        """Users created per UTC day as ``{"date": <day start epoch>, "count": n}``,
        oldest first; days with no registrations are absent. ``starting_at`` and
        ``ending_before`` bound ``created_at`` (inclusive / exclusive, epoch seconds).
        Deleted users drop out of history, so this is the directory as it is now."""
        if self._mem is not None:
            return self._mem_created_by_day(starting_at, ending_before)

        return self._db.count_authz_users_by_day(starting_at=starting_at, ending_before=ending_before)

    def is_disabled(self, id: Optional[str]) -> bool:
        """Fast path for the enforcement point: True only if the user exists AND is
        disabled. Unknown subjects are NOT disabled (the app may legitimately mint
        tokens for users not yet in the directory)."""
        if not id:
            return False
        if self._mem is not None:
            row = self._mem.get(id)
            return bool(row and row["disabled"])

        return bool(self._db.is_authz_user_disabled(id))

    # ------------------------------------------------------------------ org access
    def org_access(self, row: Optional[dict]) -> Optional[Dict[str, Any]]:
        """An org user's saved platform access (``role``, ``scopes``, ``org_id``, ``at``) while it still counts;
        None for an end user, or when none is saved or it expired."""
        if not self.org_access_max_age or user_type_of(row) != ORG_USER or row is None:
            return None
        self._org_users_seen = True
        saved = (row.get("metadata") or {}).get(ORG_ACCESS_KEY)
        if not isinstance(saved, dict):
            return None
        scopes, at = saved.get("scopes"), saved.get("at")
        if not isinstance(scopes, list) or not isinstance(at, (int, float)):
            return None
        if _now() - at > self.org_access_max_age:
            return None
        return {**saved, "scopes": [scope for scope in scopes if isinstance(scope, str)]}

    @property
    def serves_org_users(self) -> bool:
        """Whether this OS is opened on os.agno.com, as far as this process has seen: an os.agno.com token or an org
        user. False on a self-hosted OS whose tokens never come from os.agno.com."""
        return bool(self.org_access_max_age) and self._org_users_seen

    @property
    def _org_access_refresh(self) -> int:
        """How often unchanged access is written again: hourly, or within half the max age so a visit always renews
        access that would otherwise lapse before the next write."""
        return min(_ORG_ACCESS_REFRESH, max(1, (self.org_access_max_age or 0) // 2))

    def org_scopes(self, row: Optional[dict]) -> Optional[List[str]]:
        """The scopes an org user's last os.agno.com token carried while they still count, its denies included as
        the scope checks read them; None when there are none."""
        from agno.os.scopes import with_denies

        access = self.org_access(row)
        return with_denies(access["scopes"], access.get("denies")) if access is not None else None

    def _org_access_pending(self, id: str, claims: Dict[str, Any], scopes: List[str]) -> Optional[Dict[str, Any]]:
        """The access to save for a user, or None when saving is off, the token is not the platform's, or this
        process saved the same access recently."""
        from agno.os.scopes import DENY_PREFIX

        if not self.org_access_max_age or not id or not is_platform_token(claims):
            return None
        self._org_users_seen = True
        role = claims.get("role") if isinstance(claims.get("role"), str) else None
        denies = claims.get("denies")
        access = {
            "role": role,
            # The allows only: the denies the request's scope list carries are saved from the claim below
            "scopes": sorted(
                {scope for scope in scopes if isinstance(scope, str) and not scope.startswith(DENY_PREFIX)}
            ),
            # Applied over the allows wherever the saved access is used, as the token's are
            "denies": sorted({d for d in denies if isinstance(d, str)}) if isinstance(denies, list) else [],
            "org_id": claims["org_id"],
        }
        saved = self._org_access_saved.get(id)
        if (
            saved is not None
            and saved[0] == self._org_access_key(access)
            and _now() - saved[1] < self._org_access_refresh
        ):
            return None
        return access

    @staticmethod
    def _org_profile(id: str, claims: Dict[str, Any]) -> Dict[str, str]:
        """The email an os.agno.com token gives its user: its subject is the account email, with no email claim.
        No name is taken from it, since its username is the email too."""
        email = claims.get("email") if isinstance(claims.get("email"), str) else (id if "@" in id else None)
        return {"email": email} if email else {}

    def _with_org_access(
        self, row: Optional[dict], access: Dict[str, Any], profile: Optional[Dict[str, str]] = None
    ) -> Optional[dict]:
        """The row marked an org user with this access, and the profile fields it lacks filled in; None when there is
        no user, or its saved access is current and its profile complete."""
        if row is None:
            return None
        metadata = row.get("metadata") or {}
        saved = metadata.get(ORG_ACCESS_KEY)
        now = _now()
        # Only an empty field is filled, so a name or email an admin set is kept
        fills = {k: v for k, v in (profile or {}).items() if not row.get(k)}
        if user_type_of(row) == ORG_USER and isinstance(saved, dict) and not fills:
            current = {k: v for k, v in saved.items() if k != "at"}
            at = saved.get("at")
            if current == access and isinstance(at, (int, float)) and now - at < self._org_access_refresh:
                return None
        updated = {**row, **fills}
        updated["user_type"] = ORG_USER
        updated["metadata"] = {**metadata, ORG_ACCESS_KEY: {**access, "at": now}}
        return updated

    def _unmigrated(self, row: dict) -> bool:
        """Whether a row comes from a users table from before migration v3.2.2, which has no user_type to record an
        org user in; said once."""
        if "user_type" in row:
            return False
        if not self._warned_unmigrated:
            self._warned_unmigrated = True
            from agno.utils.log import log_warning

            log_warning(
                "The user directory's table has no user_type column, so os.agno.com members are not recorded and get "
                "no access in Slack. Apply migration v3.2.2 with POST /databases/all/migrate."
            )
        return True

    @staticmethod
    def _org_access_key(access: Dict[str, Any]) -> Tuple[Any, ...]:
        return (access["role"], tuple(access["scopes"]), tuple(access["denies"]), access["org_id"])

    @staticmethod
    def _org_access_change(before: dict, after: dict) -> Optional[Tuple[Optional[List[str]], List[str]]]:
        """The role and scopes before and after a save when they changed, for the audit; None when only the age moved."""

        def summary(row: dict) -> Optional[List[str]]:
            saved = (row.get("metadata") or {}).get(ORG_ACCESS_KEY)
            if user_type_of(row) != ORG_USER or not isinstance(saved, dict):
                return None
            return [f"role:{saved.get('role')}", *(saved.get("scopes") or [])]

        old, new = summary(before), summary(after)
        return None if old == new or new is None else (old, new)

    def _mark_org_access_saved(self, id: str, access: Dict[str, Any], current: dict, saved_row: dict) -> None:
        """Remember that this access is saved, so the next requests within the refresh skip it. Marked only once the
        save is done, so a request racing it saves again rather than skipping a save that has not landed, and only
        when the stored row already was an org user: that proves the table has user_type, so a table migrated
        meanwhile still records the user on their next request."""
        if user_type_of(current) != ORG_USER:
            return
        saved = (saved_row.get("metadata") or {}).get(ORG_ACCESS_KEY) or {}
        at = saved.get("at")
        if isinstance(at, (int, float)):
            self._org_access_saved[id] = (self._org_access_key(access), int(at))

    def remember_org_access(
        self,
        id: str,
        claims: Dict[str, Any],
        scopes: List[str],
        row: Optional[dict] = None,
    ) -> None:
        """Mark a verified os.agno.com token's user an org user and save the role and scopes it carries, for
        requests that carry no token. Any other token, or a user not in the directory, saves nothing. ``row`` is
        the user's row when the caller already read it."""
        pending = self._org_access_pending(id, claims, scopes)
        if pending is None:
            return
        current = row if row is not None else self.get(id)
        if current is None:
            return
        if self._unmigrated(current):
            return
        updated = self._with_org_access(current, pending, self._org_profile(id, claims))
        if updated is not None:
            self._write(updated, insert=False)
            change = self._org_access_change(current, updated)
            if change is not None:
                self._emit("user.org_access", id, change[0], change[1], _ORG_ACTOR)
        self._mark_org_access_saved(id, pending, current, updated or current)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _summary(row: dict) -> str:
        """Compact, non-secret one-line representation for the audit before/after."""
        bits = [row["id"]]
        if row.get("email"):
            bits.append(row["email"])
        bits.append("disabled" if row.get("disabled") else "active")
        return " ".join(bits)

    def _row_to_dict(self, r) -> dict:
        return {
            "id": r["id"],
            "email": r["email"],
            "name": r["name"],
            "disabled": bool(r["disabled"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "metadata": json.loads(r["user_metadata"]) if r["user_metadata"] else None,
            "user_type": user_type_of(r),
        }

    def _write(self, row: dict, insert: bool = True) -> None:
        """Persist a directory row. ``insert`` is vestigial -- the store upserts, so a
        caller never has to know whether the row already existed."""
        if self._mem is not None:
            self._mem[row["id"]] = dict(row)
            return

        self._db.upsert_authz_user(
            row["id"],
            {
                "email": row["email"],
                "name": row["name"],
                "disabled": bool(row["disabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "metadata": row.get("metadata"),
                **_user_type_value(row),
            },
        )

    # =====================================================================
    # Async variants
    #
    # Twins of every public method (plus the DB-touching helpers), so the directory works on
    # an async request path. The in-memory dev/test store has no I/O, so those branches are
    # shared with the sync path; the DB branches await through :meth:`_adb`, which drives an
    # async backend natively and a sync one in a worker thread.
    # =====================================================================
    async def _adb(self, name: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self._db, name)
        if self._db_is_async:
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _aemit(
        self,
        action: str,
        target: str,
        before: Optional[List[str]],
        after: Optional[List[str]],
        actor: Optional[str],
    ) -> None:
        if self._audit is None:
            return
        from agno.os.authz.audit import AuditEvent

        await self._audit.arecord(
            AuditEvent(action=action, actor=actor, target=target, before=before, after=after, timestamp=_now())
        )

    async def _awrite(self, row: dict, insert: bool = True) -> None:
        if self._mem is not None:
            self._mem[row["id"]] = dict(row)
            return
        await self._adb(
            "upsert_authz_user",
            row["id"],
            {
                "email": row["email"],
                "name": row["name"],
                "disabled": bool(row["disabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "metadata": row.get("metadata"),
                **_user_type_value(row),
            },
        )

    async def _apersist_disabled(self, id: str, disabled: bool, tombstone: Optional[dict] = None) -> None:
        if self._mem is not None:
            row = self._mem.get(id)
            if row is not None:
                row["disabled"] = bool(disabled)
                row["updated_at"] = _now()
            elif tombstone is not None:
                self._mem[id] = dict(tombstone)
            return
        await self._adb("set_authz_user_disabled", id, bool(disabled))

    async def aget(self, id: str) -> Optional[dict]:
        if self._mem is not None:
            row = self._mem.get(id)
            return dict(row) if row else None
        return await self._adb("get_authz_user", id)

    async def aupsert(
        self,
        id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        metadata: Optional[dict] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Async twin of :meth:`upsert`."""
        existing = await self.aget(id)
        now = _now()
        if existing is None:
            row = {
                "id": id,
                "email": email,
                "name": name,
                "disabled": False,
                "created_at": now,
                "updated_at": now,
                "metadata": metadata or None,
                "user_type": END_USER,
            }
            await self._awrite(row, insert=True)
            await self._aemit("user.created", id, None, [self._summary(row)], actor)
            return row

        row = dict(existing)
        if email is not None:
            row["email"] = email
        if name is not None:
            row["name"] = name
        if metadata is not None:
            row["metadata"] = _keep_org_access(existing.get("metadata"), metadata)
        row["updated_at"] = now
        await self._awrite(row, insert=False)
        await self._aemit("user.updated", id, [self._summary(existing)], [self._summary(row)], actor)
        return row

    async def aset_disabled(self, id: str, disabled: bool, actor: Optional[str] = None) -> dict:
        """Async twin of :meth:`set_disabled`."""
        existing = await self.aget(id)
        if existing is None:
            now = _now()
            row = {
                "id": id,
                "email": None,
                "name": None,
                "disabled": bool(disabled),
                "created_at": now,
                "updated_at": now,
                "metadata": None,
                "user_type": END_USER,
            }
            await self._apersist_disabled(id, disabled, tombstone=row)
            await self._aemit("user.disabled" if disabled else "user.enabled", id, None, [self._summary(row)], actor)
            return row

        if bool(existing["disabled"]) == bool(disabled):
            return existing

        row = dict(existing)
        row["disabled"] = bool(disabled)
        row["updated_at"] = _now()
        await self._apersist_disabled(id, disabled)
        await self._aemit(
            "user.disabled" if disabled else "user.enabled", id, [self._summary(existing)], [self._summary(row)], actor
        )
        return row

    async def aremove(self, id: str, actor: Optional[str] = None) -> bool:
        """Async twin of :meth:`remove`."""
        existing = await self.aget(id)
        if existing is None:
            return False
        if self._mem is not None:
            self._mem.pop(id, None)
        else:
            await self._adb("delete_authz_user", id)
        await self._aemit("user.removed", id, [self._summary(existing)], None, actor)
        return True

    async def aprovision_from_claims(
        self,
        subject: str,
        claims: Dict[str, Any],
        email_claim: str = "email",
        name_claim: str = "name",
        actor: Optional[str] = None,
    ) -> Tuple[dict, bool]:
        """Async twin of :meth:`provision_from_claims`."""
        existing = await self.aget(subject)
        if existing is not None:
            return existing, False
        user = await self.aupsert(
            subject,
            email=claims.get(email_claim),
            name=claims.get(name_claim),
            actor=actor or "system:jit",
        )
        return user, True

    async def alist(
        self,
        limit: int = 1000,
        include_disabled: bool = True,
        offset: int = 0,
        search: Optional[str] = None,
        sort_by: str = DEFAULT_USER_SORT_FIELD,
        order: str = DEFAULT_USER_SORT_ORDER,
        user_type: Optional[str] = None,
    ) -> List[dict]:
        """Async twin of :meth:`list`."""
        if sort_by not in USER_SORT_FIELDS:
            raise ValueError(f"sort_by must be one of {USER_SORT_FIELDS}, got {sort_by!r}")
        if self._mem is not None:
            descending = order != "asc"
            rows = self._filtered_mem_rows(include_disabled, search, user_type)
            present = sorted(
                (r for r in rows if r.get(sort_by) is not None), key=lambda r: r[sort_by], reverse=descending
            )
            missing = [r for r in rows if r.get(sort_by) is None]
            return [dict(r) for r in (present + missing)[offset : offset + limit]]
        return await self._adb(
            "list_authz_users",
            limit=limit,
            offset=offset,
            include_disabled=include_disabled,
            search=search,
            sort_by=sort_by,
            order=order,
            user_type=user_type,
        )

    async def acount(
        self, include_disabled: bool = True, search: Optional[str] = None, user_type: Optional[str] = None
    ) -> int:
        """Async twin of :meth:`count`."""
        if self._mem is not None:
            return len(self._filtered_mem_rows(include_disabled, search, user_type))
        return int(
            await self._adb("count_authz_users", include_disabled=include_disabled, search=search, user_type=user_type)
        )

    async def acount_by_status(self) -> Dict[str, int]:
        """Async twin of :meth:`count_by_status`."""
        if self._mem is not None:
            return self._mem_count_by_status()
        return dict(await self._adb("count_authz_users_by_status"))

    async def aids(self, include_disabled: bool = True) -> List[str]:
        """Async twin of :meth:`ids`."""
        if self._mem is not None:
            return self._mem_ids(include_disabled)
        return list(await self._adb("list_authz_user_ids", include_disabled=include_disabled))

    async def acreated_by_day(
        self, starting_at: Optional[int] = None, ending_before: Optional[int] = None
    ) -> List[Dict[str, int]]:
        """Async twin of :meth:`created_by_day`."""
        if self._mem is not None:
            return self._mem_created_by_day(starting_at, ending_before)
        return await self._adb("count_authz_users_by_day", starting_at=starting_at, ending_before=ending_before)

    async def ais_disabled(self, id: Optional[str]) -> bool:
        """Async twin of :meth:`is_disabled`."""
        if not id:
            return False
        if self._mem is not None:
            row = self._mem.get(id)
            return bool(row and row["disabled"])
        return bool(await self._adb("is_authz_user_disabled", id))

    async def aremember_org_access(
        self,
        id: str,
        claims: Dict[str, Any],
        scopes: List[str],
        row: Optional[dict] = None,
    ) -> None:
        """Async twin of :meth:`remember_org_access`."""
        pending = self._org_access_pending(id, claims, scopes)
        if pending is None:
            return
        current = row if row is not None else await self.aget(id)
        if current is None:
            return
        if self._unmigrated(current):
            return
        updated = self._with_org_access(current, pending, self._org_profile(id, claims))
        if updated is not None:
            await self._awrite(updated, insert=False)
            change = self._org_access_change(current, updated)
            if change is not None:
                await self._aemit("user.org_access", id, change[0], change[1], _ORG_ACTOR)
        self._mark_org_access_saved(id, pending, current, updated or current)
