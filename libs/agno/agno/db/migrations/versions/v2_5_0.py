"""Migration v2.5.0: Add primary key to session_id across SQL backends

Changes:
- Add PRIMARY KEY constraint on session_id for existing sessions tables
- Drop the redundant uq_session_id UNIQUE constraint
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
    Add PRIMARY KEY on session_id and drop redundant uq_session_id UNIQUE constraint.

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
        elif db_type == "SingleStoreDb":
            return _migrate_singlestore(db, table_name)
        elif db_type == "SqliteDb":
            # SQLite already has session_id as primary key
            return False
        else:
            log_info(f"{db_type} does not require schema migrations")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.5.0 for {db_type} on table {table_name}: {e}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Add PRIMARY KEY on session_id and drop redundant uq_session_id UNIQUE constraint.

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
        elif db_type == "AsyncSqliteDb":
            # SQLite already has session_id as primary key
            return False
        else:
            log_info(f"{db_type} does not require schema migrations")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.5.0 for {db_type} on table {table_name}: {e}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert: drop PRIMARY KEY on session_id and re-add uq_session_id UNIQUE constraint.

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
        elif db_type == "SingleStoreDb":
            return _revert_singlestore(db, table_name)
        elif db_type == "SqliteDb":
            return False
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v2.5.0 for {db_type} on table {table_name}: {e}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert: drop PRIMARY KEY on session_id and re-add uq_session_id UNIQUE constraint.

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
        elif db_type == "AsyncSqliteDb":
            return False
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v2.5.0 for {db_type} on table {table_name} asynchronously: {e}")
        raise


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _has_constraint(
    sess, db_schema: str, table_name: str, constraint_type: str, constraint_name: str | None = None
) -> bool:
    """Check if a constraint exists on a table.

    Args:
        sess: SQLAlchemy session.
        db_schema: Database schema name.
        table_name: Table name.
        constraint_type: Constraint type (e.g. 'PRIMARY KEY', 'UNIQUE').
        constraint_name: Optional constraint name. When None, checks by type only.
    """
    query = (
        "SELECT 1 FROM information_schema.table_constraints "
        "WHERE table_schema = :schema AND table_name = :table "
        "AND constraint_type = :ctype"
    )
    params: dict = {"schema": db_schema, "table": table_name, "ctype": constraint_type}
    if constraint_name is not None:
        query += " AND constraint_name = :constraint"
        params["constraint"] = constraint_name
    result = sess.execute(text(query), params)
    return result.scalar() is not None


def _validate_session_data(sess, full_table: str, table_name: str, db_type: str) -> bool:
    """Check for NULL or duplicate session_id values that would prevent adding a PRIMARY KEY.

    Returns:
        bool: True if data is valid for PK, False if issues were found.
    """
    # Check for NULL session_id values
    null_count = sess.execute(text(f"SELECT COUNT(*) FROM {full_table} WHERE session_id IS NULL")).scalar() or 0
    if null_count > 0:
        log_warning(
            f"Cannot add PRIMARY KEY to {table_name}: found {null_count} rows with NULL session_id. "
            f"Fix with: DELETE FROM {full_table} WHERE session_id IS NULL"
        )
        return False

    # Check for duplicate session_id values
    dup_count = (
        sess.execute(
            text(
                f"SELECT COUNT(*) FROM (SELECT session_id FROM {full_table} GROUP BY session_id HAVING COUNT(*) > 1) t"
            )
        ).scalar()
        or 0
    )
    if dup_count > 0:
        examples = sess.execute(
            text(f"SELECT session_id FROM {full_table} GROUP BY session_id HAVING COUNT(*) > 1 LIMIT 5")
        ).fetchall()
        dup_ids = [row[0] for row in examples]
        log_warning(
            f"Cannot add PRIMARY KEY to {table_name}: found {dup_count} duplicate session_id values. "
            f"Examples: {dup_ids}. "
            f"Fix by removing duplicate rows before retrying the migration."
        )
        return False

    return True


async def _async_validate_session_data(sess, full_table: str, table_name: str, db_type: str) -> bool:
    """Async version: check for NULL or duplicate session_id values.

    Returns:
        bool: True if data is valid for PK, False if issues were found.
    """
    # Check for NULL session_id values
    result = await sess.execute(text(f"SELECT COUNT(*) FROM {full_table} WHERE session_id IS NULL"))
    null_count = result.scalar() or 0
    if null_count > 0:
        log_warning(
            f"Cannot add PRIMARY KEY to {table_name}: found {null_count} rows with NULL session_id. "
            f"Fix with: DELETE FROM {full_table} WHERE session_id IS NULL"
        )
        return False

    # Check for duplicate session_id values
    result = await sess.execute(
        text(f"SELECT COUNT(*) FROM (SELECT session_id FROM {full_table} GROUP BY session_id HAVING COUNT(*) > 1) t")
    )
    dup_count = result.scalar() or 0
    if dup_count > 0:
        result = await sess.execute(
            text(f"SELECT session_id FROM {full_table} GROUP BY session_id HAVING COUNT(*) > 1 LIMIT 5")
        )
        examples = result.fetchall()
        dup_ids = [row[0] for row in examples]
        log_warning(
            f"Cannot add PRIMARY KEY to {table_name}: found {dup_count} duplicate session_id values. "
            f"Examples: {dup_ids}. "
            f"Fix by removing duplicate rows before retrying the migration."
        )
        return False

    return True


def _migrate_postgres(db: BaseDb, table_name: str) -> bool:
    """Add PRIMARY KEY on session_id and drop uq_session_id for PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        # Check if PK already exists
        has_pk = _has_constraint(sess, db_schema, table_name, "PRIMARY KEY")
        if not has_pk:
            if not _validate_session_data(sess, full_table, table_name, db_type):
                return False
            log_info(f"-- Adding PRIMARY KEY on session_id to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (session_id)"))
            applied = True

        # Drop the old unique constraint if it exists
        has_uq = _has_constraint(sess, db_schema, table_name, "UNIQUE", uq_name)
        if has_uq:
            log_info(f"-- Dropping redundant UNIQUE constraint {uq_name} from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT {quote_db_identifier(db_type, uq_name)}"))
            applied = True

        return applied


