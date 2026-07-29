"""Shared SQLAlchemy implementation of the authorization tables.

The sync SQLAlchemy backends (``PostgresDb``, ``SqliteDb``) expose authorization storage
as ``BaseDb`` methods (``*_authz_*``); both delegate to the functions here so the query
logic lives in one place instead of being duplicated per backend. Each function takes the
backend's ``Engine`` and the already-resolved ``Table`` (the backend fetches it via
``_get_table(..., create_table_if_not_found=True)`` so tables are created by the normal
schema-aware path on first use).

Two properties this layer must preserve, because the authorization model depends on them:

* **Fresh reads.** Nothing here caches. A revocation on one replica has to be enforced by
  every other replica on its next request, so each decision reads the tables. (The
  request-scoped memo in ``agno.os.authz`` sits above this and dies with the request.)
* **Atomic role replacement.** ``replace_subject_roles`` is one transaction. Done as
  read-then-delete-then-insert it leaves a window with no role at all, and lets two
  concurrent assigns each clear only what they saw and leave the subject holding both.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


def _upsert(conn: Any, table: Any, values: Dict[str, Any], conflict_cols: List[str], update_cols: List[str]) -> None:
    """One INSERT ... ON CONFLICT, rather than DELETE-then-INSERT.

    Delete-then-insert is not an upsert under concurrency: two writers can both delete,
    then both insert, and the second gets a primary-key violation. Postgres surfaces that
    as an IntegrityError and a 500 -- measured at 89/150 concurrent assigns before this --
    while SQLite mostly hides it behind its global write lock, which is why it looks fine
    in development and fails in production.

    Both supported backends speak ON CONFLICT; anything else falls back to the old pattern
    so a future backend still works, just without the atomicity.
    """
    dialect = conn.dialect.name
    stmt: Any
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(table).values(**values)
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(table).values(**values)
    else:  # pragma: no cover - neither shipped backend
        conn.execute(delete(table).where(*[table.c[c] == values[c] for c in conflict_cols]))
        conn.execute(insert(table).values(**values))
        return

    if update_cols:
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_cols, set_={c: values[c] for c in update_cols if c in values}
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
    conn.execute(stmt)


# ==================== Policy: what a role may do ====================


def get_policies(engine: Engine, table: Any, roles: List[str]) -> List[Tuple[str, str, str, str]]:
    """All (role, resource, action, effect) rows whose role is in ``roles``."""
    if not roles:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            select(table.c.role, table.c.resource, table.c.action, table.c.effect).where(table.c.role.in_(roles))
        )
        return [(r[0], r[1], r[2], r[3]) for r in rows]


def get_role_policies(engine: Engine, table: Any, role: str) -> List[Tuple[str, str, str]]:
    """One role's (resource, action, effect) rows."""
    with engine.connect() as conn:
        rows = conn.execute(select(table.c.resource, table.c.action, table.c.effect).where(table.c.role == role))
        return [(r[0], r[1], r[2]) for r in rows]


def set_role_policies(engine: Engine, table: Any, role: str, rows: List[Tuple[str, str, str]]) -> None:
    """Replace a role's policy rows in one transaction, so a reader never sees a role
    that has been emptied but not yet refilled."""
    with engine.begin() as conn:
        conn.execute(delete(table).where(table.c.role == role))
        for resource, action, effect in rows:
            _upsert(
                conn,
                table,
                {"role": role, "resource": resource, "action": action, "effect": effect},
                ["role", "resource", "action"],
                ["effect"],
            )


def upsert_policy(engine: Engine, table: Any, *, role: str, resource: str, action: str, effect: str) -> None:
    """Add a grant, or flip the effect of the existing one for this (role, resource, action)."""
    with engine.begin() as conn:
        _upsert(
            conn,
            table,
            {"role": role, "resource": resource, "action": action, "effect": effect},
            ["role", "resource", "action"],
            ["effect"],
        )


def delete_policy(
    engine: Engine, table: Any, *, role: str, resource: Optional[str] = None, action: Optional[str] = None
) -> None:
    """Delete a role's policy rows, optionally narrowed to one resource and action."""
    clause = [table.c.role == role]
    if resource is not None:
        clause.append(table.c.resource == resource)
    if action is not None:
        clause.append(table.c.action == action)
    with engine.begin() as conn:
        conn.execute(delete(table).where(*clause))


# ==================== Grouping: who holds which role ====================


def get_direct_roles(engine: Engine, table: Any, subject: str) -> List[str]:
    """Roles directly assigned to ``subject`` (indexed point-lookup on the PK)."""
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(select(table.c.role).where(table.c.subject == subject))]


def name_is_role(engine: Engine, policy_table: Any, grouping_table: Any, name: str) -> bool:
    """True if ``name`` is used as a ROLE: it carries policy, or something is assigned to it.

    One round trip -- two EXISTS OR'd rather than a statement each -- because this runs on
    every subject decision and answers False on every happy path. The grouping half needs
    the index on ``role``: the composite PK covers (subject, role) and so cannot serve a
    lookup by role alone.
    """
    carries_policy = select(policy_table.c.role).where(policy_table.c.role == name).exists()
    has_members = select(grouping_table.c.subject).where(grouping_table.c.role == name).exists()
    with engine.connect() as conn:
        return bool(conn.execute(select(or_(carries_policy, has_members))).scalar())


def assign_role(engine: Engine, table: Any, subject: str, role: str) -> None:
    """Add an assignment. Idempotent: a repeat is not an error."""
    with engine.begin() as conn:
        _upsert(conn, table, {"subject": subject, "role": role}, ["subject", "role"], [])


