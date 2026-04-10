"""Migration v2.5.6: Add run_status column to approvals table

Changes:
- Add run_status column to agno_approvals table
- Add index on run_status column for performance
"""

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.utils.log import log_error, log_info

try:
    from sqlalchemy import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Add run_status column to approvals table.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "approvals":
            return False

        if db_type == "PostgresDb":
            return _migrate_postgres(db, table_name)
        elif db_type == "MySQLDb":
            return _migrate_mysql(db, table_name)
        elif db_type == "SingleStoreDb":
            return _migrate_singlestore(db, table_name)
        elif db_type == "SqliteDb":
            return _migrate_sqlite(db, table_name)
        else:
            log_info(f"{db_type} does not require schema migrations")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.5.6 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Add run_status column to approvals table.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "approvals":
            return False

        if db_type == "AsyncPostgresDb":
            return await _migrate_async_postgres(db, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _migrate_async_mysql(db, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _migrate_async_sqlite(db, table_name)
        else:
            log_info(f"{db_type} does not require schema migrations")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.5.6 for {db_type} on table {table_name}: {str(e)}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert: drop run_status column from approvals table.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "approvals":
            return False

        if db_type == "PostgresDb":
            return _revert_postgres(db, table_name)
        elif db_type == "MySQLDb":
            return _revert_mysql(db, table_name)
        elif db_type == "SingleStoreDb":
            return _revert_singlestore(db, table_name)
        elif db_type == "SqliteDb":
            return _revert_sqlite(db, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v2.5.6 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert: drop run_status column from approvals table.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "approvals":
            return False

        if db_type == "AsyncPostgresDb":
            return await _revert_async_postgres(db, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _revert_async_mysql(db, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _revert_async_sqlite(db, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v2.5.6 for {db_type} on table {table_name} asynchronously: {str(e)}")
        raise


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


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


def _migrate_postgres(db: BaseDb, table_name: str) -> bool:
    """Add run_status column to approvals table for PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
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

        # Check if run_status column already exists
        has_column = _column_exists(sess, db_schema, table_name, "run_status", db_type)
        if not has_column:
            log_info(f"-- Adding run_status column to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN run_status TEXT"))
            applied = True

        # Add index on run_status if it doesn't exist
        has_index = _index_exists(sess, db_schema, table_name, index_name, db_type)
        if not has_index:
            log_info(f"-- Adding index {index_name} on {table_name}")
            sess.execute(text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (run_status)"))
            applied = True

        return applied


async def _migrate_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    """Add run_status column to approvals table for async PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # Check if table exists
        result = await sess.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :table_name"
                ")"
            ),
            {"schema": db_schema, "table_name": table_name},
        )
        table_exists = result.scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        # Check if run_status column already exists
        has_column = await _async_column_exists(sess, db_schema, table_name, "run_status", db_type)
        if not has_column:
            log_info(f"-- Adding run_status column to {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN run_status TEXT"))
            applied = True

        # Add index on run_status if it doesn't exist
        has_index = await _async_index_exists(sess, db_schema, table_name, index_name, db_type)
        if not has_index:
            log_info(f"-- Adding index {index_name} on {table_name}")
            await sess.execute(
                text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (run_status)")
            )
            applied = True

        return applied


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------


def _migrate_mysql(db: BaseDb, table_name: str) -> bool:
    """Add run_status column to approvals table for MySQL."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
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

        # Check if run_status column already exists
        has_column = _column_exists(sess, db_schema, table_name, "run_status", db_type)
        if not has_column:
            log_info(f"-- Adding run_status column to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN `run_status` TEXT"))
            applied = True

        # Add index on run_status if it doesn't exist
        has_index = _index_exists(sess, db_schema, table_name, index_name, db_type)
        if not has_index:
            log_info(f"-- Adding index {index_name} on {table_name}")
            # MySQL requires specifying length for TEXT columns in indexes
            sess.execute(
                text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`run_status`(255))")
            )
            applied = True

        return applied


async def _migrate_async_mysql(db: AsyncBaseDb, table_name: str) -> bool:
    """Add run_status column to approvals table for async MySQL."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

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

        applied = False

        # Check if run_status column already exists
        has_column = await _async_column_exists(sess, db_schema, table_name, "run_status", db_type)
        if not has_column:
            log_info(f"-- Adding run_status column to {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN `run_status` TEXT"))
            applied = True

        # Add index on run_status if it doesn't exist
        has_index = await _async_index_exists(sess, db_schema, table_name, index_name, db_type)
        if not has_index:
            log_info(f"-- Adding index {index_name} on {table_name}")
            await sess.execute(
                text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`run_status`(255))")
            )
            applied = True

        return applied


# ---------------------------------------------------------------------------
# SingleStore
# ---------------------------------------------------------------------------


def _migrate_singlestore(db: BaseDb, table_name: str) -> bool:
    """Add run_status column to approvals table for SingleStore."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
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

        # Check if run_status column already exists
        has_column = _column_exists(sess, db_schema, table_name, "run_status", db_type)
        if not has_column:
            log_info(f"-- Adding run_status column to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD COLUMN `run_status` TEXT"))
            applied = True

        # Add index on run_status if it doesn't exist
        has_index = _index_exists(sess, db_schema, table_name, index_name, db_type)
        if not has_index:
            log_info(f"-- Adding index {index_name} on {table_name}")
            sess.execute(
                text(f"CREATE INDEX {quote_db_identifier(db_type, index_name)} ON {full_table} (`run_status`(255))")
            )
            applied = True

        return applied


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def _migrate_sqlite(db: BaseDb, table_name: str) -> bool:
    """Add run_status column to approvals table for SQLite."""
    index_name = f"ix_{table_name}_run_status"

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        table_exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        # Check if run_status column already exists
        columns_info = sess.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        existing_columns = {col[1] for col in columns_info}

        if "run_status" not in existing_columns:
            log_info(f"-- Adding run_status column to {table_name}")
            sess.execute(text(f"ALTER TABLE {table_name} ADD COLUMN run_status TEXT"))
            applied = True
        else:
            log_info(f"Column run_status already exists in {table_name}, skipping")

        # Check if index exists
        indexes = sess.execute(text(f"PRAGMA index_list({table_name})")).fetchall()
        index_names = {idx[1] for idx in indexes}

        if index_name not in index_names:
            log_info(f"-- Adding index {index_name} on {table_name}")
            sess.execute(text(f"CREATE INDEX {index_name} ON {table_name} (run_status)"))
            applied = True

        return applied


async def _migrate_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
    """Add run_status column to approvals table for async SQLite."""
    index_name = f"ix_{table_name}_run_status"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        # Check if table exists
        result = await sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        )
        table_exists = result.scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        applied = False

        # Check if run_status column already exists
        result = await sess.execute(text(f"PRAGMA table_info({table_name})"))
        columns_info = result.fetchall()
        existing_columns = {col[1] for col in columns_info}

        if "run_status" not in existing_columns:
            log_info(f"-- Adding run_status column to {table_name}")
            await sess.execute(text(f"ALTER TABLE {table_name} ADD COLUMN run_status TEXT"))
            applied = True
        else:
            log_info(f"Column run_status already exists in {table_name}, skipping")

        # Check if index exists
        result = await sess.execute(text(f"PRAGMA index_list({table_name})"))
        indexes = result.fetchall()
        index_names = {idx[1] for idx in indexes}

        if index_name not in index_names:
            log_info(f"-- Adding index {index_name} on {table_name}")
            await sess.execute(text(f"CREATE INDEX {index_name} ON {table_name} (run_status)"))
            applied = True

        return applied


# ---------------------------------------------------------------------------
# Revert functions
# ---------------------------------------------------------------------------


def _revert_postgres(db: BaseDb, table_name: str) -> bool:
    """Revert: drop run_status column from approvals table for PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

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

        # Drop index if it exists
        has_index = _index_exists(sess, db_schema, table_name, index_name, db_type)
        if has_index:
            log_info(f"-- Dropping index {index_name} from {table_name}")
            sess.execute(text(f"DROP INDEX {quoted_schema}.{quote_db_identifier(db_type, index_name)}"))
            applied = True

        # Drop column if it exists
        has_column = _column_exists(sess, db_schema, table_name, "run_status", db_type)
        if has_column:
            log_info(f"-- Dropping run_status column from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN run_status"))
            applied = True

        return applied


