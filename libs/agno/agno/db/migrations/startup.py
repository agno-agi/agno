"""Bring a database to the newest schema version as AgentOS starts.

Only the newest migration is applied here. An older migration can copy or rewrite a large amount of
data, so a database that is behind an older version is left as it is for the operator to migrate.

The check that decides this is one read of the schema versions table. A database that is already
current, or that holds no table yet, is not touched and nothing is logged.

One process migrates at a time. The others wait, then find nothing left to do.
"""

import asyncio
import inspect
import os
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from packaging import version as packaging_version

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.manager import TABLE_TYPE_TO_ATTR, MigrationManager
from agno.db.utils import legacy_company_table

try:
    from sqlalchemy import select, text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

# The database types the newest migration changes tables on.
_SQL_DB_TYPES = ("PostgresDb", "SqliteDb", "AsyncPostgresDb", "AsyncSqliteDb")
_POSTGRES_DB_TYPES = ("PostgresDb", "AsyncPostgresDb")

# The name of the lock that one migrating process holds for a database.
_LOCK_NAME = "agno_startup_migration"
# How long a process waits for another one that is migrating.
LOCK_WAIT_SECONDS = 600.0
_LOCK_POLL_SECONDS = 0.2

MIGRATE_ADVICE = (
    "Apply the pending migrations with `asyncio.run(MigrationManager(db).up())` (import it from "
    "`agno.db.migrations.manager`; await the call directly in async code), or via the AgentOS endpoint "
    "`POST /databases/all/migrate`."
)


@dataclass(frozen=True)
class StartupMigration:
    """What the start did for one database.

    ``status`` is "current" when nothing was pending, "migrated" when the newest migration was
    applied, "skipped" when it is pending and was left for the operator, and "failed" when it was
    started and did not finish. ``reason`` says why for the last two.
    """

    status: str
    reason: Optional[str] = None

    @property
    def pending(self) -> bool:
        return self.status in ("skipped", "failed")


def _is_db_type(db: Any, names: Tuple[str, ...]) -> bool:
    """Whether db is one of the named adapters or a subclass, without importing their drivers."""
    return any(cls.__name__ in names for cls in type(db).__mro__)


