"""Migration v3.0.0: Normalize session runs into a dedicated runs table

Changes:
- Create the runs table (one row per run, with the run payload as JSON)
- Copy every run stored in the sessions table `runs` column into the runs table

This removes the unbounded growth of session rows: each run is now stored once,
in its own row, instead of the whole run list being rewritten on every save.

The legacy `runs` column on `agno_sessions` is intentionally NOT dropped by this
migration — it stays in place as a backup. New writes will null it as sessions
are touched. When you have verified the migration and taken a backup, drop the
column manually by calling ``db.cleanup_legacy_runs_column()``.
"""

import json
import time
from typing import Any, Dict, List, Optional

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.db.utils import CustomJSONEncoder
from agno.utils.log import log_error, log_info

try:
    from sqlalchemy import text
    from sqlalchemy.dialects import mysql, postgresql, sqlite
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

BATCH_SIZE = 50


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Move session runs into the runs table and drop the sessions `runs` column.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "PostgresDb":
            return _migrate_postgres(db, table_name)
        elif db_type == "SqliteDb":
            return _migrate_sqlite(db, table_name)
        elif db_type in ("MySQLDb", "SingleStoreDb"):
            return _migrate_mysql_like(db, table_name)
        elif db_type == "MongoDb":
            return _migrate_mongo(db, table_name)
        elif db_type == "FirestoreDb":
            return _migrate_firestore(db, table_name)
        elif db_type == "RedisDb":
            return _migrate_redis(db, table_name)
        elif db_type == "JsonDb":
            return _migrate_jsondb(db, table_name)
        elif db_type == "GcsJsonDb":
            return _migrate_gcsjsondb(db, table_name)
        elif db_type == "InMemoryDb":
            return _migrate_inmemorydb(db, table_name)
        elif db_type == "DynamoDb":
            return _migrate_dynamodb(db, table_name)
        elif db_type == "SurrealDb":
            return _migrate_surrealdb(db, table_name)
        else:
            log_info(f"Migration v3.0.0 is not implemented for {db_type}. Sessions will keep storing runs inline.")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Move session runs into the runs table and drop the sessions `runs` column.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "AsyncPostgresDb":
            return await _migrate_async_postgres(db, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _migrate_async_sqlite(db, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _migrate_async_mysql(db, table_name)
        elif db_type == "AsyncMongoDb":
            return await _migrate_async_mongo(db, table_name)
        else:
            log_info(f"Migration v3.0.0 is not implemented for {db_type}. Sessions will keep storing runs inline.")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "PostgresDb":
            return _revert_postgres(db, table_name)
        elif db_type == "SqliteDb":
            return _revert_sqlite(db, table_name)
        elif db_type in ("MySQLDb", "SingleStoreDb"):
            return _revert_mysql_like(db, table_name)
        elif db_type == "MongoDb":
            return _revert_mongo(db, table_name)
        elif db_type == "FirestoreDb":
            return _revert_firestore(db, table_name)
        elif db_type == "RedisDb":
            return _revert_redis(db, table_name)
        elif db_type == "JsonDb":
            return _revert_jsondb(db, table_name)
        elif db_type == "GcsJsonDb":
            return _revert_gcsjsondb(db, table_name)
        elif db_type == "InMemoryDb":
            return _revert_inmemorydb(db, table_name)
        elif db_type == "DynamoDb":
            return _revert_dynamodb(db, table_name)
        elif db_type == "SurrealDb":
            return _revert_surrealdb(db, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Revert: move runs back into the sessions `runs` column and drop the runs table.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "AsyncPostgresDb":
            return await _revert_async_postgres(db, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _revert_async_sqlite(db, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _revert_async_mysql(db, table_name)
        elif db_type == "AsyncMongoDb":
            return await _revert_async_mongo(db, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise


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


def _column_exists_postgres(sess, db_schema: str, table_name: str, column_name: str) -> bool:
    query = text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
    )
    return sess.execute(query, {"schema": db_schema, "table": table_name, "column": column_name}).scalar() is not None


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _migrate_postgres(db: BaseDb, table_name: str) -> bool:
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

        if not _column_exists_postgres(sess, db_schema, table_name, "runs"):
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


async def _migrate_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
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

        column_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table AND column_name = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).scalar() is not None
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


def _migrate_sqlite(db: BaseDb, table_name: str) -> bool:
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


async def _migrate_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
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


def _revert_postgres(db: BaseDb, table_name: str) -> bool:
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
        if not _column_exists_postgres(sess, db_schema, table_name, "runs"):
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

        return True


async def _revert_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
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
        column_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table AND column_name = 'runs'"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).scalar() is not None
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

        return True


def _revert_sqlite(db: BaseDb, table_name: str) -> bool:
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
            runs = [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in run_rows]
            sess.execute(
                text(f"UPDATE {table_name} SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        sess.execute(text(f"DROP TABLE {runs_table_name}"))

        return True


async def _revert_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
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
            runs = [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in run_rows]
            await sess.execute(
                text(f"UPDATE {table_name} SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        await sess.execute(text(f"DROP TABLE {runs_table_name}"))

        return True


# ---------------------------------------------------------------------------
# MySQL / SingleStore (sync). SingleStore is MySQL-protocol-compatible so it
# uses the same code path. AsyncMySQLDb has its own coroutine variants below.
# ---------------------------------------------------------------------------


def _migrate_mysql_like(db: BaseDb, table_name: str) -> bool:
    """Move session runs into the runs table for MySQL or SingleStore.

    Non-destructive: the legacy `runs` column is left in place. Call
    ``db.cleanup_legacy_runs_column()`` to drop it once you have verified
    the migration and taken a backup.
    """
    db_schema = db.db_schema or "agno"  # type: ignore

    # Ensure the runs table exists
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    with db.Session() as sess, sess.begin():  # type: ignore
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


async def _migrate_async_mysql(db: AsyncBaseDb, table_name: str) -> bool:
    """Async MySQL variant of :func:`_migrate_mysql_like`."""
    db_schema = db.db_schema or "agno"  # type: ignore

    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)  # type: ignore
    if runs_table is None:
        return False

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
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


def _revert_mysql_like(db: BaseDb, table_name: str) -> bool:
    """Revert: rebuild blobs in `sessions.runs` from the runs table; drop the runs table."""
    db_schema = db.db_schema or "agno"  # type: ignore
    runs_table_name = db.runs_table_name  # type: ignore

    with db.Session() as sess, sess.begin():  # type: ignore
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
            runs = [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in run_rows]
            sess.execute(
                text(f"UPDATE `{db_schema}`.`{table_name}` SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        # Drop the runs table
        log_info(f"-- Dropping runs table {runs_table_name}")
        sess.execute(text(f"DROP TABLE `{db_schema}`.`{runs_table_name}`"))

        return True


async def _revert_async_mysql(db: AsyncBaseDb, table_name: str) -> bool:
    """Async MySQL variant of :func:`_revert_mysql_like`."""
    db_schema = db.db_schema or "agno"  # type: ignore
    runs_table_name = db.runs_table_name  # type: ignore

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
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
            runs = [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in run_rows]
            await sess.execute(
                text(f"UPDATE `{db_schema}`.`{table_name}` SET runs = :runs WHERE session_id = :session_id"),
                {"runs": json.dumps(runs, cls=CustomJSONEncoder), "session_id": session_id},
            )

        log_info(f"-- Dropping runs table {runs_table_name}")
        await sess.execute(text(f"DROP TABLE `{db_schema}`.`{runs_table_name}`"))

        return True


# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------


def _migrate_mongo(db: BaseDb, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session documents into the runs collection.

    Non-destructive: the legacy `runs` field is left in place. Call
    ``db.cleanup_legacy_runs_field()`` to remove it once you have verified
    the migration and taken a backup.
    """
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


def _revert_mongo(db: BaseDb, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session documents from the runs collection.

    The runs collection is dropped at the end.
    """
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


async def _migrate_async_mongo(db: AsyncBaseDb, table_name: str) -> bool:
    """Async variant of :func:`_migrate_mongo`."""
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


async def _revert_async_mongo(db: AsyncBaseDb, table_name: str) -> bool:
    """Async variant of :func:`_revert_mongo`."""
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
    async for group in runs_collection.aggregate(pipeline):
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


def _migrate_firestore(db: BaseDb, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session documents into the runs collection.

    Non-destructive: the legacy `runs` field is left in place. Call
    ``db.cleanup_legacy_runs_field()`` to remove it once verified.
    """
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


def _revert_firestore(db: BaseDb, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session documents from the runs collection.

    The runs collection is deleted at the end.
    """
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


def _migrate_redis(db: BaseDb, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on session records into per-run keys.

    Non-destructive: the legacy `runs` field is left in place on the session
    record. Call ``db.cleanup_legacy_runs_field()`` once you have verified the
    migration to free the storage.
    """
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


def _revert_redis(db: BaseDb, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on session records, then delete run keys."""
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
# JsonDb / GcsJsonDb / InMemoryDb
# These adapters store sessions as a single list (file/object/in-memory dict).
# Each one exposes the same `_store_session_runs`-style helper added in v3,
# plus a way to walk the legacy `runs` field on each session record.
# ---------------------------------------------------------------------------


def _migrate_jsondb(db: BaseDb, table_name: str) -> bool:
    """Copy runs from the legacy `runs` field on each session record into the runs file."""
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


def _revert_jsondb(db: BaseDb, table_name: str) -> bool:
    """Revert: rebuild the legacy `runs` field on each session record from the runs file."""
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


def _migrate_gcsjsondb(db: BaseDb, table_name: str) -> bool:
    """Same shape as :func:`_migrate_jsondb` — both store sessions as a JSON list (file vs object)."""
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


def _revert_gcsjsondb(db: BaseDb, table_name: str) -> bool:
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


def _migrate_inmemorydb(db: BaseDb, table_name: str) -> bool:
    """InMemoryDb is not normalized in v3.0; runs stay inline."""
    log_info("-- InMemoryDb does not split runs into a separate table; skipping migration.")
    return False


def _revert_inmemorydb(db: BaseDb, table_name: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# DynamoDb
# ---------------------------------------------------------------------------


def _migrate_dynamodb(db: BaseDb, table_name: str) -> bool:
    """Copy legacy `runs` blob from each session item into the agno_runs table."""
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
            try:
                client.put_item(
                    TableName=runs_table,
                    Item=dynamo_item,
                    ConditionExpression="attribute_not_exists(run_id)",
                )
                migrated += 1
            except client.exceptions.ConditionalCheckFailedException:
                continue
            except Exception as e:
                log_error(f"Failed to migrate run {payload.get('run_id')}: {str(e)}")

    log_info(
        f"-- Copied {migrated} runs into {runs_table}. The legacy 'runs' attribute on each session item "
        "was preserved as a backup. Once verified, drop it via db.cleanup_legacy_runs_field()."
    )
    return migrated > 0


def _revert_dynamodb(db: BaseDb, table_name: str) -> bool:
    """Walk runs and re-attach to session items, then truncate the runs table."""
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

    # Best-effort: truncate the runs table
    for it in items:
        run_id = it.get("run_id", {}).get("S")
        if not run_id:
            continue
        try:
            client.delete_item(TableName=runs_table, Key={"run_id": {"S": run_id}})
        except Exception:
            pass

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


def _migrate_surrealdb(db: BaseDb, table_name: str) -> bool:
    """Copy legacy `runs` blob from each session record into the runs table."""
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


def _revert_surrealdb(db: BaseDb, table_name: str) -> bool:
    """Walk runs and rebuild the legacy `runs` blob on each session row."""
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

    try:
        db.client.delete(runs_table)  # type: ignore
    except Exception:
        pass
    return True
