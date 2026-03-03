"""Migration v2.6.0: Change session primary key to composite (session_id, session_type)

Changes:
- Replace the single-column PRIMARY KEY (session_id) with a composite
  PRIMARY KEY (session_id, session_type) so that different session types
  (agent, team, workflow) can share the same session_id without overwriting
  each other.

Fixes: https://github.com/agno-agi/agno/issues/6733
"""

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.utils.log import log_error, log_info, log_warning

try:
    from sqlalchemy import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Change PRIMARY KEY from (session_id) to (session_id, session_type).

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "PostgresDb":
            return _migrate_postgres(db, table_name)
        elif db_type == "MySQLDb":
            return _migrate_mysql(db, table_name)
        elif db_type in ("SqliteDb", "SingleStoreDb"):
            # SQLite: cannot ALTER PK; new tables use correct schema automatically.
            # SingleStore: already uses (session_id, session_type) unique key.
            return False
        else:
            log_info(f"{db_type} does not require schema migrations for v2.6.0")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.6.0 for {db_type} on table {table_name}: {e}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Change PRIMARY KEY from (session_id) to (session_id, session_type).

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "AsyncPostgresDb":
            return await _migrate_async_postgres(db, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _migrate_async_mysql(db, table_name)
        elif db_type in ("AsyncSqliteDb",):
            # SQLite: cannot ALTER PK; new tables use correct schema automatically.
            return False
        else:
            log_info(f"{db_type} does not require schema migrations for v2.6.0")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.6.0 for {db_type} on table {table_name}: {e}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert: change PRIMARY KEY back from (session_id, session_type) to (session_id).

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "PostgresDb":
            return _revert_postgres(db, table_name)
        elif db_type == "MySQLDb":
            return _revert_mysql(db, table_name)
        elif db_type in ("SqliteDb", "SingleStoreDb"):
            return False
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v2.6.0 for {db_type} on table {table_name}: {e}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert: change PRIMARY KEY back from (session_id, session_type) to (session_id).

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "AsyncPostgresDb":
            return await _revert_async_postgres(db, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _revert_async_mysql(db, table_name)
        elif db_type in ("AsyncSqliteDb",):
            return False
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v2.6.0 for {db_type} on table {table_name}: {e}")
        raise


# ---------------------------------------------------------------------------
# PostgreSQL (sync)
# ---------------------------------------------------------------------------


def _migrate_postgres(db: BaseDb, table_name: str) -> bool:
    """Change PRIMARY KEY to (session_id, session_type) for PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

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

        # Check if PK already includes session_type (already migrated)
        pk_columns = _get_pk_columns_postgres(sess, db_schema, table_name)
        if "session_type" in pk_columns:
            log_info(f"Table {table_name} already has composite PK (session_id, session_type), skipping")
            return False

        # Drop the existing PK (session_id only)
        pk_name = _get_pk_name_postgres(sess, db_schema, table_name)
        if pk_name:
            log_info(f"-- Dropping old PRIMARY KEY {pk_name} from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT {quote_db_identifier(db_type, pk_name)}"))

        # Add composite PK
        log_info(f"-- Adding composite PRIMARY KEY (session_id, session_type) to {table_name}")
        sess.execute(text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (session_id, session_type)"))

        return True


def _revert_postgres(db: BaseDb, table_name: str) -> bool:
    """Revert PRIMARY KEY to (session_id) for PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

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
            return False

        pk_columns = _get_pk_columns_postgres(sess, db_schema, table_name)
        if "session_type" not in pk_columns:
            log_info(f"Table {table_name} does not have composite PK, skipping revert")
            return False

        pk_name = _get_pk_name_postgres(sess, db_schema, table_name)
        if pk_name:
            sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT {quote_db_identifier(db_type, pk_name)}"))

        sess.execute(text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (session_id)"))
        return True


# ---------------------------------------------------------------------------
# PostgreSQL (async)
# ---------------------------------------------------------------------------


async def _migrate_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    """Change PRIMARY KEY to (session_id, session_type) for async PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

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
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        pk_columns = await _get_pk_columns_async_postgres(sess, db_schema, table_name)
        if "session_type" in pk_columns:
            log_info(f"Table {table_name} already has composite PK (session_id, session_type), skipping")
            return False

        pk_name = await _get_pk_name_async_postgres(sess, db_schema, table_name)
        if pk_name:
            log_info(f"-- Dropping old PRIMARY KEY {pk_name} from {table_name}")
            await sess.execute(
                text(f"ALTER TABLE {full_table} DROP CONSTRAINT {quote_db_identifier(db_type, pk_name)}")
            )

        log_info(f"-- Adding composite PRIMARY KEY (session_id, session_type) to {table_name}")
        await sess.execute(text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (session_id, session_type)"))

        return True


async def _revert_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert PRIMARY KEY to (session_id) for async PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

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
            return False

        pk_columns = await _get_pk_columns_async_postgres(sess, db_schema, table_name)
        if "session_type" not in pk_columns:
            return False

        pk_name = await _get_pk_name_async_postgres(sess, db_schema, table_name)
        if pk_name:
            await sess.execute(
                text(f"ALTER TABLE {full_table} DROP CONSTRAINT {quote_db_identifier(db_type, pk_name)}")
            )

        await sess.execute(text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (session_id)"))
        return True


# ---------------------------------------------------------------------------
# MySQL (sync)
# ---------------------------------------------------------------------------


def _migrate_mysql(db: BaseDb, table_name: str) -> bool:
    """Change PRIMARY KEY to (session_id, session_type) for MySQL."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        result = sess.execute(text(f"SHOW TABLES LIKE '{table_name}'"))
        if not result.fetchone():
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        # Check current PK columns
        pk_result = sess.execute(text(f"SHOW KEYS FROM {quoted_table} WHERE Key_name = 'PRIMARY'"))
        pk_cols = {row[4] for row in pk_result.fetchall()}

        if "session_type" in pk_cols:
            log_info(f"Table {table_name} already has composite PK, skipping")
            return False

        log_info(f"-- Changing PRIMARY KEY to (session_id, session_type) on {table_name}")
        sess.execute(text(f"ALTER TABLE {quoted_table} DROP PRIMARY KEY, ADD PRIMARY KEY (session_id, session_type)"))
        return True


def _revert_mysql(db: BaseDb, table_name: str) -> bool:
    """Revert PRIMARY KEY to (session_id) for MySQL."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        result = sess.execute(text(f"SHOW TABLES LIKE '{table_name}'"))
        if not result.fetchone():
            return False

        pk_result = sess.execute(text(f"SHOW KEYS FROM {quoted_table} WHERE Key_name = 'PRIMARY'"))
        pk_cols = {row[4] for row in pk_result.fetchall()}

        if "session_type" not in pk_cols:
            return False

        sess.execute(text(f"ALTER TABLE {quoted_table} DROP PRIMARY KEY, ADD PRIMARY KEY (session_id)"))
        return True


# ---------------------------------------------------------------------------
# MySQL (async)
# ---------------------------------------------------------------------------


async def _migrate_async_mysql(db: AsyncBaseDb, table_name: str) -> bool:
    """Change PRIMARY KEY to (session_id, session_type) for async MySQL."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(text(f"SHOW TABLES LIKE '{table_name}'"))
        if not result.fetchone():
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False

        pk_result = await sess.execute(text(f"SHOW KEYS FROM {quoted_table} WHERE Key_name = 'PRIMARY'"))
        pk_cols = {row[4] for row in pk_result.fetchall()}

        if "session_type" in pk_cols:
            log_info(f"Table {table_name} already has composite PK, skipping")
            return False

        log_info(f"-- Changing PRIMARY KEY to (session_id, session_type) on {table_name}")
        await sess.execute(
            text(f"ALTER TABLE {quoted_table} DROP PRIMARY KEY, ADD PRIMARY KEY (session_id, session_type)")
        )
        return True


async def _revert_async_mysql(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert PRIMARY KEY to (session_id) for async MySQL."""
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(text(f"SHOW TABLES LIKE '{table_name}'"))
        if not result.fetchone():
            return False

        pk_result = await sess.execute(text(f"SHOW KEYS FROM {quoted_table} WHERE Key_name = 'PRIMARY'"))
        pk_cols = {row[4] for row in pk_result.fetchall()}

        if "session_type" not in pk_cols:
            return False

        await sess.execute(text(f"ALTER TABLE {quoted_table} DROP PRIMARY KEY, ADD PRIMARY KEY (session_id)"))
        return True


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_pk_columns_postgres(sess, db_schema: str, table_name: str) -> set:
    """Get the column names of the primary key for a PostgreSQL table."""
    result = sess.execute(
        text(
            "SELECT a.attname "
            "FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = :full_name::regclass AND i.indisprimary"
        ),
        {"full_name": f"{db_schema}.{table_name}"},
    )
    return {row[0] for row in result.fetchall()}


def _get_pk_name_postgres(sess, db_schema: str, table_name: str) -> str:
    """Get the name of the primary key constraint for a PostgreSQL table."""
    result = sess.execute(
        text("SELECT conname FROM pg_constraint WHERE conrelid = :full_name::regclass AND contype = 'p'"),
        {"full_name": f"{db_schema}.{table_name}"},
    )
    row = result.fetchone()
    return row[0] if row else ""


async def _get_pk_columns_async_postgres(sess, db_schema: str, table_name: str) -> set:
    """Get the column names of the primary key for an async PostgreSQL table."""
    result = await sess.execute(
        text(
            "SELECT a.attname "
            "FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = :full_name::regclass AND i.indisprimary"
        ),
        {"full_name": f"{db_schema}.{table_name}"},
    )
    return {row[0] for row in result.fetchall()}


async def _get_pk_name_async_postgres(sess, db_schema: str, table_name: str) -> str:
    """Get the name of the primary key constraint for an async PostgreSQL table."""
    result = await sess.execute(
        text("SELECT conname FROM pg_constraint WHERE conrelid = :full_name::regclass AND contype = 'p'"),
        {"full_name": f"{db_schema}.{table_name}"},
    )
    row = result.fetchone()
    return row[0] if row else ""
