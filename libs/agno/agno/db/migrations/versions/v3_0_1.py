"""Migration v3.0.1: Backfill the schedule provenance columns

Changes:
- Add the eight nullable provenance columns from ``SCHEDULE_PROVENANCE_COLUMNS``
  (managed_by, target_type, target_id, created_by_run_id, created_by_session_id,
  updated_by_run_id, updated_by_session_id, disabled_reason) to the schedules table
- Add the idx_<table>_managed_by and idx_<table>_target_id lookup indexes

Why this exists: an early 3.0.0 build created the schedules table before the
provenance columns entered the schema, and the adapters stamp a table with the
latest version at creation time — so those tables sit at 3.0.0 without the
columns. The manager only runs versions strictly greater than the stamp, which
means v3.0.0's own ensure-block can never reach them (``up(force=True)`` only
bypasses the up-to-date check, not the strictly-greater version selection).
Re-shipping just the ensure-block under the next version number heals them.

Every step is idempotent: a table that already has the columns (created fresh,
or migrated from pre-3.0 by v3.0.0) is left unchanged. Document backends carry
the fields without a schema change, and MySQL/SingleStore never got the
provenance block in v3.0.0, so only the engines v3.0.0 covers for it are
handled here: PostgreSQL and SQLite, sync and async.
"""

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.db.migrations.versions.v3_0_0 import SCHEDULE_PROVENANCE_COLUMNS, SCHEDULE_PROVENANCE_INDEXED
from agno.utils.log import log_error, log_info

try:
    from sqlalchemy import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Ensure the schedule provenance columns and their indexes exist on the schedules table.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "schedules":
            return False

        if db_type == "PostgresDb":
            return _migrate_postgres_schedules(db, table_name)
        elif db_type == "SqliteDb":
            return _migrate_sqlite_schedules(db, table_name)
        else:
            log_info(f"Migration v3.0.1 is not needed for {db_type}. Table '{table_name}' is left unchanged.")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.1 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Ensure the schedule provenance columns and their indexes exist on the schedules table.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "schedules":
            return False

        if db_type == "AsyncPostgresDb":
            return await _migrate_async_postgres_schedules(db, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _migrate_async_sqlite_schedules(db, table_name)
        else:
            log_info(f"Migration v3.0.1 is not needed for {db_type}. Table '{table_name}' is left unchanged.")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.1 for {db_type} on table {table_name}: {str(e)}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert is a deliberate no-op: the provenance columns are nullable and may hold
    operator data (e.g. disabled_reason), and v3.0.0's own revert leaves them in
    place too. Dropping them would lose data a re-run cannot restore.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    if table_type == "schedules":
        log_info(f"Revert of v3.0.1 is a no-op: the provenance columns on '{table_name}' are left in place.")
    return False


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert is a deliberate no-op: see :func:`down`.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    if table_type == "schedules":
        log_info(f"Revert of v3.0.1 is a no-op: the provenance columns on '{table_name}' are left in place.")
    return False


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _migrate_postgres_schedules(db: BaseDb, table_name: str) -> bool:
    """Ensure the provenance columns and indexes on the schedules table for PostgreSQL."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

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

        for column in SCHEDULE_PROVENANCE_COLUMNS:
            if not _column_exists(sess, db_schema, table_name, column):
                log_info(f"-- Adding {column} column to {table_name}")
                # IF NOT EXISTS: a replica booting alongside another should not die over a
                # column the other added between the check above and this statement
                sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS {column} VARCHAR"))
                applied = True

        for column in SCHEDULE_PROVENANCE_INDEXED:
            index_name = f"idx_{table_name}_{column}"
            if not _index_exists(sess, db_schema, table_name, index_name):
                log_info(f"-- Adding index {index_name} on {table_name}")
                sess.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {quote_db_identifier(db_type, index_name)} "
                        f"ON {full_table} ({column})"
                    )
                )
                applied = True

        return applied


async def _migrate_async_postgres_schedules(db: AsyncBaseDb, table_name: str) -> bool:
    """Async PostgreSQL variant of :func:`_migrate_postgres_schedules`."""
    db_schema = db.db_schema or "ai"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    full_table = f"{quoted_schema}.{quote_db_identifier(db_type, table_name)}"

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

        for column in SCHEDULE_PROVENANCE_COLUMNS:
            if not await _async_column_exists(sess, db_schema, table_name, column):
                log_info(f"-- Adding {column} column to {table_name}")
                # See _migrate_postgres_schedules: IF NOT EXISTS lets two replicas
                # migrate the same table at once
                await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS {column} VARCHAR"))
                applied = True

        for column in SCHEDULE_PROVENANCE_INDEXED:
            index_name = f"idx_{table_name}_{column}"
            if not await _async_index_exists(sess, db_schema, table_name, index_name):
                log_info(f"-- Adding index {index_name} on {table_name}")
                await sess.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {quote_db_identifier(db_type, index_name)} "
                        f"ON {full_table} ({column})"
                    )
                )
                applied = True

        return applied


def _column_exists(sess, db_schema: str, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a PostgreSQL table."""
    result = sess.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        ),
        {"schema": db_schema, "table": table_name, "column": column_name},
    )
    return result.scalar() is not None


