"""Migration v3.1.5: Bring Company Tasks tables created by v3.1.4 up to date

Changes:
- Add origin, routine_id, dedupe_key and metadata columns to the tasks table
- Add the uq_company_task_evidence unique constraint on (product_id, dedupe_key),
  which Routine evidence deduplication relies on for ON CONFLICT DO NOTHING

Company storage is only implemented for PostgreSQL and SQLite, so other adapters
have nothing to migrate. Every step checks the current shape first, so tables
created by v3.1.5 or later are left untouched.
"""

from typing import List, Set, Tuple

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.utils.log import log_error, log_info

try:
    from sqlalchemy import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


UNIQUE_CONSTRAINT_NAME = "uq_company_task_evidence"
# Marks an evidence unique constraint SQLite created with the table, under an internal name
_TABLE_CONSTRAINT = "<table constraint>"

# (column name, PostgreSQL type, SQLite type)
NEW_COLUMNS: List[Tuple[str, str, str]] = [
    ("origin", "VARCHAR", "VARCHAR"),
    ("routine_id", "VARCHAR", "VARCHAR"),
    ("dedupe_key", "VARCHAR", "VARCHAR"),
    ("metadata", "JSONB", "JSON"),
]


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Add the v3.1.5 Company Task columns and evidence unique constraint.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "tasks":
            return False

        if db_type == "PostgresDb":
            return _migrate_postgres(db, table_name)
        elif db_type == "SqliteDb":
            return _migrate_sqlite(db, table_name)
        else:
            log_info(f"{db_type} does not store Company Tasks, skipping migration")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.1.5 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Add the v3.1.5 Company Task columns and evidence unique constraint.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "tasks":
            return False

        if db_type == "AsyncPostgresDb":
            return await _migrate_async_postgres(db, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _migrate_async_sqlite(db, table_name)
        else:
            log_info(f"{db_type} does not store Company Tasks, skipping migration")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.1.5 for {db_type} on table {table_name}: {str(e)}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert: drop the evidence unique constraint and the v3.1.5 Company Task columns.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "tasks":
            return False

        if db_type == "PostgresDb":
            return _revert_postgres(db, table_name)
        elif db_type == "SqliteDb":
            return _revert_sqlite(db, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v3.1.5 for {db_type} on table {table_name}: {str(e)}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Revert: drop the evidence unique constraint and the v3.1.5 Company Task columns.

    Returns:
        bool: True if any migration was reverted, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "tasks":
            return False

        if db_type == "AsyncPostgresDb":
            return await _revert_async_postgres(db, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _revert_async_sqlite(db, table_name)
        else:
            log_info(f"Revert not implemented for {db_type}")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v3.1.5 for {db_type} on table {table_name} asynchronously: {str(e)}")
        raise


# ---------------------------------------------------------------------------
# Statement builders
#
# Each builder takes the table's current columns and index names and returns
# only the statements still needed, so sync and async paths share one plan.
# ---------------------------------------------------------------------------


def _postgres_full_table(db_type: str, db_schema: str, table_name: str) -> str:
    return f"{quote_db_identifier(db_type, db_schema)}.{quote_db_identifier(db_type, table_name)}"


def _postgres_up_statements(db_type: str, full_table: str, columns: Set[str], indexes: Set[str]) -> List[str]:
    statements = []
    for column, pg_type, _ in NEW_COLUMNS:
        if column not in columns:
            log_info(f"-- Adding {column} column to {full_table}")
            statements.append(f"ALTER TABLE {full_table} ADD COLUMN {quote_db_identifier(db_type, column)} {pg_type}")
    if UNIQUE_CONSTRAINT_NAME not in indexes:
        log_info(f"-- Adding unique constraint {UNIQUE_CONSTRAINT_NAME} on {full_table}")
        # Rows written before v3.1.5 have no dedupe_key, and NULLs never collide
        statements.append(
            f"ALTER TABLE {full_table} ADD CONSTRAINT {quote_db_identifier(db_type, UNIQUE_CONSTRAINT_NAME)} "
            "UNIQUE (product_id, dedupe_key)"
        )
    return statements


def _postgres_down_statements(db_type: str, full_table: str, columns: Set[str], indexes: Set[str]) -> List[str]:
    statements = []
    if UNIQUE_CONSTRAINT_NAME in indexes:
        log_info(f"-- Dropping unique constraint {UNIQUE_CONSTRAINT_NAME} from {full_table}")
        statements.append(
            f"ALTER TABLE {full_table} DROP CONSTRAINT {quote_db_identifier(db_type, UNIQUE_CONSTRAINT_NAME)}"
        )
    for column, _, _ in NEW_COLUMNS:
        if column in columns:
            log_info(f"-- Dropping {column} column from {full_table}")
            statements.append(f"ALTER TABLE {full_table} DROP COLUMN {quote_db_identifier(db_type, column)}")
    return statements


def _sqlite_up_statements(table_name: str, columns: Set[str], indexes: Set[str]) -> List[str]:
    quoted_table = quote_db_identifier("SqliteDb", table_name)
    statements = []
    for column, _, sqlite_type in NEW_COLUMNS:
        if column not in columns:
            log_info(f"-- Adding {column} column to {table_name}")
            statements.append(
                f"ALTER TABLE {quoted_table} ADD COLUMN {quote_db_identifier('SqliteDb', column)} {sqlite_type}"
            )
    if UNIQUE_CONSTRAINT_NAME not in indexes and _TABLE_CONSTRAINT not in indexes:
        # SQLite cannot add a table constraint after creation; a unique index under
        # the same name enforces the same rule and satisfies ON CONFLICT inference.
        log_info(f"-- Adding unique index {UNIQUE_CONSTRAINT_NAME} on {table_name}")
        statements.append(
            f"CREATE UNIQUE INDEX {quote_db_identifier('SqliteDb', UNIQUE_CONSTRAINT_NAME)} "
            f"ON {quoted_table} (product_id, dedupe_key)"
        )
    return statements


def _sqlite_down_statements(table_name: str, columns: Set[str], indexes: Set[str]) -> List[str]:
    quoted_table = quote_db_identifier("SqliteDb", table_name)
    if _TABLE_CONSTRAINT in indexes:
        # SQLite cannot drop a table constraint or the columns it names without rebuilding the table
        log_info(f"Table {table_name} was created with the v3.1.5 shape, skipping SQLite revert")
        return []
    statements = []
    if UNIQUE_CONSTRAINT_NAME in indexes:
        log_info(f"-- Dropping unique index {UNIQUE_CONSTRAINT_NAME} from {table_name}")
        statements.append(f"DROP INDEX {quote_db_identifier('SqliteDb', UNIQUE_CONSTRAINT_NAME)}")
    for column, _, _ in NEW_COLUMNS:
        if column in columns:
            # Requires SQLite 3.35+
            log_info(f"-- Dropping {column} column from {table_name}")
            statements.append(f"ALTER TABLE {quoted_table} DROP COLUMN {quote_db_identifier('SqliteDb', column)}")
    return statements


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

_PG_TABLE_EXISTS = text(
    "SELECT EXISTS (  SELECT FROM information_schema.tables  WHERE table_schema = :schema AND table_name = :table_name)"
)
_PG_COLUMNS = text(
    "SELECT column_name FROM information_schema.columns WHERE table_schema = :schema AND table_name = :table_name"
)
# A UNIQUE constraint is backed by an index of the same name
_PG_INDEXES = text("SELECT indexname FROM pg_indexes WHERE schemaname = :schema AND tablename = :table_name")

_SQLITE_TABLE_EXISTS = text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name")


def _pg_shape(sess, db_schema: str, table_name: str) -> Tuple[bool, Set[str], Set[str]]:
    params = {"schema": db_schema, "table_name": table_name}
    if not sess.execute(_PG_TABLE_EXISTS, params).scalar():
        return False, set(), set()
    columns = {row[0] for row in sess.execute(_PG_COLUMNS, params).fetchall()}
    indexes = {row[0] for row in sess.execute(_PG_INDEXES, params).fetchall()}
    return True, columns, indexes


async def _async_pg_shape(sess, db_schema: str, table_name: str) -> Tuple[bool, Set[str], Set[str]]:
    params = {"schema": db_schema, "table_name": table_name}
    if not (await sess.execute(_PG_TABLE_EXISTS, params)).scalar():
        return False, set(), set()
    columns = {row[0] for row in (await sess.execute(_PG_COLUMNS, params)).fetchall()}
    indexes = {row[0] for row in (await sess.execute(_PG_INDEXES, params)).fetchall()}
    return True, columns, indexes


# A table created with the constraint lists it as an unnamed sqlite_autoindex_*, so
# SQLite matches it by the columns it covers. The constraint name is reported only
# for the unique index this migration creates, which is the one a revert can drop.
_EVIDENCE_COLUMNS = ["product_id", "dedupe_key"]


def _sqlite_shape(sess, table_name: str) -> Tuple[bool, Set[str], Set[str]]:
    if not sess.execute(_SQLITE_TABLE_EXISTS, {"table_name": table_name}).scalar():
        return False, set(), set()
    quoted_table = quote_db_identifier("SqliteDb", table_name)
    columns = {col[1] for col in sess.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()}
    indexes = set()
    for idx in sess.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall():
        name, unique = idx[1], idx[2]
        if not unique:
            continue
        quoted_index = quote_db_identifier("SqliteDb", name)
        covered = [col[2] for col in sess.execute(text(f"PRAGMA index_info({quoted_index})")).fetchall()]
        if covered == _EVIDENCE_COLUMNS:
            indexes.add(name if name == UNIQUE_CONSTRAINT_NAME else _TABLE_CONSTRAINT)
    return True, columns, indexes


async def _async_sqlite_shape(sess, table_name: str) -> Tuple[bool, Set[str], Set[str]]:
    if not (await sess.execute(_SQLITE_TABLE_EXISTS, {"table_name": table_name})).scalar():
        return False, set(), set()
    quoted_table = quote_db_identifier("SqliteDb", table_name)
    columns = {col[1] for col in (await sess.execute(text(f"PRAGMA table_info({quoted_table})"))).fetchall()}
    indexes = set()
    for idx in (await sess.execute(text(f"PRAGMA index_list({quoted_table})"))).fetchall():
        name, unique = idx[1], idx[2]
        if not unique:
            continue
        quoted_index = quote_db_identifier("SqliteDb", name)
        covered = [col[2] for col in (await sess.execute(text(f"PRAGMA index_info({quoted_index})"))).fetchall()]
        if covered == _EVIDENCE_COLUMNS:
            indexes.add(name if name == UNIQUE_CONSTRAINT_NAME else _TABLE_CONSTRAINT)
    return True, columns, indexes


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _migrate_postgres(db: BaseDb, table_name: str, revert: bool = False) -> bool:
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    full_table = _postgres_full_table(db_type, db_schema, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        exists, columns, indexes = _pg_shape(sess, db_schema, table_name)
        if not exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        build = _postgres_down_statements if revert else _postgres_up_statements
        statements = build(db_type, full_table, columns, indexes)
        for statement in statements:
            sess.execute(text(statement))
        return bool(statements)


async def _migrate_async_postgres(db: AsyncBaseDb, table_name: str, revert: bool = False) -> bool:
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    full_table = _postgres_full_table(db_type, db_schema, table_name)

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        exists, columns, indexes = await _async_pg_shape(sess, db_schema, table_name)
        if not exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        build = _postgres_down_statements if revert else _postgres_up_statements
        statements = build(db_type, full_table, columns, indexes)
        for statement in statements:
            await sess.execute(text(statement))
        return bool(statements)


def _revert_postgres(db: BaseDb, table_name: str) -> bool:
    return _migrate_postgres(db, table_name, revert=True)


async def _revert_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    return await _migrate_async_postgres(db, table_name, revert=True)


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def _migrate_sqlite(db: BaseDb, table_name: str, revert: bool = False) -> bool:
    with db.Session() as sess, sess.begin():  # type: ignore
        exists, columns, indexes = _sqlite_shape(sess, table_name)
        if not exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        build = _sqlite_down_statements if revert else _sqlite_up_statements
        statements = build(table_name, columns, indexes)
        for statement in statements:
            sess.execute(text(statement))
        return bool(statements)


async def _migrate_async_sqlite(db: AsyncBaseDb, table_name: str, revert: bool = False) -> bool:
    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        exists, columns, indexes = await _async_sqlite_shape(sess, table_name)
        if not exists:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        build = _sqlite_down_statements if revert else _sqlite_up_statements
        statements = build(table_name, columns, indexes)
        for statement in statements:
            await sess.execute(text(statement))
        return bool(statements)


def _revert_sqlite(db: BaseDb, table_name: str) -> bool:
    return _migrate_sqlite(db, table_name, revert=True)


async def _revert_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
    return await _migrate_async_sqlite(db, table_name, revert=True)
