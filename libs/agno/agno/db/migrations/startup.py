"""Bring a database to the newest schema version as AgentOS starts.

Only the newest migration is applied here. An older migration can copy or rewrite a large amount of
data, so a database that is behind an older version is left as it is for the operator to migrate.

The check that decides this is one read of the schema versions table. A database that is already
current, or that holds no table yet, is not touched and nothing is logged.

One process migrates at a time. The others wait, then find nothing left to do. The migrate endpoints
take the same lock.
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
from agno.utils.log import log_warning

try:
    from sqlalchemy import select, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

# The database types the newest migration changes tables on.
_SQL_DB_TYPES = ("PostgresDb", "SqliteDb", "AsyncPostgresDb", "AsyncSqliteDb")
_POSTGRES_DB_TYPES = ("PostgresDb", "AsyncPostgresDb")

# The name of the lock that one migrating process holds for a database.
_LOCK_NAME = "agno_startup_migration"
# How long a process waits for another one that is migrating.
LOCK_WAIT_SECONDS = 600.0
# How long a migrate request waits. Short enough to answer before a proxy gives up on it.
REQUEST_LOCK_WAIT_SECONDS = 20.0
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
    # Until the newest migration renames them, the goals and details tables are stamped under their
    # 3.2.0 names. An agno 3.2 process that starts after the migration stamps them again.
    legacy = [name for name in (legacy_company_table(db, kind) for kind in ("goals", "company")) if name in stamps]
    if legacy and not await manager._company_rename_pending():
        legacy = []
    for name in [*names, *legacy]:
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
        # A migration that stopped after the goals table was renamed leaves it under its new name
        # with the stamp still under the old one. That table is pending, not behind.
        stopped = getattr(db, "goals_table_name", None) if legacy_company_table(db, "goals") in stamps else None
        for name in unstamped:
            if name in names and name != stopped and await _call(db.table_exists, name):  # type: ignore[union-attr]
                behind.append(f"{name} has no version")
    return pending, behind


async def _sqlite_lock_path(db: Any) -> Optional[str]:
    """The file that holds the migration lock of a SQLite database. None for one kept in memory.

    SQLite is asked for the file it has open, so a path, a ``file:`` URI and a relative path to one
    database all share the lock.
    """
    conn = await _call(db.db_engine.connect)
    try:
        rows = (await _call(conn.execute, text("PRAGMA database_list"))).all()
    finally:
        await _call(conn.close)
    path = next((row[2] for row in rows if row[1] == "main"), None)
    return f"{os.path.realpath(path)}.migration-lock" if path else None


def _lock_engine(db: Any) -> Any:
    """An engine that connects as the database's own does, outside its pool.

    The lock is held while the migration runs, and the pool may have no second connection to give.
    """
    if isinstance(db, AsyncBaseDb):
        engine = db.db_engine.sync_engine  # type: ignore[attr-defined]
        return AsyncEngine(Engine(engine.pool.recreate(), engine.dialect, engine.url))
    engine = db.db_engine
    return Engine(engine.pool.recreate(), engine.dialect, engine.url)


async def _wait_for(acquire: Any, seconds: float) -> bool:
    """Call ``acquire`` until it returns True or ``seconds`` have passed."""
    waited = 0.0
    while True:
        if await _call(acquire):
            return True
        if waited >= seconds:
            return False
        await asyncio.sleep(_LOCK_POLL_SECONDS)
        waited += _LOCK_POLL_SECONDS


@asynccontextmanager
async def _postgres_lock(db: Any, seconds: float) -> AsyncIterator[bool]:
    """A session advisory lock on one connection. PostgreSQL releases it when the connection ends."""
    acquire, release = "SELECT pg_try_advisory_lock(hashtext(:name))", "SELECT pg_advisory_unlock(hashtext(:name))"
    params = {"name": _LOCK_NAME}
    engine = _lock_engine(db)
    try:
        conn = await _call(engine.connect)
    except BaseException:
        await _call(engine.dispose)
        raise
    held = False
    try:

        async def attempt() -> bool:
            return bool((await _call(conn.execute, text(acquire), params)).scalar())

        held = await _wait_for(attempt, seconds)
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
            await _call(engine.dispose)


def _file_id(path: str) -> Optional[Tuple[int, int]]:
    try:
        found = os.stat(path)
    except OSError:
        return None
    return found.st_dev, found.st_ino


@asynccontextmanager
async def _sqlite_lock(path: Optional[str], seconds: float) -> AsyncIterator[bool]:
    """An exclusive transaction on a lock file beside the database. SQLite releases it when the process ends.

    The database file itself cannot hold the lock: the migration writes to it on other connections.
    """
    if path is None:
        yield True
        return
    held: List[sqlite3.Connection] = []

    def attempt() -> bool:
        # A new connection each time: the process that held the lock removed the file it was opened on.
        os.close(os.open(path, os.O_CREAT | os.O_RDONLY, 0o644))
        before = _file_id(path)
        conn = sqlite3.connect(path, timeout=0, isolation_level=None, check_same_thread=False)
        try:
            conn.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError:
            conn.close()
            return False
        if before is None or _file_id(path) != before:
            # The lock is on a file that was removed meanwhile, which no other process looks at.
            conn.close()
            return False
        held.append(conn)
        return True

    try:
        yield await _wait_for(attempt, seconds)
    finally:
        for conn in held:
            # Removed while it is still locked, so no other process holds it at that moment.
            try:
                os.unlink(path)
            except OSError:
                pass
            conn.execute("ROLLBACK")
            conn.close()


@asynccontextmanager
async def migration_lock(db: Any, seconds: float) -> AsyncIterator[bool]:
    """Let one process migrate ``db`` at a time, at the start and through the migrate endpoints.

    Yields whether the lock was taken within ``seconds``. A database other than SQLite and
    PostgreSQL has no lock and yields True.
    """
    if not _is_db_type(db, _SQL_DB_TYPES):
        yield True
    elif _is_db_type(db, _POSTGRES_DB_TYPES):
        async with _postgres_lock(db, seconds) as held:
            yield held
    else:
        async with _sqlite_lock(await _sqlite_lock_path(db), seconds) as held:
            yield held


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


async def _warn_of_unused_tables(db: Union[BaseDb, AsyncBaseDb]) -> None:
    """Say which tables an agno 3.2 process created again after the migration."""
    stamps = await _stamps(db)
    stored = [name for name in (legacy_company_table(db, kind) for kind in ("goals", "company")) if name in stamps]
    unused = [name for name in stored if await _call(db.table_exists, name)]  # type: ignore[union-attr]
    if unused:
        log_warning(
            f"{', '.join(unused)}: created by an agno 3.2 process after {db.__class__.__name__} (id: {db.id}) was "
            "migrated, and not used. Stop every process that still runs agno 3.2. Copy any row you need, then drop "
            "what is left."
        )


async def _migrate(db: Union[BaseDb, AsyncBaseDb]) -> StartupMigration:
    pending, _ = await _pending(db)
    if not pending:
        await _warn_of_unused_tables(db)
        return StartupMigration("current")
    async with migration_lock(db, LOCK_WAIT_SECONDS) as held:
        if not held:
            return StartupMigration("skipped", f"another process held the migration lock for {LOCK_WAIT_SECONDS:.0f}s")
        return await _migrate_locked(db)


async def migrate_at_startup(db: Union[BaseDb, AsyncBaseDb]) -> StartupMigration:
    """Apply the newest migration to ``db`` when it is the only one pending. Never raises.

    Runs on SQLite and PostgreSQL, with the sync and the async adapter. Any other database is
    reported as current and left for the operator to migrate.
    """
    if not _is_db_type(db, _SQL_DB_TYPES):
        return StartupMigration("current")
    try:
        return await _migrate(db)
    except Exception as exc:
        return StartupMigration("failed", f"{type(exc).__name__}: {exc}")
