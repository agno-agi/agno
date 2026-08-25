"""Managed users for AgentOS — a credential-less user directory.

This is the "no IdP" tier. When a customer has no external identity provider,
their app still authenticates users its own way and mints a JWT that AgentOS
verifies (see :class:`~agno.os.middleware.jwt.JWTValidator`). agno does NOT store
passwords and is NOT an authenticator — it owns a *directory* of the users the
app asserts, plus their roles (via :class:`ManagedRoleStore`) and enforcement.

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

Backed by your own DB via SQLAlchemy (pass ``db_url``/``engine``); falls back to
in-memory when neither is given (fine for tests, not for production).
"""

import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink

# The directory's list contract: which fields a page can be sorted by / searched
# over, and the defaults. The roles router validates request params against
# these, so they have one owner.
USER_SORT_FIELDS = ("created_at", "updated_at", "id", "email", "name")
USER_SEARCH_FIELDS = ("id", "email", "name")
DEFAULT_USER_SORT_FIELD = "created_at"
DEFAULT_USER_SORT_ORDER = "desc"


def _now() -> int:
    return int(time.time())


class ManagedUserStore:
    """Credential-less user directory. agno-native; identity asserted externally."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        engine: Optional[Any] = None,
        table_name: str = "authz_users",
        create_table: bool = True,
        audit: Optional["AuditSink"] = None,
        db: Optional[Any] = None,
    ):
        """
        Args:
            db_url: SQLAlchemy URL for the DB that holds the directory (e.g.
                ``postgresql+psycopg://...`` or ``sqlite:///users.db``). If
                ``db_url``, ``engine`` and ``db`` are all omitted, the store is
                in-memory.
            engine: an existing SQLAlchemy engine (takes precedence over db_url).
            table_name: directory table name (default ``authz_users``).
            create_table: create the table if missing (default True).
            audit: optional :class:`~agno.os.authz.audit.AuditSink`. When set,
                every directory change emits an append-only AuditEvent with the
                acting principal and the before/after (same trail as role changes).
            db: an agno database (the same object you pass to ``AgentOS(db=...)``).
                Its SQLAlchemy engine is reused, so the directory lives in the same
                database as your agent data. Takes precedence over ``db_url``.
        """
        self._audit = audit
        self._mem: Optional[Dict[str, dict]] = None
        from agno.os.authz._db import resolve_authz_db

        self._db: Any = resolve_authz_db(db, db_url)
        if self._db is None:
            # In-memory directory (not persisted). Fine for tests/dev, and AgentOS
            # upgrades it in place via attach_db() when it has a usable db -- see the
            # guard there for why a live one must not stay in-memory.
            self._mem = {}

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
        for ``ManagedRoleStore``. Any rows written while the store was in-memory are
        migrated across, so adoption never silently drops a disabled user.
        """
        from agno.os.authz._db import supports_authz

        if self._db is not None or db is None or not supports_authz(db):
            return
        pending = list((self._mem or {}).values())
        self._db = db
        self._mem = None
        # Carry rows written before adoption across verbatim -- including ``disabled``,
        # which upsert() deliberately refuses to set, so a revoked user stays revoked.
        for row in pending:
            self._write(row, insert=True)

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

        Only fields you pass are changed; omitted fields are left as-is on an
        existing user (so a metadata-light update can't blank out an email).
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
            row["metadata"] = metadata
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
        (``UserDirectoryConfig(auto_provision=True)``), the next valid token
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
    ) -> dict:
        """Just-in-time: create a directory row for ``subject`` from token claims if
        it doesn't exist yet. No-op if the user is already present. Returns the user."""
        existing = self.get(subject)
        if existing is not None:
            return existing
        return self.upsert(
            subject,
            email=claims.get(email_claim),
            name=claims.get(name_claim),
            actor=actor or "system:jit",
        )

    # ------------------------------------------------------------------ reads
    def get(self, id: str) -> Optional[dict]:
        if self._mem is not None:
            row = self._mem.get(id)
            return dict(row) if row else None

        return self._db.get_authz_user(id)

    def _filtered_mem_rows(self, include_disabled: bool, search: Optional[str]) -> List[dict]:
        """The in-memory equivalent of the SQL filters, for the unbound dev/test store."""
        rows = list((self._mem or {}).values())
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
    ) -> List[dict]:
        """A page of users, optionally excluding disabled ones.

        ``offset``/``limit`` page in the store so callers don't materialise the
        whole directory; pair with :meth:`count` for the total. ``search``
        filters case-insensitively by substring across id, email, and name;
        ``sort_by`` is any of :data:`USER_SORT_FIELDS` (newest first by default)."""
        if sort_by not in USER_SORT_FIELDS:
            raise ValueError(f"sort_by must be one of {USER_SORT_FIELDS}, got {sort_by!r}")
        descending = order != "asc"
        if self._mem is not None:
            # Rows missing the field (email/name are optional) go last in either
            # direction, matching the nullslast() on the SQL path.
            rows = self._filtered_mem_rows(include_disabled, search)
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
        )

    def count(self, include_disabled: bool = True, search: Optional[str] = None) -> int:
        """Total number of users (for pagination), with the same filters as
        :meth:`list`."""
        if self._mem is not None:
            return len(self._filtered_mem_rows(include_disabled, search))

        return int(self._db.count_authz_users(include_disabled=include_disabled, search=search))

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
            },
        )