async def _revert_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert: drop run_status column from approvals table for async PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

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
        table_exists = result.scalar()

        if not table_exists:
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        applied = False

        # Drop index if it exists
        has_index = await _async_index_exists(sess, db_schema, table_name, index_name, db_type)
        if has_index:
            log_info(f"-- Dropping index {index_name} from {table_name}")
            await sess.execute(text(f"DROP INDEX {quoted_schema}.{quote_db_identifier(db_type, index_name)}"))
            applied = True

        # Drop column if it exists
        has_column = await _async_column_exists(sess, db_schema, table_name, "run_status", db_type)
        if has_column:
            log_info(f"-- Dropping run_status column from {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN run_status"))
            applied = True

        return applied


def _revert_mysql(db: BaseDb, table_name: str) -> bool:
    """Revert: drop run_status column from approvals table for MySQL."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

    with db.Session() as sess, sess.begin():  # type: ignore
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

        # Drop index if it exists
        has_index = _index_exists(sess, db_schema, table_name, index_name, db_type)
        if has_index:
            log_info(f"-- Dropping index {index_name} from {table_name}")
            sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)} ON {full_table}"))
            applied = True

        # Drop column if it exists
        has_column = _column_exists(sess, db_schema, table_name, "run_status", db_type)
        if has_column:
            log_info(f"-- Dropping run_status column from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN `run_status`"))
            applied = True

        return applied


async def _revert_async_mysql(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert: drop run_status column from approvals table for async MySQL."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

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
            log_info(f"Table {table_name} does not exist, skipping revert")
            return False

        applied = False

        # Drop index if it exists
        has_index = await _async_index_exists(sess, db_schema, table_name, index_name, db_type)
        if has_index:
            log_info(f"-- Dropping index {index_name} from {table_name}")
            await sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)} ON {full_table}"))
            applied = True

        # Drop column if it exists
        has_column = await _async_column_exists(sess, db_schema, table_name, "run_status", db_type)
        if has_column:
            log_info(f"-- Dropping run_status column from {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN `run_status`"))
            applied = True

        return applied


def _revert_singlestore(db: BaseDb, table_name: str) -> bool:
    """Revert: drop run_status column from approvals table for SingleStore."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    index_name = f"ix_{table_name}_run_status"

    with db.Session() as sess, sess.begin():  # type: ignore
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

        # Drop index if it exists
        has_index = _index_exists(sess, db_schema, table_name, index_name, db_type)
        if has_index:
            log_info(f"-- Dropping index {index_name} from {table_name}")
            sess.execute(text(f"DROP INDEX {quote_db_identifier(db_type, index_name)} ON {full_table}"))
            applied = True

        # Drop column if it exists
        has_column = _column_exists(sess, db_schema, table_name, "run_status", db_type)
        if has_column:
            log_info(f"-- Dropping run_status column from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP COLUMN `run_status`"))
            applied = True

        return applied


def _revert_sqlite(db: BaseDb, table_name: str) -> bool:
    """Revert: SQLite does not support DROP COLUMN in older versions, so we skip."""
    log_info(f"SQLite revert for {table_name}: DROP COLUMN not universally supported, skipping")
    return False


async def _revert_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert: SQLite does not support DROP COLUMN in older versions, so we skip."""
    log_info(f"SQLite revert for {table_name}: DROP COLUMN not universally supported, skipping")
    return False
