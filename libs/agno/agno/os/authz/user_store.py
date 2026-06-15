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
        self._engine: Any = None  # SQLAlchemy Engine when db-backed, else None
        self._table: Any = None  # SQLAlchemy Table for authz_users

        if db is not None and engine is None:
            from agno.os.authz._db import engine_from_db

            engine = engine_from_db(db)

        if engine is not None or db_url is not None:
            import sqlalchemy as sa

            self._engine = engine if engine is not None else sa.create_engine(db_url)  # type: ignore[arg-type]
            metadata = sa.MetaData()
            self._table = sa.Table(
                table_name,
                metadata,
                sa.Column("id", sa.String(255), primary_key=True),  # the JWT sub
                sa.Column("email", sa.String(320)),
                sa.Column("name", sa.String(255)),
                sa.Column("disabled", sa.Boolean, nullable=False, default=False),
                sa.Column("created_at", sa.Integer, nullable=False),
                sa.Column("updated_at", sa.Integer, nullable=False),
                sa.Column("user_metadata", sa.Text),
            )
            if create_table:
                metadata.create_all(self._engine)
        else:
            # In-memory directory (not persisted). Fine for tests/dev.
            self._mem = {}

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
            self._write(row, insert=True)
            self._emit("user.disabled" if disabled else "user.enabled", id, None, [self._summary(row)], actor)
            return row

        if bool(existing["disabled"]) == bool(disabled):
            return existing  # no-op, no event

        row = dict(existing)
        row["disabled"] = bool(disabled)
        row["updated_at"] = _now()
        self._write(row, insert=False)
        self._emit(
            "user.disabled" if disabled else "user.enabled", id, [self._summary(existing)], [self._summary(row)], actor
        )
        return row

    def remove(self, id: str, actor: Optional[str] = None) -> bool:
        """Delete a user from the directory. Does NOT remove role assignments —
        those live in the role store; remove them there if needed.

        NOTE: delete is NOT a revocation primitive. With JIT auto-provisioning on
        (``AuthorizationConfig(auto_provision_users=True)``), the next valid token
        from this subject re-creates the row as *active*, and any surviving role
        assignments come back with it. To revoke access, use :meth:`set_disabled`
        (a durable tombstone enforced at every request), not :meth:`remove`."""
        existing = self.get(id)
        if existing is None:
            return False
        if self._mem is not None:
            self._mem.pop(id, None)
        else:
            import sqlalchemy as sa

            with self._engine.begin() as conn:  # type: ignore[union-attr]
                conn.execute(sa.delete(self._table).where(self._table.c.id == id))  # type: ignore[union-attr]
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

        import sqlalchemy as sa

        with self._engine.connect() as conn:  # type: ignore[union-attr]
            r = conn.execute(sa.select(self._table).where(self._table.c.id == id)).mappings().first()  # type: ignore[union-attr]
        return self._row_to_dict(r) if r else None

    # list() and count() apply the same filters (include_disabled + search) over
    # whichever backend is active; these two helpers are that shared filtering.
    def _filtered_mem_rows(self, include_disabled: bool, search: Optional[str]) -> List[dict]:
        def matches(row: dict, needle: str) -> bool:
            return any(needle in (row.get(f) or "").casefold() for f in USER_SEARCH_FIELDS)

        rows = list(self._mem.values())  # type: ignore[union-attr]
        if not include_disabled:
            rows = [r for r in rows if not r["disabled"]]
        if search:
            needle = search.casefold()
            rows = [r for r in rows if matches(r, needle)]
        return rows

    def _sql_filters(self, include_disabled: bool, search: Optional[str]) -> list:
        import sqlalchemy as sa

        clauses = []
        if not include_disabled:
            clauses.append(self._table.c.disabled.is_(False))  # type: ignore[union-attr]
        if search:
            pattern = f"%{search}%"
            clauses.append(sa.or_(*(self._table.c[f].ilike(pattern) for f in USER_SEARCH_FIELDS)))  # type: ignore[index]
        return clauses

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

        import sqlalchemy as sa

        sort_col = self._table.c[sort_by]  # type: ignore[index]
        stmt = (
            sa.select(self._table)
            .where(*self._sql_filters(include_disabled, search))
            # nullslast: backends disagree on NULL placement (and email/name are
            # nullable); pin them last in either direction.
            .order_by(sa.nullslast(sort_col.desc() if descending else sort_col.asc()))
            .limit(limit)
            .offset(offset)
        )
        with self._engine.connect() as conn:
            db_rows = conn.execute(stmt).mappings().all()
        return [self._row_to_dict(r) for r in db_rows]

    def count(self, include_disabled: bool = True, search: Optional[str] = None) -> int:
        """Total number of users (for pagination), with the same filters as
        :meth:`list`."""
        if self._mem is not None:
            return len(self._filtered_mem_rows(include_disabled, search))

        import sqlalchemy as sa

        stmt = sa.select(sa.func.count()).select_from(self._table).where(*self._sql_filters(include_disabled, search))  # type: ignore[arg-type]
        with self._engine.connect() as conn:  # type: ignore[union-attr]
            return int(conn.execute(stmt).scalar() or 0)

    def is_disabled(self, id: Optional[str]) -> bool:
        """Fast path for the enforcement point: True only if the user exists AND is
        disabled. Unknown subjects are NOT disabled (the app may legitimately mint
        tokens for users not yet in the directory)."""
        if not id:
            return False
        if self._mem is not None:
            row = self._mem.get(id)
            return bool(row and row["disabled"])

        import sqlalchemy as sa

        with self._engine.connect() as conn:  # type: ignore[union-attr]
            r = conn.execute(
                sa.select(self._table.c.disabled).where(self._table.c.id == id)  # type: ignore[union-attr]
            ).first()
        return bool(r and r[0])

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

    def _write(self, row: dict, insert: bool) -> None:
        if self._mem is not None:
            self._mem[row["id"]] = dict(row)
            return

        import sqlalchemy as sa

        values = {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "disabled": bool(row["disabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "user_metadata": json.dumps(row["metadata"]) if row.get("metadata") else None,
        }
        with self._engine.begin() as conn:  # type: ignore[union-attr]
            if insert:
                conn.execute(sa.insert(self._table).values(**values))  # type: ignore[union-attr]
            else:
                conn.execute(
                    sa.update(self._table).where(self._table.c.id == row["id"]).values(**values)  # type: ignore[union-attr]
                )
