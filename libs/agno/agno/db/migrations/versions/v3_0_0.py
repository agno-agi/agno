"""Migration v3.0.0: Normalize session runs into a runs table, isolate eval runs by user

Sessions changes:
- Create the runs table (one row per run, with the run payload as JSON)
- Copy every run stored in the sessions table `runs` column into the runs table

This removes the unbounded growth of session rows: each run is now stored once,
in its own row, instead of the whole run list being rewritten on every save.

The legacy `runs` column on `agno_sessions` is intentionally NOT dropped by this
migration — it stays in place as a backup. New writes will null it as sessions
are touched. When you have verified the migration and taken a backup, drop the
column manually by calling ``db.cleanup_legacy_runs_column()``.

Per-user isolation changes:
- Add the user_id column and its index to every table in ``USER_ID_TABLE_TYPES``

The column backs per-user isolation: get / list / rename / delete scope by
user_id when the caller is scoped, and stay global when it is None. Existing
rows keep a NULL user_id, so they stay visible to admins and to unscoped
deployments while a scoped caller sees none of them. Document backends store
these records as documents and pick the field up without a schema change.

To isolate another table, declare user_id on that table in the adapter schemas
that have it, register the table type in ``MigrationManager`` and add it to
``USER_ID_TABLE_TYPES`` — the per-backend functions read the column type from
the schema, so they need no change. A backend whose schema does not declare the
column is skipped, so a table type that only some adapters support is safe to
list here.
"""

import json
import time
from typing import Any, Dict, List, Optional

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.db.utils import CustomJSONEncoder
from agno.utils.log import log_error, log_info, log_warning

try:
    from sqlalchemy import text
    from sqlalchemy.dialects import mysql, postgresql, sqlite
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

BATCH_SIZE = 50