async def _migrate_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    """Add PRIMARY KEY on session_id and drop uq_session_id for async PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        # Check if PK already exists
        result = await sess.execute(
            text(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND constraint_type = 'PRIMARY KEY'"
            ),
            {"schema": db_schema, "table": table_name},
        )
        has_pk = result.scalar() is not None
        if not has_pk:
            if not await _async_validate_session_data(sess, full_table, table_name, db_type):
                return False
            log_info(f"-- Adding PRIMARY KEY on session_id to {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (session_id)"))
            applied = True

        # Drop the old unique constraint if it exists
        result = await sess.execute(
            text(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND constraint_name = :constraint AND constraint_type = 'UNIQUE'"
            ),
            {"schema": db_schema, "table": table_name, "constraint": uq_name},
        )
        has_uq = result.scalar() is not None
        if has_uq:
            log_info(f"-- Dropping redundant UNIQUE constraint {uq_name} from {table_name}")
            await sess.execute(
                text(f"ALTER TABLE {full_table} DROP CONSTRAINT {quote_db_identifier(db_type, uq_name)}")
            )
            applied = True

        return applied


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------


def _migrate_mysql(db: BaseDb, table_name: str) -> bool:
    """Add PRIMARY KEY on session_id and drop uq_session_id for MySQL."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        # Check if PK already exists
        pk_exists = sess.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                "AND CONSTRAINT_TYPE = 'PRIMARY KEY'"
            ),
            {"schema": db_schema, "table": table_name},
        ).scalar()

        if not pk_exists:
            if not _validate_session_data(sess, full_table, table_name, db_type):
                return False
            log_info(f"-- Adding PRIMARY KEY on session_id to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (`session_id`)"))
            applied = True

        # Drop the old unique constraint if it exists
        uq_exists = sess.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                "AND CONSTRAINT_NAME = :constraint AND CONSTRAINT_TYPE = 'UNIQUE'"
            ),
            {"schema": db_schema, "table": table_name, "constraint": uq_name},
        ).scalar()

        if uq_exists:
            log_info(f"-- Dropping redundant UNIQUE constraint {uq_name} from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP INDEX {quote_db_identifier(db_type, uq_name)}"))
            applied = True

        return applied