async def _async_column_exists(sess, db_schema: str, table_name: str, column_name: str) -> bool:
    """Async version: check if a column exists in a PostgreSQL table."""
    result = await sess.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        ),
        {"schema": db_schema, "table": table_name, "column": column_name},
    )
    return result.scalar() is not None


def _index_exists(sess, db_schema: str, table_name: str, index_name: str) -> bool:
    """Check if an index exists on a PostgreSQL table."""
    result = sess.execute(
        text("SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND tablename = :table AND indexname = :index"),
        {"schema": db_schema, "table": table_name, "index": index_name},
    )
    return result.scalar() is not None


async def _async_index_exists(sess, db_schema: str, table_name: str, index_name: str) -> bool:
    """Async version: check if an index exists on a PostgreSQL table."""
    result = await sess.execute(
        text("SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND tablename = :table AND indexname = :index"),
        {"schema": db_schema, "table": table_name, "index": index_name},
    )
    return result.scalar() is not None


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def _migrate_sqlite_schedules(db: BaseDb, table_name: str) -> bool:
    """Ensure the provenance columns and indexes on the schedules table for SQLite."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

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
        existing_columns = {col[1] for col in columns_info}
        indexes = sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall()
        existing_indexes = {idx[1] for idx in indexes}

        for column in SCHEDULE_PROVENANCE_COLUMNS:
            if column not in existing_columns:
                log_info(f"-- Adding {column} column to {table_name}")
                sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN {column} TEXT"))
                applied = True

        for column in SCHEDULE_PROVENANCE_INDEXED:
            index_name = f"idx_{table_name}_{column}"
            if index_name not in existing_indexes:
                log_info(f"-- Adding index {index_name} on {table_name}")
                sess.execute(
                    text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} ({column})")
                )
                applied = True

        return applied


async def _migrate_async_sqlite_schedules(db: AsyncBaseDb, table_name: str) -> bool:
    """Async SQLite variant of :func:`_migrate_sqlite_schedules`."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        )
        if not result.scalar():
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        columns_info = (await sess.execute(text(f"PRAGMA table_info({quoted_table})"))).fetchall()
        existing_columns = {col[1] for col in columns_info}
        indexes = (await sess.execute(text(f"PRAGMA index_list({quoted_table})"))).fetchall()
        existing_indexes = {idx[1] for idx in indexes}

        for column in SCHEDULE_PROVENANCE_COLUMNS:
            if column not in existing_columns:
                log_info(f"-- Adding {column} column to {table_name}")
                await sess.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN {column} TEXT"))
                applied = True

        for column in SCHEDULE_PROVENANCE_INDEXED:
            index_name = f"idx_{table_name}_{column}"
            if index_name not in existing_indexes:
                log_info(f"-- Adding index {index_name} on {table_name}")
                await sess.execute(
                    text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {quoted_table} ({column})")
                )
                applied = True

        return applied