async def _call(function: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a sync or an async adapter method."""
    result = function(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


async def _stamps(db: Union[BaseDb, AsyncBaseDb]) -> Dict[str, str]:
    """Every table's stamped version, read once. Empty when the database has no versions table."""
    table = await _call(db._get_table, table_type="versions", create_table_if_not_found=False)  # type: ignore[union-attr]
    if table is None:
        return {}
    statement = select(table.c.table_name, table.c.version)
    if isinstance(db, AsyncBaseDb):
        async with db.async_session_factory() as sess:  # type: ignore[attr-defined]
            rows = (await sess.execute(statement)).all()
    else:
        with db.Session() as sess:  # type: ignore[attr-defined]
            rows = sess.execute(statement).all()
    return {row[0]: row[1] for row in rows if row[1]}


async def _pending(db: Union[BaseDb, AsyncBaseDb]) -> Tuple[bool, List[str]]:
    """Whether the newest migration is pending, and the tables that are behind an older one."""
    manager = MigrationManager(db)
    latest, previous = manager.latest_schema_version, manager.available_versions[-2][1]
    stamps = await _stamps(db)
    names = [getattr(db, attr) for attr in TABLE_TYPE_TO_ATTR.values()]
    pending, behind, unstamped = False, [], []
    # Until the newest migration renames it, the goals table is stamped under its 3.2.0 name.
    for name in [*names, legacy_company_table(db, "goals")]:
        if name is None:
            continue
        if name not in stamps:
            unstamped.append(name)
            continue
        stamped = packaging_version.parse(stamps[name])
        if stamped < previous:
            behind.append(f"{name} is at version {stamped}")
        elif stamped < latest:
            pending = True
    if pending:
        # A table from before versions were stamped is behind too. Looked for only now, so a
        # database with nothing to migrate costs the one read above.
        for name in unstamped:
            if name in names and await _call(db.table_exists, name):  # type: ignore[union-attr]
                behind.append(f"{name} has no version")
    return pending, behind


def _sqlite_lock_path(db: Any) -> Optional[str]:
    """The file that holds the migration lock of a SQLite database. None for one kept in memory."""
    path = db.db_engine.url.database
    if not path or path == ":memory:" or path.startswith("file:"):
        return None
    return f"{path}.migration-lock"


async def _wait_for(acquire: Any) -> bool:
    """Call ``acquire`` until it returns True or the wait is over."""
    waited = 0.0
    while True:
        if await _call(acquire):
            return True
        if waited >= LOCK_WAIT_SECONDS:
            return False
        await asyncio.sleep(_LOCK_POLL_SECONDS)
        waited += _LOCK_POLL_SECONDS


@asynccontextmanager
async def _postgres_lock(db: Any) -> AsyncIterator[bool]:
    """A session advisory lock on one connection. PostgreSQL releases it when the connection ends."""
    acquire, release = "SELECT pg_try_advisory_lock(hashtext(:name))", "SELECT pg_advisory_unlock(hashtext(:name))"
    params = {"name": _LOCK_NAME}
    conn = await _call(db.db_engine.connect)
    held = False
    try:

        async def attempt() -> bool:
            return bool((await _call(conn.execute, text(acquire), params)).scalar())

        held = await _wait_for(attempt)
        yield held
    finally:
        try:
            if held:
                await _call(conn.execute, text(release), params)
            await _call(conn.commit)
        except Exception:
            # The lock goes with the connection, so the connection is not returned to the pool.
            await _call(conn.invalidate)
        finally:
            await _call(conn.close)


@asynccontextmanager
async def _sqlite_lock(db: Any) -> AsyncIterator[bool]:
    """An exclusive transaction on a lock file beside the database. SQLite releases it when the process ends.

    The database file itself cannot hold the lock: the migration writes to it on other connections.
    """
    path = _sqlite_lock_path(db)
    if path is None:
        yield True
        return
    held: List[sqlite3.Connection] = []

    def attempt() -> bool:
        # A new connection each time. The process that migrated removes the file, and a connection
        # opened before that can no longer lock it.
        conn = sqlite3.connect(path, timeout=0, isolation_level=None, check_same_thread=False)
        try:
            conn.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError:
            conn.close()
            return False
        held.append(conn)
        return True

    try:
        yield await _wait_for(attempt)
    finally:
        for conn in held:
            conn.execute("ROLLBACK")
            conn.close()


async def _migrate_locked(db: Union[BaseDb, AsyncBaseDb]) -> StartupMigration:
    """Migrate while this process holds the lock."""
    # Another process may have migrated while this one waited.
    pending, behind = await _pending(db)
    if not pending:
        return StartupMigration("current")
    if behind:
        latest = MigrationManager(db).latest_schema_version
        return StartupMigration(
            "skipped", f"{', '.join(behind)}, and only the {latest} migration is applied automatically"
        )
    try:
        await MigrationManager(db).up()
    except Exception as exc:
        return StartupMigration("failed", f"{type(exc).__name__}: {exc}")
    return StartupMigration("migrated")


async def _migrate(db: Union[BaseDb, AsyncBaseDb]) -> StartupMigration:
    pending, _ = await _pending(db)
    if not pending:
        return StartupMigration("current")
    postgres = _is_db_type(db, _POSTGRES_DB_TYPES)
    async with _postgres_lock(db) if postgres else _sqlite_lock(db) as held:
        if not held:
            return StartupMigration("skipped", f"another process held the migration lock for {LOCK_WAIT_SECONDS:.0f}s")
        result = await _migrate_locked(db)
    lock_path = None if postgres else _sqlite_lock_path(db)
    if lock_path is not None and not result.pending:
        # Nothing is left to migrate, so the lock file has no more use. A process that still waits
        # on it takes the lock next and finds the same.
        try:
            os.unlink(lock_path)
        except OSError:
            pass
    return result


async def migrate_at_startup(db: Union[BaseDb, AsyncBaseDb]) -> StartupMigration:
    """Apply the newest migration to ``db`` when it is the only one pending. Never raises.

    Runs on SQLite and PostgreSQL, with the sync and the async adapter. Any other database is
    reported as current: the newest migration changes no table there.
    """
    if not _is_db_type(db, _SQL_DB_TYPES):
        return StartupMigration("current")
    try:
        return await _migrate(db)
    except Exception as exc:
        return StartupMigration("failed", f"{type(exc).__name__}: {exc}")