def unassign_role(engine: Engine, table: Any, subject: str, role: str) -> None:
    """Remove an assignment. Idempotent."""
    with engine.begin() as conn:
        conn.execute(delete(table).where(table.c.subject == subject, table.c.role == role))


def replace_subject_roles(engine: Engine, table: Any, subject: str, role: str) -> None:
    """Atomically make ``role`` the subject's only role -- see the module docstring."""
    with engine.begin() as conn:
        conn.execute(delete(table).where(table.c.subject == subject))
        conn.execute(insert(table).values(subject=subject, role=role))


def list_roles(engine: Engine, policy_table: Any, grouping_table: Any) -> List[str]:
    """Every role name known to policy or to assignments, so an assignment-only role is
    still inspectable and removable."""
    with engine.connect() as conn:
        roles = {r[0] for r in conn.execute(select(policy_table.c.role).distinct())}
        roles |= {r[0] for r in conn.execute(select(grouping_table.c.role).distinct())}
    return sorted(roles)


def delete_role(engine: Engine, policy_table: Any, grouping_table: Any, meta_table: Any, role: str) -> None:
    """Drop a role entirely -- policy, assignments, metadata -- in one transaction, so a
    decision can never see a half-deleted role."""
    with engine.begin() as conn:
        conn.execute(delete(policy_table).where(policy_table.c.role == role))
        conn.execute(delete(grouping_table).where(grouping_table.c.role == role))
        conn.execute(delete(meta_table).where(meta_table.c.slug == role))


# ==================== Role metadata ====================


def get_role_meta(engine: Engine, table: Any, slug: str) -> Optional[Dict[str, Any]]:
    with engine.connect() as conn:
        row = conn.execute(select(table).where(table.c.slug == slug)).mappings().first()
    return dict(row) if row is not None else None


def list_role_meta(engine: Engine, table: Any) -> List[Dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(table)).mappings()]


def upsert_role_meta(engine: Engine, table: Any, slug: str, values: Dict[str, Any]) -> None:
    with engine.begin() as conn:
        _upsert(conn, table, {"slug": slug, **values}, ["slug"], list(values))


def delete_role_meta(engine: Engine, table: Any, slug: str) -> None:
    with engine.begin() as conn:
        conn.execute(delete(table).where(table.c.slug == slug))


# ==================== User directory ====================


def get_user(engine: Engine, table: Any, user_id: str) -> Optional[Dict[str, Any]]:
    with engine.connect() as conn:
        row = conn.execute(select(table).where(table.c.id == user_id)).mappings().first()
    return _user_row(row) if row is not None else None


def list_users(engine: Engine, table: Any, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
    stmt = select(table).order_by(table.c.updated_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    with engine.connect() as conn:
        return [_user_row(r) for r in conn.execute(stmt).mappings()]


def count_users(engine: Engine, table: Any) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar() or 0)


def upsert_user(engine: Engine, table: Any, user_id: str, values: Dict[str, Any]) -> None:
    """Write a directory row verbatim -- including ``disabled``, so a revoked user stays
    revoked when a store adopts a database mid-flight."""
    payload = dict(values)
    metadata = payload.pop("metadata", None)
    if metadata is not None:
        payload["user_metadata"] = json.dumps(metadata)
    with engine.begin() as conn:
        _upsert(conn, table, {"id": user_id, **payload}, ["id"], list(payload))


def delete_user(engine: Engine, table: Any, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(delete(table).where(table.c.id == user_id))


def is_user_disabled(engine: Engine, table: Any, user_id: str) -> bool:
    """The kill switch. An unknown subject is NOT disabled -- absence from the directory
    is not a revocation, and auto-provisioning depends on that distinction."""
    with engine.connect() as conn:
        row = conn.execute(select(table.c.disabled).where(table.c.id == user_id)).first()
    return bool(row[0]) if row is not None else False


def _user_row(row: Any) -> Dict[str, Any]:
    """Directory row in the shape the store hands out (metadata parsed back from text)."""
    out = dict(row)
    raw = out.pop("user_metadata", None)
    out["metadata"] = json.loads(raw) if raw else None
    return out


# ==================== Audit: change trail and access trail ====================


def record_event(engine: Engine, table: Any, values: Dict[str, Any]) -> None:
    """Append an audit row. An audit sink must never break the request it is recording,
    so a duplicate id is swallowed rather than raised."""
    try:
        with engine.begin() as conn:
            conn.execute(insert(table).values(**values))
    except IntegrityError:
        pass


def read_events(
    engine: Engine,
    table: Any,
    limit: int = 100,
    offset: int = 0,
    search: Optional[str] = None,
    sort_by: str = "timestamp",
    order: str = "desc",
    search_columns: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    stmt = select(table)
    if search:
        needle = f"%{search}%"
        columns = [table.c[name] for name in (search_columns or []) if name in table.c]
        if columns:
            stmt = stmt.where(or_(*[c.like(needle) for c in columns]))
    column = table.c[sort_by] if sort_by in table.c else table.c.timestamp
    stmt = stmt.order_by(column.desc() if order.lower() == "desc" else column.asc()).limit(limit).offset(offset)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(stmt).mappings()]


def count_events(
    engine: Engine, table: Any, search: Optional[str] = None, search_columns: Optional[List[str]] = None
) -> int:
    stmt = select(func.count()).select_from(table)
    if search:
        needle = f"%{search}%"
        columns = [table.c[name] for name in (search_columns or []) if name in table.c]
        if columns:
            stmt = stmt.where(or_(*[c.like(needle) for c in columns]))
    with engine.connect() as conn:
        return int(conn.execute(stmt).scalar() or 0)
