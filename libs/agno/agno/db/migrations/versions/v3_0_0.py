"""Migration v3.0.0: Normalize session runs into a dedicated runs table

Changes:
- Create the runs table (one row per run, with the run payload as JSON)
- Move every run stored in the sessions table `runs` column into the runs table
- Drop the `runs` column from the sessions table

This removes the unbounded growth of session rows: each run is now stored once,
in its own row, instead of the whole run list being rewritten on every save.
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
    from sqlalchemy.dialects import postgresql, sqlite
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

        log_info(f"-- Moved {migrated_runs} runs from {table_name} into the runs table")

        # Drop the legacy runs column
        log_info(f"-- Dropping runs column from {table_name}")
        sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN runs"))

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

        log_info(f"-- Moved {migrated_runs} runs from {table_name} into the runs table")

        # Drop the legacy runs column
        log_info(f"-- Dropping runs column from {table_name}")
        await sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN runs"))

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

        log_info(f"-- Moved {migrated_runs} runs from {table_name} into the runs table")

        # Drop the legacy runs column. Not supported in SQLite < 3.35: clear the column instead.
        try:
            sess.execute(text(f"ALTER TABLE {table_name} DROP COLUMN runs"))
            log_info(f"-- Dropped runs column from {table_name}")
        except Exception:
            sess.execute(text(f"UPDATE {table_name} SET runs = NULL"))
            log_info(f"-- Could not drop runs column from {table_name}, cleared its content instead")

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

        log_info(f"-- Moved {migrated_runs} runs from {table_name} into the runs table")

        # Drop the legacy runs column. Not supported in SQLite < 3.35: clear the column instead.
        try:
            await sess.execute(text(f"ALTER TABLE {table_name} DROP COLUMN runs"))
            log_info(f"-- Dropped runs column from {table_name}")
        except Exception:
            await sess.execute(text(f"UPDATE {table_name} SET runs = NULL"))
            log_info(f"-- Could not drop runs column from {table_name}, cleared its content instead")

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