# Table types that get a user_id column and index, so AgentOS can scope them per user.
# Extend this tuple to isolate another table; the per-backend functions need no change,
# and backends whose schema does not declare the column skip it.
USER_ID_TABLE_TYPES = ("evals", "components")


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Apply the following changes to the database:
    - Move session runs out of the sessions `runs` column into the runs table
    - Add a user_id column and index to the tables listed in USER_ID_TABLE_TYPES

    Notice only the changes related to the given table_type are applied.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if db_type == "PostgresDb":
            return _migrate_postgres(db, table_type, table_name)
        elif db_type == "SqliteDb":
            return _migrate_sqlite(db, table_type, table_name)
        elif db_type in ("MySQLDb", "SingleStoreDb"):
            return _migrate_mysql_like(db, table_type, table_name)
        elif db_type == "MongoDb":
            return _migrate_mongo(db, table_type, table_name)
        elif db_type == "FirestoreDb":
            return _migrate_firestore(db, table_type, table_name)
        elif db_type == "RedisDb":
            return _migrate_redis(db, table_type, table_name)
        elif db_type == "ValkeyDb":
            return _migrate_valkey(db, table_type, table_name)
        elif db_type == "JsonDb":
            return _migrate_jsondb(db, table_type, table_name)
        elif db_type == "GcsJsonDb":
            return _migrate_gcsjsondb(db, table_type, table_name)
        elif db_type == "InMemoryDb":
            return _migrate_inmemorydb(db, table_type, table_name)
        elif db_type == "DynamoDb":
            return _migrate_dynamodb(db, table_type, table_name)
        elif db_type == "SurrealDb":
            return _migrate_surrealdb(db, table_type, table_name)
        else:
            log_info(f"Migration v3.0.0 is not implemented for {db_type}. Table '{table_name}' is left unchanged.")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Apply the following changes to the database:
    - Move session runs out of the sessions `runs` column into the runs table
    - Add a user_id column and index to the tables listed in USER_ID_TABLE_TYPES

    Notice only the changes related to the given table_type are applied.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if db_type == "AsyncPostgresDb":
            return await _migrate_async_postgres(db, table_type, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _migrate_async_sqlite(db, table_type, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _migrate_async_mysql(db, table_type, table_name)
        elif db_type == "AsyncMongoDb":
            return await _migrate_async_mongo(db, table_type, table_name)
        else:
            log_info(f"Migration v3.0.0 is not implemented for {db_type}. Table '{table_name}' is left unchanged.")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert the following changes to the database:
    - Move runs back into the sessions `runs` column and drop the runs table
    - Drop the user_id column and index from the tables listed in USER_ID_TABLE_TYPES

    Notice only the changes related to the given table_type are reverted.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if db_type == "PostgresDb":
            return _revert_postgres(db, table_type, table_name)
        elif db_type == "SqliteDb":
            return _revert_sqlite(db, table_type, table_name)
        elif db_type in ("MySQLDb", "SingleStoreDb"):
            return _revert_mysql_like(db, table_type, table_name)
        elif db_type == "MongoDb":
            return _revert_mongo(db, table_type, table_name)
        elif db_type == "FirestoreDb":
            return _revert_firestore(db, table_type, table_name)
        elif db_type == "RedisDb":
            return _revert_redis(db, table_type, table_name)
        elif db_type == "ValkeyDb":
            return _revert_valkey(db, table_type, table_name)
        elif db_type == "JsonDb":
            return _revert_jsondb(db, table_type, table_name)
        elif db_type == "GcsJsonDb":
            return _revert_gcsjsondb(db, table_type, table_name)
        elif db_type == "InMemoryDb":
            return _revert_inmemorydb(db, table_type, table_name)
        elif db_type == "DynamoDb":
            return _revert_dynamodb(db, table_type, table_name)
        elif db_type == "SurrealDb":
            return _revert_surrealdb(db, table_type, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert the following changes to the database:
    - Move runs back into the sessions `runs` column and drop the runs table
    - Drop the user_id column and index from the tables listed in USER_ID_TABLE_TYPES

    Notice only the changes related to the given table_type are reverted.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if db_type == "AsyncPostgresDb":
            return await _revert_async_postgres(db, table_type, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _revert_async_sqlite(db, table_type, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _revert_async_mysql(db, table_type, table_name)
        elif db_type == "AsyncMongoDb":
            return await _revert_async_mongo(db, table_type, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


# ---------------------------------------------------------------------------
# Per-backend dispatch
#
# One entry per SQL backend, routing a table type to the work v3.0.0 does on it.
# The document backends carry user_id without a schema change, so they only
# implement the sessions half and return False for everything else.
# ---------------------------------------------------------------------------


def _migrate_postgres(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on PostgreSQL."""
    if table_type == "sessions":
        return _migrate_postgres_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _migrate_postgres_user_id(db, table_type, table_name)
    return False


async def _migrate_async_postgres(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on async PostgreSQL."""
    if table_type == "sessions":
        return await _migrate_async_postgres_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _migrate_async_postgres_user_id(db, table_type, table_name)
    return False


def _migrate_sqlite(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on SQLite."""
    if table_type == "sessions":
        return _migrate_sqlite_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _migrate_sqlite_user_id(db, table_type, table_name)
    return False


async def _migrate_async_sqlite(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on async SQLite."""
    if table_type == "sessions":
        return await _migrate_async_sqlite_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _migrate_async_sqlite_user_id(db, table_type, table_name)
    return False


def _migrate_mysql_like(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on MySQL or SingleStore."""
    if table_type == "sessions":
        return _migrate_mysql_like_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _migrate_mysql_like_user_id(db, table_type, table_name)
    return False


async def _migrate_async_mysql(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Apply the v3.0.0 changes for the given table type on async MySQL."""
    if table_type == "sessions":
        return await _migrate_async_mysql_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _migrate_async_mysql_user_id(db, table_type, table_name)
    return False


def _revert_postgres(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on PostgreSQL."""
    if table_type == "sessions":
        return _revert_postgres_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _revert_postgres_user_id(db, table_type, table_name)
    return False


async def _revert_async_postgres(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on async PostgreSQL."""
    if table_type == "sessions":
        return await _revert_async_postgres_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _revert_async_postgres_user_id(db, table_type, table_name)
    return False


def _revert_sqlite(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on SQLite."""
    if table_type == "sessions":
        return _revert_sqlite_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _revert_sqlite_user_id(db, table_type, table_name)
    return False


async def _revert_async_sqlite(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on async SQLite."""
    if table_type == "sessions":
        return await _revert_async_sqlite_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _revert_async_sqlite_user_id(db, table_type, table_name)
    return False


def _revert_mysql_like(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on MySQL or SingleStore."""
    if table_type == "sessions":
        return _revert_mysql_like_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return _revert_mysql_like_user_id(db, table_type, table_name)
    return False


async def _revert_async_mysql(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Revert the v3.0.0 changes for the given table type on async MySQL."""
    if table_type == "sessions":
        return await _revert_async_mysql_sessions(db, table_name)
    if table_type in USER_ID_TABLE_TYPES:
        return await _revert_async_mysql_user_id(db, table_type, table_name)
    return False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _build_run_rows(
    runs: Optional[List[Dict[str, Any]]],
    session_id: str,
    user_id: Optional[str],
    run_data_as_string: bool,
) -> List[Dict[str, Any]]:
    """Build runs-table rows from the runs found in a sessions table `runs` column."""
    if isinstance(runs, str):
        runs = json.loads(runs)
    if not runs:
        return []

    current_time = int(time.time())
    rows = []
    for run_index, run in enumerate(runs):
        if not isinstance(run, dict) or run.get("run_id") is None:
            continue

        if run.get("agent_id"):
            run_type = "agent"
        elif run.get("team_id"):
            run_type = "team"
        else:
            run_type = "workflow"

        rows.append(
            {
                "run_id": run.get("run_id"),
                "session_id": session_id,
                "run_type": run_type,
                "agent_id": run.get("agent_id"),
                "team_id": run.get("team_id"),
                "workflow_id": run.get("workflow_id"),
                "user_id": user_id,
                "parent_run_id": run.get("parent_run_id"),
                "status": run.get("status"),
                "run_index": run_index,
                "run_data": json.dumps(run, cls=CustomJSONEncoder) if run_data_as_string else run,
                "created_at": run.get("created_at") or current_time,
                "updated_at": current_time,
            }
        )
    return rows


def _forget_runs_table(db) -> None:
    """Drop the runs table from the adapter's SQLAlchemy state after a revert.

    ``DROP TABLE`` only removes the table from the database — the Table object
    stays registered on ``db.metadata``, so a later up() in the same process
    raises "Table is already defined for this MetaData instance" when it tries
    to define it again.
    """
    metadata = getattr(db, "metadata", None)
    runs_table_name = getattr(db, "runs_table_name", None)
    if metadata is not None and runs_table_name is not None:
        for table in list(metadata.tables.values()):
            if table.name == runs_table_name:
                metadata.remove(table)
    if hasattr(db, "runs_table"):
        db.runs_table = None


def _decode_run_data(value: Any) -> Any:
    """Decode a run_data payload read back through a raw SQL SELECT.

    A raw select skips the column's JSON deserializer, so SQLite — which stores
    the payload as a JSON string inside a JSON column — hands back both layers.
    """
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, str):
        value = json.loads(value)
    return value


def _column_exists(sess, db_schema: str, table_name: str, column_name: str, db_type: str) -> bool:
    """Check if a column exists in a table."""
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        query = text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        )
    else:
        # MySQL / SingleStore
        query = text(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = :column"
        )
    result = sess.execute(query, {"schema": db_schema, "table": table_name, "column": column_name})
    return result.scalar() is not None


async def _async_column_exists(sess, db_schema: str, table_name: str, column_name: str, db_type: str) -> bool:
    """Async version: check if a column exists in a table."""
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        query = text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        )
    else:
        # MySQL / SingleStore
        query = text(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = :column"
        )
    result = await sess.execute(query, {"schema": db_schema, "table": table_name, "column": column_name})
    return result.scalar() is not None


def _index_exists(sess, db_schema: str, table_name: str, index_name: str, db_type: str) -> bool:
    """Check if an index exists on a table."""
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        query = text(
            "SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND tablename = :table AND indexname = :index"
        )
    else:
        # MySQL / SingleStore
        query = text(
            "SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND INDEX_NAME = :index"
        )
    result = sess.execute(query, {"schema": db_schema, "table": table_name, "index": index_name})
    return result.scalar() is not None


async def _async_index_exists(sess, db_schema: str, table_name: str, index_name: str, db_type: str) -> bool:
    """Async version: check if an index exists on a table."""
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        query = text(
            "SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND tablename = :table AND indexname = :index"
        )
    else:
        # MySQL / SingleStore
        query = text(
            "SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND INDEX_NAME = :index"
        )
    result = await sess.execute(query, {"schema": db_schema, "table": table_name, "index": index_name})
    return result.scalar() is not None


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _migrate_postgres_sessions(db: BaseDb, table_name: str) -> bool:
    """Move session runs into the runs table and drop the `runs` column, for PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

    # Ensure the runs table exists
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        if not _column_exists(sess, db_schema, table_name, "runs", db_type):
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Move all runs into the runs table
        result = sess.execute(text(f"SELECT session_id, user_id, runs FROM {full_table} WHERE runs IS NOT NULL"))
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = postgresql.insert(runs_table).on_conflict_do_nothing(index_elements=["run_id"])
                sess.execute(insert_stmt, rows)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


async def _migrate_async_postgres_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Move session runs into the runs table and drop the `runs` column, for async PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

    # Ensure the runs table exists
    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_schema = :schema AND table_name = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        column_exists = await _async_column_exists(sess, db_schema, table_name, "runs", db_type)
        if not column_exists:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Move all runs into the runs table
        result = await sess.execute(text(f"SELECT session_id, user_id, runs FROM {full_table} WHERE runs IS NOT NULL"))
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = postgresql.insert(runs_table).on_conflict_do_nothing(index_elements=["run_id"])
                await sess.execute(insert_stmt, rows)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def _migrate_sqlite_sessions(db: BaseDb, table_name: str) -> bool:
    """Move session runs into the runs table and drop the `runs` column, for SQLite."""
    # Ensure the runs table exists
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        columns_info = sess.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        existing_columns = {col[1] for col in columns_info}
        if "runs" not in existing_columns:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Move all runs into the runs table
        result = sess.execute(text(f"SELECT session_id, user_id, runs FROM {table_name} WHERE runs IS NOT NULL"))
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=True))

            if rows:
                insert_stmt = sqlite.insert(runs_table).on_conflict_do_nothing(index_elements=["run_id"])
                sess.execute(insert_stmt, rows)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


async def _migrate_async_sqlite_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Move session runs into the runs table and drop the `runs` column, for async SQLite."""
    # Ensure the runs table exists
    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        table_exists = (
            await sess.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
                {"table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        columns_info = (await sess.execute(text(f"PRAGMA table_info({table_name})"))).fetchall()
        existing_columns = {col[1] for col in columns_info}
        if "runs" not in existing_columns:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Move all runs into the runs table
        result = await sess.execute(text(f"SELECT session_id, user_id, runs FROM {table_name} WHERE runs IS NOT NULL"))
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=True))

            if rows:
                insert_stmt = sqlite.insert(runs_table).on_conflict_do_nothing(index_elements=["run_id"])
                await sess.execute(insert_stmt, rows)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


# ---------------------------------------------------------------------------
# Revert functions
# ---------------------------------------------------------------------------


def _revert_postgres_sessions(db: BaseDb, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table, for PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    runs_table_name = db.runs_table_name
    quoted_runs_table = f"{quoted_schema}.{quote_db_identifier(db_type, runs_table_name)}"

    with db.Session() as sess, sess.begin():  # type: ignore
        runs_table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": runs_table_name},
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        if not _column_exists(sess, db_schema, table_name, "runs", db_type):
            log_info(f"-- Adding runs column back to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN runs JSONB"))

        # Rebuild the runs blobs from the runs table
        result = sess.execute(
            text(
                f"SELECT session_id, json_agg(run_data ORDER BY run_index, created_at) "
                f"FROM {quoted_runs_table} GROUP BY session_id"
            )
        )
        for session_id, runs in result.fetchall():
            sess.execute(
                text(f"UPDATE {full_table} SET runs = CAST(:runs AS JSONB) WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        sess.execute(text(f"DROP TABLE {quoted_runs_table}"))
        _forget_runs_table(db)

        return True


async def _revert_async_postgres_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table, for async PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    runs_table_name = db.runs_table_name
    quoted_runs_table = f"{quoted_schema}.{quote_db_identifier(db_type, runs_table_name)}"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        runs_table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_schema = :schema AND table_name = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": runs_table_name},
            )
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        column_exists = await _async_column_exists(sess, db_schema, table_name, "runs", db_type)
        if not column_exists:
            log_info(f"-- Adding runs column back to {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN runs JSONB"))

        # Rebuild the runs blobs from the runs table
        result = await sess.execute(
            text(
                f"SELECT session_id, json_agg(run_data ORDER BY run_index, created_at) "
                f"FROM {quoted_runs_table} GROUP BY session_id"
            )
        )
        for session_id, runs in result.fetchall():
            await sess.execute(
                text(f"UPDATE {full_table} SET runs = CAST(:runs AS JSONB) WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        await sess.execute(text(f"DROP TABLE {quoted_runs_table}"))
        _forget_runs_table(db)

        return True


def _revert_sqlite_sessions(db: BaseDb, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table, for SQLite."""
    runs_table_name = db.runs_table_name

    with db.Session() as sess, sess.begin():  # type: ignore
        runs_table_exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": runs_table_name},
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        columns_info = sess.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        existing_columns = {col[1] for col in columns_info}
        if "runs" not in existing_columns:
            log_info(f"-- Adding runs column back to {table_name}")
            sess.execute(text(f"ALTER TABLE {table_name} ADD COLUMN runs JSON"))

        # Rebuild the runs blobs from the runs table
        result = sess.execute(text(f"SELECT DISTINCT session_id FROM {runs_table_name} ORDER BY session_id")).fetchall()
        for (session_id,) in result:
            run_rows = sess.execute(
                text(
                    f"SELECT run_data FROM {runs_table_name} "
                    f"WHERE session_id = :session_id ORDER BY run_index, created_at"
                ),
                {"session_id": session_id},
            ).fetchall()
            runs = [_decode_run_data(row[0]) for row in run_rows]
            sess.execute(
                text(f"UPDATE {table_name} SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        sess.execute(text(f"DROP TABLE {runs_table_name}"))
        _forget_runs_table(db)

        return True


async def _revert_async_sqlite_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table, for async SQLite."""
    runs_table_name = db.runs_table_name

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        runs_table_exists = (
            await sess.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
                {"table_name": runs_table_name},
            )
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        columns_info = (await sess.execute(text(f"PRAGMA table_info({table_name})"))).fetchall()
        existing_columns = {col[1] for col in columns_info}
        if "runs" not in existing_columns:
            log_info(f"-- Adding runs column back to {table_name}")
            await sess.execute(text(f"ALTER TABLE {table_name} ADD COLUMN runs JSON"))

        # Rebuild the runs blobs from the runs table
        result = (
            await sess.execute(text(f"SELECT DISTINCT session_id FROM {runs_table_name} ORDER BY session_id"))
        ).fetchall()
        for (session_id,) in result:
            run_rows = (
                await sess.execute(
                    text(
                        f"SELECT run_data FROM {runs_table_name} "
                        f"WHERE session_id = :session_id ORDER BY run_index, created_at"
                    ),
                    {"session_id": session_id},
                )
            ).fetchall()
            runs = [_decode_run_data(row[0]) for row in run_rows]
            await sess.execute(
                text(f"UPDATE {table_name} SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        await sess.execute(text(f"DROP TABLE {runs_table_name}"))
        _forget_runs_table(db)

        return True


# ---------------------------------------------------------------------------
# MySQL / SingleStore (sync). SingleStore is MySQL-protocol-compatible so it
# uses the same code path. AsyncMySQLDb has its own coroutine variants below.
# ---------------------------------------------------------------------------


def _migrate_mysql_like_sessions(db: BaseDb, table_name: str) -> bool:
    """Move session runs into the runs table for MySQL or SingleStore.

    Non-destructive: the legacy `runs` column is left in place. Call
    ``db.cleanup_legacy_runs_column()`` to drop it once you have verified
    the migration and taken a backup.
    """
    # Ensure the runs table exists
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or sess.execute(text("SELECT DATABASE()")).scalar()  # type: ignore

        # Does the sessions table exist?
        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        # Does the legacy `runs` column exist?
        column_exists = (
            sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            ).scalar()
            is not None
        )
        if not column_exists:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        # Copy every legacy run into the runs table
        result = sess.execute(
            text(f"SELECT session_id, user_id, runs FROM `{db_schema}`.`{table_name}` WHERE runs IS NOT NULL")
        )
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                # MySQL JSON columns come back as either dict/list (asyncmy)
                # or str (pymysql), depending on driver — _build_run_rows handles both.
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = mysql.insert(runs_table).values(rows)
                # ON DUPLICATE KEY UPDATE that effectively does nothing: keeps idempotency
                # without raising on previously-migrated runs.
                insert_stmt = insert_stmt.on_duplicate_key_update(run_id=insert_stmt.inserted.run_id)
                sess.execute(insert_stmt)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


async def _migrate_async_mysql_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Async MySQL variant of :func:`_migrate_mysql_like_sessions`."""
    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or (await sess.execute(text("SELECT DATABASE()"))).scalar()  # type: ignore

        table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                    "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        column_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).scalar() is not None
        if not column_exists:
            log_info(f"Table {table_name} has no runs column, skipping migration")
            return False

        result = await sess.execute(
            text(f"SELECT session_id, user_id, runs FROM `{db_schema}`.`{table_name}` WHERE runs IS NOT NULL")
        )
        migrated_runs = 0
        while True:
            batch = result.fetchmany(BATCH_SIZE)
            if not batch:
                break

            rows: List[Dict[str, Any]] = []
            for session_id, user_id, runs in batch:
                rows.extend(_build_run_rows(runs, session_id, user_id, run_data_as_string=False))

            if rows:
                insert_stmt = mysql.insert(runs_table).values(rows)
                insert_stmt = insert_stmt.on_duplicate_key_update(run_id=insert_stmt.inserted.run_id)
                await sess.execute(insert_stmt)
                migrated_runs += len(rows)

        log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs table")
        log_info(
            f"-- The legacy '{table_name}.runs' column was preserved as a backup. "
            "Once you have verified the migration, drop it via db.cleanup_legacy_runs_column()."
        )

        return True


def _revert_mysql_like_sessions(db: BaseDb, table_name: str) -> bool:
    """Revert: rebuild blobs in `sessions.runs` from the runs table; drop the runs table."""
    runs_table_name = db.runs_table_name  # type: ignore

    with db.Session() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or sess.execute(text("SELECT DATABASE()")).scalar()  # type: ignore

        runs_table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": runs_table_name},
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        # Re-add the runs column if missing
        column_exists = (
            sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            ).scalar()
            is not None
        )
        if not column_exists:
            log_info(f"-- Adding runs column back to {table_name}")
            sess.execute(text(f"ALTER TABLE `{db_schema}`.`{table_name}` ADD COLUMN `runs` JSON"))

        # Rebuild blobs
        session_ids = sess.execute(
            text(f"SELECT DISTINCT session_id FROM `{db_schema}`.`{runs_table_name}` ORDER BY session_id")
        ).fetchall()
        for (session_id,) in session_ids:
            run_rows = sess.execute(
                text(
                    f"SELECT run_data FROM `{db_schema}`.`{runs_table_name}` "
                    f"WHERE session_id = :session_id ORDER BY run_index, created_at"
                ),
                {"session_id": session_id},
            ).fetchall()
            runs = [_decode_run_data(row[0]) for row in run_rows]
            sess.execute(
                text(f"UPDATE `{db_schema}`.`{table_name}` SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        sess.execute(text(f"DROP TABLE `{db_schema}`.`{runs_table_name}`"))
        _forget_runs_table(db)

        return True


async def _revert_async_mysql_sessions(db: AsyncBaseDb, table_name: str) -> bool:
    """Async MySQL variant of :func:`_revert_mysql_like_sessions`."""
    runs_table_name = db.runs_table_name  # type: ignore

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or (await sess.execute(text("SELECT DATABASE()"))).scalar()  # type: ignore

        runs_table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                    "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": runs_table_name},
            )
        ).scalar()
        if not runs_table_exists:
            log_info(f"Runs table {runs_table_name} does not exist, skipping revert")
            return False

        column_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).scalar() is not None
        if not column_exists:
            log_info(f"-- Adding runs column back to {table_name}")
            await sess.execute(text(f"ALTER TABLE `{db_schema}`.`{table_name}` ADD COLUMN `runs` JSON"))

        result = await sess.execute(
            text(f"SELECT DISTINCT session_id FROM `{db_schema}`.`{runs_table_name}` ORDER BY session_id")
        )
        session_ids = result.fetchall()
        for (session_id,) in session_ids:
            run_rows = (
                await sess.execute(
                    text(
                        f"SELECT run_data FROM `{db_schema}`.`{runs_table_name}` "
                        f"WHERE session_id = :session_id ORDER BY run_index, created_at"
                    ),
                    {"session_id": session_id},
                )
            ).fetchall()
            runs = [_decode_run_data(row[0]) for row in run_rows]
            await sess.execute(
                text(f"UPDATE `{db_schema}`.`{table_name}` SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        log_info(f"-- Dropping runs table {runs_table_name}")
        await sess.execute(text(f"DROP TABLE `{db_schema}`.`{runs_table_name}`"))
        _forget_runs_table(db)

        return True


# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------


def _migrate_mongo(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session documents into the runs collection.

    Non-destructive: the legacy `runs` field is left in place. Call
    ``db.cleanup_legacy_runs_field()`` to remove it once you have verified
    the migration and taken a backup.
    """
    if table_type != "sessions":
        return False

    sessions_collection = db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    if sessions_collection is None:
        log_info(f"Sessions collection {table_name} does not exist, skipping migration")
        return False

    # Ensure the runs collection exists (creates indexes too)
    runs_collection = db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore
    if runs_collection is None:
        log_info("Runs collection unavailable, skipping migration")
        return False

    migrated_runs = 0
    cursor = sessions_collection.find(
        {"runs": {"$exists": True, "$ne": None, "$not": {"$size": 0}}},
        {"session_id": 1, "user_id": 1, "runs": 1},
    ).batch_size(BATCH_SIZE)

    for doc in cursor:
        rows = _build_run_rows(doc.get("runs"), doc.get("session_id"), doc.get("user_id"), run_data_as_string=False)
        for row in rows:
            runs_collection.replace_one({"run_id": row["run_id"]}, row, upsert=True)
            migrated_runs += 1

    log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs collection")
    log_info(
        f"-- The legacy '{table_name}.runs' field was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )

    return True


def _revert_mongo(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session documents from the runs collection.

    The runs collection is dropped at the end.
    """
    if table_type != "sessions":
        return False

    sessions_collection = db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    runs_collection_name = db.runs_table_name  # type: ignore
    runs_collection = db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore

    if sessions_collection is None or runs_collection is None:
        log_info("Sessions or runs collection unavailable, skipping revert")
        return False

    # Group runs by session_id, ordered
    pipeline = [
        {"$sort": {"session_id": 1, "run_index": 1, "created_at": 1}},
        {"$group": {"_id": "$session_id", "runs": {"$push": "$run_data"}}},
    ]
    for group in runs_collection.aggregate(pipeline):
        session_id = group["_id"]
        runs = group["runs"]
        sessions_collection.update_one(
            {"session_id": session_id},
            {"$set": {"runs": runs}},
        )

    log_info(f"-- Dropping runs collection {runs_collection_name}")
    runs_collection.drop()

    return True


async def _migrate_async_mongo(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async variant of :func:`_migrate_mongo`."""
    if table_type != "sessions":
        return False

    sessions_collection = await db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    if sessions_collection is None:
        log_info(f"Sessions collection {table_name} does not exist, skipping migration")
        return False

    runs_collection = await db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore
    if runs_collection is None:
        log_info("Runs collection unavailable, skipping migration")
        return False

    migrated_runs = 0
    cursor = sessions_collection.find(
        {"runs": {"$exists": True, "$ne": None, "$not": {"$size": 0}}},
        {"session_id": 1, "user_id": 1, "runs": 1},
    ).batch_size(BATCH_SIZE)

    async for doc in cursor:
        rows = _build_run_rows(doc.get("runs"), doc.get("session_id"), doc.get("user_id"), run_data_as_string=False)
        for row in rows:
            await runs_collection.replace_one({"run_id": row["run_id"]}, row, upsert=True)
            migrated_runs += 1

    log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs collection")
    log_info(
        f"-- The legacy '{table_name}.runs' field was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


async def _revert_async_mongo(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async variant of :func:`_revert_mongo`."""
    if table_type != "sessions":
        return False

    sessions_collection = await db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    runs_collection_name = db.runs_table_name  # type: ignore
    runs_collection = await db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore

    if sessions_collection is None or runs_collection is None:
        log_info("Sessions or runs collection unavailable, skipping revert")
        return False

    pipeline = [
        {"$sort": {"session_id": 1, "run_index": 1, "created_at": 1}},
        {"$group": {"_id": "$session_id", "runs": {"$push": "$run_data"}}},
    ]
    # PyMongo's async client returns a coroutine from aggregate(), Motor returns a
    # cursor. _aggregate_to_list() is the adapter's helper that handles both.
    for group in await db._aggregate_to_list(runs_collection, pipeline):  # type: ignore
        session_id = group["_id"]
        runs = group["runs"]
        await sessions_collection.update_one(
            {"session_id": session_id},
            {"$set": {"runs": runs}},
        )

    log_info(f"-- Dropping runs collection {runs_collection_name}")
    await runs_collection.drop()
    return True


# ---------------------------------------------------------------------------
# Firestore
# ---------------------------------------------------------------------------


def _migrate_firestore(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session documents into the runs collection.

    Non-destructive: the legacy `runs` field is left in place. Call
    ``db.cleanup_legacy_runs_field()`` to remove it once verified.
    """
    if table_type != "sessions":
        return False

    sessions_ref = db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    if sessions_ref is None:
        log_info(f"Sessions collection {table_name} does not exist, skipping migration")
        return False

    runs_ref = db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore
    if runs_ref is None:
        log_info("Runs collection unavailable, skipping migration")
        return False

    migrated_runs = 0
    batch = db.db_client.batch()  # type: ignore
    pending_in_batch = 0
    BATCH_LIMIT = 400  # Firestore batches max out at 500 writes; stay below the cap

    for doc in sessions_ref.stream():
        data = doc.to_dict() or {}
        legacy_runs = data.get("runs")
        if not legacy_runs:
            continue
        session_id = data.get("session_id")
        if not session_id:
            continue
        rows = _build_run_rows(legacy_runs, session_id, data.get("user_id"), run_data_as_string=False)
        for row in rows:
            run_doc_ref = runs_ref.document(row["run_id"])
            batch.set(run_doc_ref, row)
            pending_in_batch += 1
            migrated_runs += 1
            if pending_in_batch >= BATCH_LIMIT:
                batch.commit()
                batch = db.db_client.batch()  # type: ignore
                pending_in_batch = 0

    if pending_in_batch:
        batch.commit()

    log_info(f"-- Copied {migrated_runs} runs from {table_name} into the runs collection")
    log_info(
        f"-- The legacy '{table_name}.runs' field was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_firestore(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session documents from the runs collection.

    The runs collection is deleted at the end.
    """
    if table_type != "sessions":
        return False

    from google.cloud.firestore import FieldFilter  # type: ignore[import-untyped]

    sessions_ref = db._get_collection(table_type="sessions", create_collection_if_not_found=True)  # type: ignore
    runs_ref = db._get_collection(table_type="runs", create_collection_if_not_found=True)  # type: ignore
    if sessions_ref is None or runs_ref is None:
        log_info("Sessions or runs collection unavailable, skipping revert")
        return False

    runs_by_session: Dict[str, List[Any]] = {}
    for doc in runs_ref.stream():
        d = doc.to_dict() or {}
        sid = d.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (d.get("run_index") or 0, d.get("created_at") or 0, d.get("run_data"))
        )

    # Rebuild the inline blob on each session doc
    batch = db.db_client.batch()  # type: ignore
    pending = 0
    for sid, items in runs_by_session.items():
        items.sort(key=lambda t: (t[0], t[1]))
        runs = [t[2] for t in items]
        q = sessions_ref.where(filter=FieldFilter("session_id", "==", sid))
        for sd in q.stream():
            batch.update(sd.reference, {"runs": runs})
            pending += 1
            if pending >= 400:
                batch.commit()
                batch = db.db_client.batch()  # type: ignore
                pending = 0
    if pending:
        batch.commit()

    # Wipe the runs collection
    log_info("-- Deleting all documents in the runs collection")
    batch = db.db_client.batch()  # type: ignore
    pending = 0
    for doc in runs_ref.stream():
        batch.delete(doc.reference)
        pending += 1
        if pending >= 400:
            batch.commit()
            batch = db.db_client.batch()  # type: ignore
            pending = 0
    if pending:
        batch.commit()

    return True


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


def _migrate_redis(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session records into per-run keys.

    Non-destructive: the legacy `runs` field is left in place on the session
    record. Call ``db.cleanup_legacy_runs_field()`` once you have verified the
    migration to free the storage.
    """
    if table_type != "sessions":
        return False

    sessions = db._get_all_records("sessions")  # type: ignore
    migrated_runs = 0
    for session in sessions:
        legacy_runs = session.get("runs")
        if not legacy_runs:
            continue
        rows = _build_run_rows(legacy_runs, session.get("session_id"), session.get("user_id"), run_data_as_string=False)
        if not rows:
            continue
        # Write each run key directly + populate the sorted-set index.
        index_key = db._runs_by_session_index_key(session["session_id"])  # type: ignore
        from agno.db.redis.utils import generate_redis_key, serialize_data  # type: ignore

        pipe = db.redis_client.pipeline()  # type: ignore
        for row in rows:
            key = generate_redis_key(prefix=db.db_prefix, table_type="runs", key_id=row["run_id"])  # type: ignore
            pipe.set(key, serialize_data(row), ex=db.expire)  # type: ignore
            pipe.zadd(index_key, {row["run_id"]: float(row.get("run_index") or 0)})
        pipe.execute()
        migrated_runs += len(rows)

    log_info(f"-- Copied {migrated_runs} runs into per-run Redis keys")
    log_info(
        "-- The legacy 'runs' field on each session record was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_redis(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session records, then delete run keys."""
    if table_type != "sessions":
        return False

    from agno.db.redis.utils import generate_redis_key  # type: ignore

    # Collect runs per session
    runs_keys = db._get_all_records("runs")  # type: ignore
    runs_by_session: Dict[str, List[Any]] = {}
    for r in runs_keys:
        sid = r.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    sessions = db._get_all_records("sessions")  # type: ignore
    for session in sessions:
        sid = session.get("session_id")
        items = runs_by_session.get(sid, [])
        items.sort(key=lambda t: (t[0], t[1]))
        session["runs"] = [t[2] for t in items]
        db._store_record(table_type="sessions", record_id=sid, data=session)  # type: ignore

    # Delete per-run keys + per-session indexes
    for r in runs_keys:
        rid = r.get("run_id")
        if not rid:
            continue
        try:
            db.redis_client.delete(generate_redis_key(prefix=db.db_prefix, table_type="runs", key_id=rid))  # type: ignore
        except Exception:
            pass
    for sid in list(runs_by_session.keys()):
        try:
            db.redis_client.delete(db._runs_by_session_index_key(sid))  # type: ignore
        except Exception:
            pass

    return True


# ---------------------------------------------------------------------------
# Valkey
# ---------------------------------------------------------------------------


def _migrate_valkey(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session records into per-run keys.

    Non-destructive: the legacy `runs` field is left in place on the session
    record. Call ``db.cleanup_legacy_runs_field()`` once you have verified the
    migration to free the storage.
    """
    if table_type != "sessions":
        return False

    from glide_sync import ExpirySet, ExpiryType

    from agno.db.valkey.utils import generate_valkey_key, serialize_data  # type: ignore

    sessions = db._get_all_records("sessions")  # type: ignore
    migrated_runs = 0
    for session in sessions:
        legacy_runs = session.get("runs")
        if not legacy_runs:
            continue
        rows = _build_run_rows(legacy_runs, session.get("session_id"), session.get("user_id"), run_data_as_string=False)
        if not rows:
            continue
        # Write each run key directly + populate the sorted-set index.
        index_key = db._runs_by_session_index_key(session["session_id"])  # type: ignore
        pipeline = db._create_pipeline()  # type: ignore
        expiry = ExpirySet(ExpiryType.SEC, db.expire) if db.expire is not None else None  # type: ignore
        for row in rows:
            key = generate_valkey_key(prefix=db.db_prefix, table_type="runs", key_id=row["run_id"])  # type: ignore
            pipeline.set(key, serialize_data(row), expiry=expiry)
            pipeline.zadd(index_key, {row["run_id"]: float(row.get("run_index") or 0)})
        if db.expire is not None:  # type: ignore
            pipeline.expire(index_key, db.expire)  # type: ignore
        db._exec_pipeline(pipeline)  # type: ignore
        migrated_runs += len(rows)

    log_info(f"-- Copied {migrated_runs} runs into per-run Valkey keys")
    log_info(
        "-- The legacy 'runs' field on each session record was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_valkey(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session records, then delete run keys."""
    if table_type != "sessions":
        return False

    from agno.db.valkey.utils import generate_valkey_key  # type: ignore

    # Collect runs per session
    runs_keys = db._get_all_records("runs")  # type: ignore
    runs_by_session: Dict[str, List[Any]] = {}
    for r in runs_keys:
        sid = r.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    sessions = db._get_all_records("sessions")  # type: ignore
    for session in sessions:
        sid = session.get("session_id")
        items = runs_by_session.get(sid, [])
        items.sort(key=lambda t: (t[0], t[1]))
        session["runs"] = [t[2] for t in items]
        db._store_record(table_type="sessions", record_id=sid, data=session)  # type: ignore

    # Delete per-run keys + per-session indexes
    for r in runs_keys:
        rid = r.get("run_id")
        if not rid:
            continue
        try:
            db.valkey_client.delete([generate_valkey_key(prefix=db.db_prefix, table_type="runs", key_id=rid)])  # type: ignore
        except Exception:
            pass
    for sid in list(runs_by_session.keys()):
        try:
            db.valkey_client.delete([db._runs_by_session_index_key(sid)])  # type: ignore
        except Exception:
            pass

    return True


# ---------------------------------------------------------------------------
# JsonDb / GcsJsonDb / InMemoryDb
# These adapters store sessions as a single list (file/object/in-memory dict).
# Each one exposes the same `_store_session_runs`-style helper added in v3,
# plus a way to walk the legacy `runs` field on each session record.
# ---------------------------------------------------------------------------


def _migrate_jsondb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on each session record into the runs file.

    Idempotent: reruns don't clobber fresh post-migration writes. Any run_id
    already present in the runs table wins — the legacy blob is only used
    to backfill run_ids that aren't there yet.
    """
    if table_type != "sessions":
        return False

    sessions = db._read_json_file(db.session_table_name, create_table_if_not_found=False)  # type: ignore
    if not sessions:
        log_info(f"Sessions file {table_name}.json is empty or missing, skipping migration")
        return False

    existing_runs = db._read_runs_file(create_table_if_not_found=True)  # type: ignore
    by_id = {r["run_id"]: r for r in existing_runs if "run_id" in r}

    migrated = 0
    for session in sessions:
        legacy = session.get("runs")
        if not legacy:
            continue
        rows = _build_run_rows(legacy, session.get("session_id"), session.get("user_id"), run_data_as_string=False)
        for row in rows:
            # Runs table wins on conflict: never overwrite a post-migration
            # update with the stale blob copy on a rerun.
            if row["run_id"] in by_id:
                continue
            by_id[row["run_id"]] = row
            migrated += 1

    if migrated:
        db._write_runs_file(list(by_id.values()))  # type: ignore
    log_info(f"-- Copied {migrated} runs into {db.runs_table_name}.json")  # type: ignore
    log_info(
        "-- The legacy 'runs' field on each session record was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_jsondb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on each session record from the runs file."""
    if table_type != "sessions":
        return False

    sessions = db._read_json_file(db.session_table_name, create_table_if_not_found=False)  # type: ignore
    all_runs = db._read_runs_file(create_table_if_not_found=False)  # type: ignore

    runs_by_session: Dict[str, List[Any]] = {}
    for r in all_runs:
        sid = r.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    for session in sessions:
        sid = session.get("session_id")
        items = runs_by_session.get(sid, [])
        items.sort(key=lambda t: (t[0], t[1]))
        session["runs"] = [t[2] for t in items]

    db._write_json_file(db.session_table_name, sessions)  # type: ignore
    db._write_runs_file([])  # type: ignore
    return True


def _migrate_gcsjsondb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Same shape as :func:`_migrate_jsondb` — both store sessions as a JSON list (file vs object).

    Idempotent: reruns don't clobber fresh post-migration writes. Any run_id
    already present in the runs table wins.
    """
    if table_type != "sessions":
        return False

    sessions = db._read_json_file(db.session_table_name, create_table_if_not_found=False)  # type: ignore
    if not sessions:
        log_info(f"Sessions object {table_name}.json is empty or missing, skipping migration")
        return False

    existing_runs = db._read_json_file(db.runs_table_name, create_table_if_not_found=True)  # type: ignore
    by_id = {r["run_id"]: r for r in existing_runs if "run_id" in r}

    migrated = 0
    for session in sessions:
        legacy = session.get("runs")
        if not legacy:
            continue
        rows = _build_run_rows(legacy, session.get("session_id"), session.get("user_id"), run_data_as_string=False)
        for row in rows:
            if row["run_id"] in by_id:
                continue
            by_id[row["run_id"]] = row
            migrated += 1

    if migrated:
        db._write_json_file(db.runs_table_name, list(by_id.values()))  # type: ignore
    log_info(f"-- Copied {migrated} runs into {db.runs_table_name}.json (GCS)")  # type: ignore
    log_info(
        "-- The legacy 'runs' field on each session record was preserved as a backup. "
        "Once you have verified the migration, drop it via db.cleanup_legacy_runs_field()."
    )
    return True


def _revert_gcsjsondb(db: BaseDb, table_type: str, table_name: str) -> bool:
    if table_type != "sessions":
        return False

    sessions = db._read_json_file(db.session_table_name, create_table_if_not_found=False)  # type: ignore
    all_runs = db._read_json_file(db.runs_table_name, create_table_if_not_found=False)  # type: ignore

    runs_by_session: Dict[str, List[Any]] = {}
    for r in all_runs:
        sid = r.get("session_id")
        if sid is None:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    for session in sessions:
        sid = session.get("session_id")
        items = runs_by_session.get(sid, [])
        items.sort(key=lambda t: (t[0], t[1]))
        session["runs"] = [t[2] for t in items]

    db._write_json_file(db.session_table_name, sessions)  # type: ignore
    db._write_json_file(db.runs_table_name, [])  # type: ignore
    return True


def _migrate_inmemorydb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """InMemoryDb is not normalized in v3.0; runs stay inline."""
    if table_type != "sessions":
        return False

    log_info("-- InMemoryDb does not split runs into a separate table; skipping migration.")
    return False


def _revert_inmemorydb(db: BaseDb, table_type: str, table_name: str) -> bool:
    if table_type != "sessions":
        return False

    return False


# ---------------------------------------------------------------------------
# DynamoDb
# ---------------------------------------------------------------------------


# DynamoDB error codes that indicate a transient, retryable failure.
_DYNAMO_THROTTLE_CODES = {
    "ProvisionedThroughputExceededException",
    "ThrottlingException",
    "RequestLimitExceeded",
    "InternalServerError",
}


def _dynamo_put_run_with_retry(
    client,
    table_name: str,
    item: Dict[str, Any],
    max_retries: int = 5,
    initial_backoff_seconds: float = 0.1,
) -> bool:
    """Conditionally put a run item, retrying transient throttling failures.

    The write is guarded by ``attribute_not_exists(run_id)`` so a run that was
    already copied (e.g. by a partial/lazy self-migration) is left untouched --
    keeping the migration idempotent and preserving the "store wins" invariant.

    On throttling, retries with exponential backoff. Any non-throttling error,
    or throttling that survives ``max_retries``, is propagated so a partial
    migration fails loudly instead of silently dropping runs (the legacy blob is
    lazily nulled on the next session write, so a silent skip means data loss).

    Returns:
        True if the item was written, False if it already existed.
    """
    backoff = initial_backoff_seconds
    for attempt in range(max_retries + 1):
        try:
            client.put_item(
                TableName=table_name,
                Item=item,
                ConditionExpression="attribute_not_exists(run_id)",
            )
            return True
        except client.exceptions.ConditionalCheckFailedException:
            return False
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code")
            if code in _DYNAMO_THROTTLE_CODES and attempt < max_retries:
                log_warning(
                    f"Dynamo put_item throttled ({code}) migrating run "
                    f"{item.get('run_id', {}).get('S')}; retry {attempt + 1}/{max_retries} "
                    f"after {backoff:.2f}s"
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 5.0)
                continue
            raise
    # Unreachable: the final attempt above always returns or raises.
    raise RuntimeError(f"Failed to migrate run into {table_name} after {max_retries} retries")


def _migrate_dynamodb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy legacy `runs` blob from each session item into the agno_runs table."""
    if table_type != "sessions":
        return False

    import json as _json

    client = db.client  # type: ignore
    runs_table = db.runs_table_name  # type: ignore

    # Ensure runs table exists
    db._get_table("runs", create_table_if_not_found=True)  # type: ignore

    # Scan all sessions
    items: List[Dict[str, Any]] = []
    try:
        response = client.scan(TableName=table_name)
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = client.scan(TableName=table_name, ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
    except Exception as e:
        log_error(f"Failed to scan {table_name} during v3 migration: {str(e)}")
        return False

    migrated = 0
    for item in items:
        runs_attr = item.get("runs")
        if runs_attr is None:
            continue

        legacy: Any = None
        if "S" in runs_attr:
            try:
                legacy = _json.loads(runs_attr["S"])
            except (_json.JSONDecodeError, TypeError):
                legacy = None
        elif "L" in runs_attr:
            legacy = runs_attr["L"]

        if not legacy:
            continue

        session_id = item.get("session_id", {}).get("S")
        user_id = item.get("user_id", {}).get("S")
        if not session_id:
            continue

        rows = _build_run_rows(legacy, session_id, user_id, run_data_as_string=False)
        for row in rows:
            payload = {k: v for k, v in row.items() if v is not None}
            if "run_data" in payload and isinstance(payload["run_data"], (dict, list)):
                payload["run_data"] = _json.dumps(payload["run_data"])
            dynamo_item = _serialize_to_dynamo_item_minimal(payload)
            # Propagates on non-transient failure so a partial migration aborts
            # loudly rather than silently dropping runs. Safe to re-run (the
            # conditional write skips already-migrated runs).
            if _dynamo_put_run_with_retry(client, runs_table, dynamo_item):
                migrated += 1

    log_info(
        f"-- Copied {migrated} runs into {runs_table}. The legacy 'runs' attribute on each session item "
        "was preserved as a backup. Once verified, drop it via db.cleanup_legacy_runs_field()."
    )
    return migrated > 0


def _revert_dynamodb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Walk runs and re-attach to session items, then truncate the runs table."""
    if table_type != "sessions":
        return False

    import json as _json

    client = db.client  # type: ignore
    runs_table = db.runs_table_name  # type: ignore

    items: List[Dict[str, Any]] = []
    try:
        response = client.scan(TableName=runs_table)
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = client.scan(TableName=runs_table, ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
    except Exception as e:
        log_error(f"Failed to scan runs table {runs_table}: {str(e)}")
        return False

    runs_by_session: Dict[str, List[Any]] = {}
    for it in items:
        sid = it.get("session_id", {}).get("S")
        if not sid:
            continue
        run_index = int(it.get("run_index", {}).get("N", "0"))
        created_at = int(it.get("created_at", {}).get("N", "0"))
        run_data_raw = it.get("run_data", {}).get("S")
        if not run_data_raw:
            continue
        try:
            payload = _json.loads(run_data_raw)
        except (_json.JSONDecodeError, TypeError):
            continue
        runs_by_session.setdefault(sid, []).append((run_index, created_at, payload))

    failed_sids: set = set()
    for sid, items_for_session in runs_by_session.items():
        items_for_session.sort(key=lambda t: (t[0], t[1]))
        legacy_runs = [t[2] for t in items_for_session]
        try:
            client.update_item(
                TableName=table_name,
                Key={"session_id": {"S": sid}},
                UpdateExpression="SET #runs = :runs",
                ExpressionAttributeNames={"#runs": "runs"},
                ExpressionAttributeValues={":runs": {"S": _json.dumps(legacy_runs)}},
            )
        except Exception as e:
            log_error(f"Failed to revert runs onto session {sid}: {str(e)}")
            failed_sids.add(sid)

    # Truncate the runs table, but preserve runs for any session whose blob
    # rebuild failed -- deleting them would lose the only remaining copy.
    preserved = 0
    for it in items:
        run_id = it.get("run_id", {}).get("S")
        if not run_id:
            continue
        if it.get("session_id", {}).get("S") in failed_sids:
            preserved += 1
            continue
        try:
            client.delete_item(TableName=runs_table, Key={"run_id": {"S": run_id}})
        except Exception:
            pass

    if failed_sids:
        log_warning(
            f"Preserved {preserved} run(s) in {runs_table} for {len(failed_sids)} session(s) whose "
            "blob rebuild failed; re-run down() after resolving the error."
        )

    return True


def _serialize_to_dynamo_item_minimal(data: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal DynamoDB item serializer used by the v3 migration."""
    item: Dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, bool):
            item[key] = {"BOOL": value}
        elif isinstance(value, (int, float)):
            item[key] = {"N": str(value)}
        elif isinstance(value, str):
            item[key] = {"S": value}
        elif isinstance(value, (dict, list)):
            import json as _json

            item[key] = {"S": _json.dumps(value)}
        else:
            item[key] = {"S": str(value)}
    return item


# ---------------------------------------------------------------------------
# SurrealDb
# ---------------------------------------------------------------------------


def _migrate_surrealdb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Copy legacy `runs` blob from each session record into the runs table."""
    if table_type != "sessions":
        return False

    from surrealdb import RecordID  # type: ignore

    from agno.db.surrealdb.models import serialize_run_row  # local import to avoid hard dep

    runs_table = db.runs_table_name  # type: ignore

    # Make sure the runs table exists
    db._get_table("runs", create_table_if_not_found=True)  # type: ignore

    sessions_raw = db._query(f"SELECT * FROM {table_name}", {}, dict)  # type: ignore
    migrated = 0
    for s in sessions_raw:
        legacy = s.get("runs")
        if not legacy:
            continue

        session_id = s.get("id")
        if isinstance(session_id, RecordID):
            session_id = session_id.id
        user_id = s.get("user_id")
        if not session_id:
            continue

        rows = _build_run_rows(legacy, session_id, user_id, run_data_as_string=False)
        for row in rows:
            content = serialize_run_row(row, runs_table)
            try:
                db._query_one(  # type: ignore
                    "UPSERT ONLY $record CONTENT $content",
                    {"record": RecordID(runs_table, row["run_id"]), "content": content},
                    dict,
                )
                migrated += 1
            except Exception as e:
                log_error(f"Failed to migrate run {row.get('run_id')}: {str(e)}")

    log_info(
        f"-- Copied {migrated} runs into {runs_table}. The legacy 'runs' field on each session record "
        "was preserved as a backup. Once verified, drop it via db.cleanup_legacy_runs_field()."
    )
    return migrated > 0


def _revert_surrealdb(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Walk runs and rebuild the legacy `runs` blob on each session row."""
    if table_type != "sessions":
        return False

    from surrealdb import RecordID  # type: ignore

    runs_table = db.runs_table_name  # type: ignore

    rows_raw = db._query(f"SELECT * FROM {runs_table}", {}, dict)  # type: ignore
    runs_by_session: Dict[str, List[Any]] = {}
    for r in rows_raw:
        sid = r.get("session_id")
        if isinstance(sid, RecordID):
            sid = sid.id
        if not sid:
            continue
        runs_by_session.setdefault(sid, []).append(
            (r.get("run_index") or 0, r.get("created_at") or 0, r.get("run_data"))
        )

    sessions_table = table_name
    failed_sids: set = set()
    for sid, items in runs_by_session.items():
        items.sort(key=lambda t: (t[0], t[1]))
        legacy_runs = [t[2] for t in items if t[2] is not None]
        try:
            db.client.query(  # type: ignore
                "UPDATE $record SET runs = $runs",
                {"record": RecordID(sessions_table, sid), "runs": legacy_runs},
            )
        except Exception as e:
            log_error(f"Failed to revert runs onto session {sid}: {str(e)}")
            failed_sids.add(sid)

    if not failed_sids:
        # No failures: truncate the whole runs table.
        try:
            db.client.delete(runs_table)  # type: ignore
        except Exception:
            pass
    else:
        # Preserve runs for sessions whose blob rebuild failed -- deleting them
        # would lose the only remaining copy. Delete the rest by record id.
        preserved = 0
        for r in rows_raw:
            sid = r.get("session_id")
            if isinstance(sid, RecordID):
                sid = sid.id
            if sid in failed_sids:
                preserved += 1
                continue
            rid = r.get("id")
            if rid is None:
                continue
            try:
                db.client.delete(rid)  # type: ignore
            except Exception:
                pass
        log_warning(
            f"Preserved {preserved} run(s) in {runs_table} for {len(failed_sids)} session(s) whose "
            "blob rebuild failed; re-run down() after resolving the error."
        )
    return True


# ---------------------------------------------------------------------------
# user_id column
# ---------------------------------------------------------------------------


def _user_id_column_ddl(db, table_type: str) -> Optional[str]:
    """Compile the user_id column type from the adapter's own schema for this table.

    Keeps a migrated table identical to one created fresh from the schema, so a
    later migration reading INFORMATION_SCHEMA sees the same type either way.

    Returns None when this adapter's schema has no such table, or has it without a
    user_id column. Not every table type exists on every backend, and the SQL
    adapters report an unknown table as version 2.0.0 rather than None, so the
    migration is attempted there and has to bow out on its own.
    """
    db_type = type(db).__name__

    schemas: Any
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        from agno.db.postgres import schemas
    elif db_type in ("MySQLDb", "AsyncMySQLDb"):
        from agno.db.mysql import schemas
    elif db_type == "SingleStoreDb":
        from agno.db.singlestore import schemas
    else:
        from agno.db.sqlite import schemas

    try:
        column_type = schemas.get_table_schema_definition(table_type)["user_id"]["type"]
    except (ValueError, KeyError):
        return None
    return column_type().compile(dialect=db.db_engine.dialect)


def _migrate_postgres_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Add the user_id column to the given table for PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        if not _column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Adding user_id column to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN user_id {column_ddl}"))
            applied = True

        if not _index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Adding index {index_name} on {table_name}")
            sess.execute(text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (user_id)"))
            applied = True

        return applied


async def _migrate_async_postgres_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async PostgreSQL variant of :func:`_migrate_postgres_user_id`."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        )
        if not result.scalar():
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        if not await _async_column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Adding user_id column to {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN user_id {column_ddl}"))
            applied = True

        if not await _async_index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Adding index {index_name} on {table_name}")
            await sess.execute(
                text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (user_id)")
            )
            applied = True

        return applied


def _migrate_mysql_like_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Add the user_id column to the given table for MySQL or SingleStore."""
    db_type = type(db).__name__
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or sess.execute(text("SELECT DATABASE()")).scalar()  # type: ignore
        quoted_schema = quote_db_identifier(db_type, db_schema)
        full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        if not _column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Adding user_id column to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN `user_id` {column_ddl}"))
            applied = True

        if not _index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Adding index {index_name} on {table_name}")
            sess.execute(text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`user_id`)"))
            applied = True

        return applied


async def _migrate_async_mysql_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async MySQL variant of :func:`_migrate_mysql_like_user_id`."""
    db_type = type(db).__name__
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        db_schema = db.db_schema or (await sess.execute(text("SELECT DATABASE()"))).scalar()  # type: ignore
        quoted_schema = quote_db_identifier(db_type, db_schema)
        full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

        table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                    "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        if not await _async_column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Adding user_id column to {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN `user_id` {column_ddl}"))
            applied = True

        if not await _async_index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Adding index {index_name} on {table_name}")
            await sess.execute(
                text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`user_id`)")
            )
            applied = True

        return applied


def _migrate_sqlite_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Add the user_id column to the given table for SQLite."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        columns_info = sess.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
        if "user_id" not in {col[1] for col in columns_info}:
            log_info(f"-- Adding user_id column to {table_name}")
            sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN user_id {column_ddl}"))
            applied = True

        indexes = sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall()
        if index_name not in {idx[1] for idx in indexes}:
            log_info(f"-- Adding index {index_name} on {table_name}")
            sess.execute(text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} (user_id)"))
            applied = True

        return applied


async def _migrate_async_sqlite_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async SQLite variant of :func:`_migrate_sqlite_user_id`."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)
    index_name = f"idx_{table_name}_user_id"
    column_ddl = _user_id_column_ddl(db, table_type)
    if column_ddl is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        )
        if not result.scalar():
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        result = await sess.execute(text(f"PRAGMA table_info({quoted_table})"))
        if "user_id" not in {col[1] for col in result.fetchall()}:
            log_info(f"-- Adding user_id column to {table_name}")
            await sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN user_id {column_ddl}"))
            applied = True

        result = await sess.execute(text(f"PRAGMA index_list({quoted_table})"))
        if index_name not in {idx[1] for idx in result.fetchall()}:
            log_info(f"-- Adding index {index_name} on {table_name}")
            await sess.execute(
                text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} (user_id)")
            )
            applied = True

        return applied


def _revert_postgres_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Drop the user_id column from the given table for PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"
    index_name = f"idx_{table_name}_user_id"

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        applied = False

        if _index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Dropping index {index_name} from {table_name}")
            sess.execute(text(f"DROP INDEX {quoted_schema}.{quote_db_identifier(db_type, index_name)}"))
            applied = True

        if _column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Dropping user_id column from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN user_id"))
            applied = True

        return applied


async def _revert_async_postgres_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async PostgreSQL variant of :func:`_revert_postgres_user_id`."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"
    index_name = f"idx_{table_name}_user_id"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        )
        if not result.scalar():
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        applied = False

        if await _async_index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Dropping index {index_name} from {table_name}")
            await sess.execute(text(f"DROP INDEX {quoted_schema}.{quote_db_identifier(db_type, index_name)}"))
            applied = True

        if await _async_column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Dropping user_id column from {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN user_id"))
            applied = True

        return applied


def _revert_mysql_like_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Drop the user_id column from the given table for MySQL or SingleStore."""
    db_type = type(db).__name__
    index_name = f"idx_{table_name}_user_id"

    with db.Session() as sess, sess.begin():  # type: ignore
        # SingleStore leaves db_schema as None and uses the connection's database
        db_schema = db.db_schema or sess.execute(text("SELECT DATABASE()")).scalar()  # type: ignore
        quoted_schema = quote_db_identifier(db_type, db_schema)
        full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

        table_exists = sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        applied = False

        dropped_index = False
        if _index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Dropping index {index_name} from {table_name}")
            sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)} ON {full_table}"))
            dropped_index = True
            applied = True

        if _column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Dropping user_id column from {table_name}")
            try:
                sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN `user_id`"))
            except Exception:
                # MySQL and SingleStore commit DDL immediately, so the index drop
                # above already stuck. Put it back rather than leave the column in
                # place but unindexed.
                if dropped_index:
                    sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`user_id`)")
                    )
                raise
            applied = True

        return applied


async def _revert_async_mysql_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async MySQL variant of :func:`_revert_mysql_like_user_id`."""
    db_type = type(db).__name__
    index_name = f"idx_{table_name}_user_id"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        db_schema = db.db_schema or (await sess.execute(text("SELECT DATABASE()"))).scalar()  # type: ignore
        quoted_schema = quote_db_identifier(db_type, db_schema)
        full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

        table_exists = (
            await sess.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM INFORMATION_SCHEMA.TABLES"
                    "  WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                    ")"
                ),
                {"schema": db_schema, "table_name": table_name},
            )
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        applied = False

        dropped_index = False
        if await _async_index_exists(sess, db_schema, table_name, index_name, db_type):
            log_info(f"-- Dropping index {index_name} from {table_name}")
            await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)} ON {full_table}"))
            dropped_index = True
            applied = True

        if await _async_column_exists(sess, db_schema, table_name, "user_id", db_type):
            log_info(f"-- Dropping user_id column from {table_name}")
            try:
                await sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN `user_id`"))
            except Exception:
                # MySQL commits DDL immediately, so the index drop above already
                # stuck. Put it back rather than leave the column in place but
                # unindexed.
                if dropped_index:
                    await sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`user_id`)")
                    )
                raise
            applied = True

        return applied


def _revert_sqlite_user_id(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Drop the user_id column from the given table for SQLite.

    ``DROP COLUMN`` needs SQLite 3.35+, and the index has to go first because
    SQLite refuses to drop a column an index still references.
    """
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)
    index_name = f"idx_{table_name}_user_id"

    with db.Session() as sess, sess.begin():  # type: ignore
        table_exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()
        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        import sqlite3

        # DROP COLUMN landed in SQLite 3.35.0. Skip rather than drop the index
        # and then fail on the column, which would leave user_id unindexed.
        if sqlite3.sqlite_version_info < (3, 35, 0):
            log_info(f"SQLite revert for {table_name}: DROP COLUMN needs SQLite >= 3.35.0, skipping")
            return False

        applied = False

        dropped_index = False
        indexes = sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall()
        if index_name in {idx[1] for idx in indexes}:
            log_info(f"-- Dropping index {index_name} from {table_name}")
            sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)}"))
            dropped_index = True
            applied = True

        columns_info = sess.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
        if "user_id" in {col[1] for col in columns_info}:
            log_info(f"-- Dropping user_id column from {table_name}")
            try:
                sess.execute(text(f"ALTER TABLE {quoted_table} DROP COLUMN user_id"))
            except Exception:
                # SQLite commits DDL outside the session transaction, so the index
                # drop above already stuck. Put it back rather than leave the column
                # in place but unindexed.
                if dropped_index:
                    sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} (user_id)")
                    )
                raise
            applied = True

        return applied


async def _revert_async_sqlite_user_id(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async SQLite variant of :func:`_revert_sqlite_user_id`."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)
    index_name = f"idx_{table_name}_user_id"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        )
        if not result.scalar():
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        import sqlite3

        # DROP COLUMN landed in SQLite 3.35.0. Skip rather than drop the index
        # and then fail on the column, which would leave user_id unindexed.
        if sqlite3.sqlite_version_info < (3, 35, 0):
            log_info(f"SQLite revert for {table_name}: DROP COLUMN needs SQLite >= 3.35.0, skipping")
            return False

        applied = False

        result = await sess.execute(text(f"PRAGMA index_list({quoted_table})"))
        dropped_index = False
        if index_name in {idx[1] for idx in result.fetchall()}:
            log_info(f"-- Dropping index {index_name} from {table_name}")
            await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)}"))
            dropped_index = True
            applied = True

        result = await sess.execute(text(f"PRAGMA table_info({quoted_table})"))
        if "user_id" in {col[1] for col in result.fetchall()}:
            log_info(f"-- Dropping user_id column from {table_name}")
            try:
                await sess.execute(text(f"ALTER TABLE {quoted_table} DROP COLUMN user_id"))
            except Exception:
                # SQLite commits DDL outside the session transaction, so the index
                # drop above already stuck. Put it back rather than leave the column
                # in place but unindexed.
                if dropped_index:
                    await sess.execute(
                        text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} (user_id)")
                    )
                raise
            applied = True

        return applied