async def _migrate_async_mysql(db: AsyncBaseDb, table_name: str) -> bool:
    """Add PRIMARY KEY on session_id and drop uq_session_id for async MySQL."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        pk_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                    "AND CONSTRAINT_TYPE = 'PRIMARY KEY'"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).scalar()

        if not pk_exists:
            if not await _async_validate_session_data(sess, full_table, table_name, db_type):
                return False
            log_info(f"-- Adding PRIMARY KEY on session_id to {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (`session_id`)"))
            applied = True

        uq_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                    "AND CONSTRAINT_NAME = :constraint AND CONSTRAINT_TYPE = 'UNIQUE'"
                ),
                {"schema": db_schema, "table": table_name, "constraint": uq_name},
            )
        ).scalar()

        if uq_exists:
            log_info(f"-- Dropping redundant UNIQUE constraint {uq_name} from {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} DROP INDEX {quote_db_identifier(db_type, uq_name)}"))
            applied = True

        return applied


# ---------------------------------------------------------------------------
# SingleStore
# ---------------------------------------------------------------------------


def _migrate_singlestore(db: BaseDb, table_name: str) -> bool:
    """Add PRIMARY KEY on session_id and drop uq_session_id for SingleStore."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        # Check if PK already exists
        pk_exists = sess.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                "AND CONSTRAINT_TYPE = 'PRIMARY KEY'"
            ),
            {"schema": db_schema, "table": table_name},
        ).scalar()

        if not pk_exists:
            if not _validate_session_data(sess, full_table, table_name, db_type):
                return False
            log_info(f"-- Adding PRIMARY KEY on session_id to {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (`session_id`)"))
            applied = True

        # Drop the old unique constraint if it exists
        uq_exists = sess.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                "AND CONSTRAINT_NAME = :constraint AND CONSTRAINT_TYPE = 'UNIQUE'"
            ),
            {"schema": db_schema, "table": table_name, "constraint": uq_name},
        ).scalar()

        if uq_exists:
            log_info(f"-- Dropping redundant UNIQUE constraint {uq_name} from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP INDEX {quote_db_identifier(db_type, uq_name)}"))
            applied = True

        return applied


# ---------------------------------------------------------------------------
# Revert functions
# ---------------------------------------------------------------------------


def _revert_postgres(db: BaseDb, table_name: str) -> bool:
    """Revert: drop PK and re-add UNIQUE constraint for PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        # Re-add unique constraint if missing
        has_uq = _has_constraint(sess, db_schema, table_name, "UNIQUE", uq_name)
        if not has_uq:
            log_info(f"-- Re-adding UNIQUE constraint {uq_name} to {table_name}")
            sess.execute(
                text(
                    f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, uq_name)} UNIQUE (session_id)"
                )
            )
            applied = True

        # Drop primary key if it exists
        pk_result = sess.execute(
            text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND constraint_type = 'PRIMARY KEY'"
            ),
            {"schema": db_schema, "table": table_name},
        )
        pk_row = pk_result.fetchone()
        if pk_row is not None:
            pk_name = pk_row[0]
            log_info(f"-- Dropping PRIMARY KEY {pk_name} from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT {quote_db_identifier(db_type, pk_name)}"))
            applied = True

        return applied


async def _revert_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert: drop PK and re-add UNIQUE constraint for async PostgreSQL."""
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        # Re-add unique constraint if missing
        result = await sess.execute(
            text(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND constraint_name = :constraint AND constraint_type = 'UNIQUE'"
            ),
            {"schema": db_schema, "table": table_name, "constraint": uq_name},
        )
        has_uq = result.scalar() is not None
        if not has_uq:
            log_info(f"-- Re-adding UNIQUE constraint {uq_name} to {table_name}")
            await sess.execute(
                text(
                    f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, uq_name)} UNIQUE (session_id)"
                )
            )
            applied = True

        # Drop primary key if it exists
        result = await sess.execute(
            text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND constraint_type = 'PRIMARY KEY'"
            ),
            {"schema": db_schema, "table": table_name},
        )
        pk_row = result.fetchone()
        if pk_row is not None:
            pk_name = pk_row[0]
            log_info(f"-- Dropping PRIMARY KEY {pk_name} from {table_name}")
            await sess.execute(
                text(f"ALTER TABLE {full_table} DROP CONSTRAINT {quote_db_identifier(db_type, pk_name)}")
            )
            applied = True

        return applied


