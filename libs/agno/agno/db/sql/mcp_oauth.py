"""Shared SQLAlchemy implementation of the built-in MCP OAuth token store.

The sync SQLAlchemy backends (``PostgresDb``, ``SqliteDb``) expose the OAuth store as
``BaseDb`` methods (``*_mcp_oauth_*``); both delegate to the functions here so the store
logic -- expiry sweeps, the anti-flood caps, the atomic single-use consume, and the
IntegrityError-tolerant key insert -- lives in one place instead of being duplicated per
backend. Each function takes the backend's ``Engine`` and the already-resolved
``Table`` (the backend fetches it via ``_get_table(..., create_table_if_not_found=True)``
so the table is created by the normal schema-aware path on first use).

Secrets never reach this layer in the clear: the provider SHA-256-hashes authorization
codes and refresh tokens before calling ``store_code`` / ``store_refresh`` and looks them
up by the same hash, and it JSON-serializes payloads/scopes to text. This module only
stores and queries opaque strings.
"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

# ==================== Clients (DCR) ====================


def get_client(engine: Engine, table: Any, client_id: str) -> Optional[str]:
    """The stored client_metadata JSON for ``client_id``, or None."""
    with engine.connect() as conn:
        row = conn.execute(select(table.c.client_metadata).where(table.c.client_id == client_id)).first()
    return row[0] if row is not None else None


def create_client(
    engine: Engine,
    table: Any,
    *,
    client_id: str,
    client_metadata: str,
    now: int,
    unconsumed_ttl: int,
    max_clients: int,
) -> bool:
    """Register a public client. Returns False (nothing inserted) when the anti-flood cap
    on unconsumed registrations is reached, True after a successful insert.

    Expires unconsummated registrations (the flood vector) first; consumed rows are kept
    -- a consumed client holds a live, rotating refresh token, so deleting its row would
    401 an actively-used connector. The cap bounds only unconsumed rows, so a run of
    deployer-approved (consumed) connections can never wedge ``/register``.
    """
    with engine.connect() as conn:
        conn.execute(
            delete(table).where(
                table.c.consumed_at.is_(None),
                table.c.created_at < now - unconsumed_ttl,
            )
        )
        count = conn.execute(select(func.count()).select_from(table).where(table.c.consumed_at.is_(None))).scalar() or 0
        if count >= max_clients:
            conn.commit()
            return False
        conn.execute(
            insert(table).values(
                client_id=client_id,
                client_metadata=client_metadata,
                created_at=now,
                consumed_at=None,
            )
        )
        conn.commit()
    return True


def mark_client_consumed(engine: Engine, table: Any, client_id: str, now: int) -> None:
    """Stamp ``consumed_at`` so the client is exempt from the unconsumed-registration cap."""
    with engine.connect() as conn:
        conn.execute(
            update(table).where(table.c.client_id == client_id, table.c.consumed_at.is_(None)).values(consumed_at=now)
        )
        conn.commit()


# ==================== Transactions (pending authorizations) ====================


def store_transaction(
    engine: Engine,
    table: Any,
    *,
    txn_id: str,
    client_id: str,
    params: str,
    expires_at: int,
    now: int,
    max_pending: int,
) -> None:
    """Insert a pending authorization, sweeping expired rows and evicting the oldest to
    keep the table bounded (``/authorize`` is reachable unauthenticated after one DCR)."""
    with engine.connect() as conn:
        conn.execute(delete(table).where(table.c.expires_at < now))
        count = conn.execute(select(func.count()).select_from(table)).scalar() or 0
        overflow = count - (max_pending - 1)
        if overflow > 0:
            # Wrap the oldest-N select in a derived table so the delete is not a bare
            # self-referential subquery -- MySQL rejects that (error 1093) while the
            # derived-table form is portable across sqlite / Postgres / MySQL.
            oldest = select(table.c.txn_id).order_by(table.c.expires_at.asc()).limit(overflow).subquery()
            conn.execute(delete(table).where(table.c.txn_id.in_(select(oldest.c.txn_id))))
        conn.execute(insert(table).values(txn_id=txn_id, client_id=client_id, params=params, expires_at=expires_at))
        conn.commit()


def get_transaction(engine: Engine, table: Any, txn_id: str) -> Optional[Tuple[str, int]]:
    """The ``(params, expires_at)`` for ``txn_id`` (no expiry filter; the caller checks)."""
    with engine.connect() as conn:
        row = conn.execute(select(table.c.params, table.c.expires_at).where(table.c.txn_id == txn_id)).first()
    return (row[0], row[1]) if row is not None else None


def consume_transaction(engine: Engine, table: Any, txn_id: str, now: int) -> Optional[Tuple[str, int]]:
    """Atomically claim the transaction: the DELETE succeeds on exactly one replica.

    Returns ``(params, expires_at)`` for a live transaction, or None when it is missing,
    already claimed, or expired (an expired row is left for the sweep, not deleted here).
    """
    with engine.connect() as conn:
        row = conn.execute(select(table.c.params, table.c.expires_at).where(table.c.txn_id == txn_id)).first()
        if row is None or row[1] < now:
            conn.commit()
            return None
        result = conn.execute(delete(table).where(table.c.txn_id == txn_id))
        conn.commit()
    if result.rowcount != 1:
        return None
    return (row[0], row[1])


# ==================== Authorization codes ====================


def store_code(engine: Engine, table: Any, *, code_hash: str, payload: str, expires_at: int, now: int) -> None:
    """Insert a hashed authorization code, sweeping expired rows first."""
    with engine.connect() as conn:
        conn.execute(delete(table).where(table.c.expires_at < now))
        conn.execute(insert(table).values(code_hash=code_hash, payload=payload, expires_at=expires_at))
        conn.commit()


def get_code(engine: Engine, table: Any, code_hash: str) -> Optional[Tuple[str, int]]:
    """The ``(payload, expires_at)`` for a hashed code (no expiry filter; the caller checks)."""
    with engine.connect() as conn:
        row = conn.execute(select(table.c.payload, table.c.expires_at).where(table.c.code_hash == code_hash)).first()
    return (row[0], row[1]) if row is not None else None


def delete_code(engine: Engine, table: Any, code_hash: str) -> bool:
    """Delete a hashed code atomically. Returns True iff exactly one row was removed --
    the single-use guarantee: a replayed code deletes on only one replica."""
    with engine.connect() as conn:
        result = conn.execute(delete(table).where(table.c.code_hash == code_hash))
        conn.commit()
    return result.rowcount == 1


# ==================== Refresh tokens ====================


def store_refresh(
    engine: Engine,
    table: Any,
    *,
    token_hash: str,
    client_id: str,
    scopes: str,
    expires_at: int,
    now: int,
    family_id: str,
) -> None:
    """Insert a hashed refresh token (tagged with its rotation family), sweeping expired rows first."""
    with engine.connect() as conn:
        conn.execute(delete(table).where(table.c.expires_at < now))
        conn.execute(
            insert(table).values(
                token_hash=token_hash,
                client_id=client_id,
                scopes=scopes,
                expires_at=expires_at,
                family_id=family_id,
            )
        )
        conn.commit()


def get_refresh(engine: Engine, table: Any, token_hash: str) -> Optional[Tuple[str, str, int]]:
    """The ``(client_id, scopes, expires_at)`` for a hashed refresh token (caller checks expiry)."""
    with engine.connect() as conn:
        row = conn.execute(
            select(table.c.client_id, table.c.scopes, table.c.expires_at).where(table.c.token_hash == token_hash)
        ).first()
    return (row[0], row[1], row[2]) if row is not None else None


def delete_refresh(engine: Engine, table: Any, token_hash: str) -> bool:
    """Delete a hashed refresh token atomically. Returns True iff exactly one row was
    removed -- rotation-on-use: a replayed refresh token deletes on only one replica."""
    with engine.connect() as conn:
        result = conn.execute(delete(table).where(table.c.token_hash == token_hash))
        conn.commit()
    return result.rowcount == 1


def delete_refresh_family(engine: Engine, table: Any, family_id: str) -> int:
    """Delete every refresh token in a rotation family. Returns the number removed --
    the reuse-detection revocation lever: one reused token invalidates the whole chain."""
    with engine.connect() as conn:
        result = conn.execute(delete(table).where(table.c.family_id == family_id))
        conn.commit()
    return int(result.rowcount or 0)


# ==================== Signing keys ====================


def get_keys(engine: Engine, table: Any) -> List[Tuple[str, str]]:
    """All ``(kid, secret)`` signing keys, newest first."""
    with engine.connect() as conn:
        rows = conn.execute(select(table.c.kid, table.c.secret).order_by(table.c.created_at.desc())).all()
    return [(r[0], r[1]) for r in rows]


def insert_key(engine: Engine, table: Any, *, kid: str, secret: str, created_at: int) -> bool:
    """Insert a signing key. Returns False on a uniqueness conflict (another replica won
    the cold-start race), True on success -- the caller re-reads the keys either way."""
    with engine.connect() as conn:
        try:
            conn.execute(insert(table).values(kid=kid, secret=secret, created_at=created_at))
            conn.commit()
            return True
        except IntegrityError:
            conn.rollback()
            return False