def _revert_mysql(db: BaseDb, table_name: str) -> bool:
    """Revert: drop PK and re-add UNIQUE constraint for MySQL."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        # Re-add unique constraint if missing
        uq_exists = sess.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                "AND CONSTRAINT_NAME = :constraint AND CONSTRAINT_TYPE = 'UNIQUE'"
            ),
            {"schema": db_schema, "table": table_name, "constraint": uq_name},
        ).scalar()

        if not uq_exists:
            log_info(f"-- Re-adding UNIQUE constraint {uq_name} to {table_name}")
            sess.execute(
                text(
                    f"ALTER TABLE {full_table} ADD UNIQUE INDEX {quote_db_identifier(db_type, uq_name)} (`session_id`)"
                )
            )
            applied = True

        # Drop PK if it exists
        pk_exists = sess.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                "AND CONSTRAINT_TYPE = 'PRIMARY KEY'"
            ),
            {"schema": db_schema, "table": table_name},
        ).scalar()

        if pk_exists:
            log_info(f"-- Dropping PRIMARY KEY from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP PRIMARY KEY"))
            applied = True

        return applied


async def _revert_async_mysql(db: AsyncBaseDb, table_name: str) -> bool:
    """Revert: drop PK and re-add UNIQUE constraint for async MySQL."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        uq_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                    "AND CONSTRAINT_NAME = :constraint AND CONSTRAINT_TYPE = 'UNIQUE'"
                ),
                {"schema": db_schema, "table": table_name, "constraint": uq_name},
            )
        ).scalar()

        if not uq_exists:
            log_info(f"-- Re-adding UNIQUE constraint {uq_name} to {table_name}")
            await sess.execute(
                text(
                    f"ALTER TABLE {full_table} ADD UNIQUE INDEX {quote_db_identifier(db_type, uq_name)} (`session_id`)"
                )
            )
            applied = True

        pk_exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                    "AND CONSTRAINT_TYPE = 'PRIMARY KEY'"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).scalar()

        if pk_exists:
            log_info(f"-- Dropping PRIMARY KEY from {table_name}")
            await sess.execute(text(f"ALTER TABLE {full_table} DROP PRIMARY KEY"))
            applied = True

        return applied


def _revert_singlestore(db: BaseDb, table_name: str) -> bool:
    """Revert: drop PK and re-add UNIQUE constraint for SingleStore."""
    db_schema = db.db_schema or "agno"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"
    uq_name = f"{table_name}_uq_session_id"

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

        # Re-add unique constraint if missing
        uq_exists = sess.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                "AND CONSTRAINT_NAME = :constraint AND CONSTRAINT_TYPE = 'UNIQUE'"
            ),
            {"schema": db_schema, "table": table_name, "constraint": uq_name},
        ).scalar()

        if not uq_exists:
            log_info(f"-- Re-adding UNIQUE constraint {uq_name} to {table_name}")
            sess.execute(
                text(
                    f"ALTER TABLE {full_table} ADD UNIQUE INDEX {quote_db_identifier(db_type, uq_name)} (`session_id`)"
                )
            )
            applied = True

        # Drop PK if it exists
        pk_exists = sess.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table "
                "AND CONSTRAINT_TYPE = 'PRIMARY KEY'"
            ),
            {"schema": db_schema, "table": table_name},
        ).scalar()

        if pk_exists:
            log_info(f"-- Dropping PRIMARY KEY from {table_name}")
            sess.execute(text(f"ALTER TABLE {full_table} DROP PRIMARY KEY"))
            applied = True

        return applied
