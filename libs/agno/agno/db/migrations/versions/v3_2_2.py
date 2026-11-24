"""Migration v3.2.2: Add user_type to the user directory

Changes:
- Add the nullable user_type column to the authz users table, with its index

Existing rows keep a NULL user_type, which the directory reads as "end_user". A member of the
organization that owns the OS on os.agno.com becomes "org_user" on their next request with a
platform-signed token. The authz tables are only stored by the SQL backends that implement them
(PostgreSQL and SQLite), so every other backend has nothing to migrate.
"""

from typing import Any, List, Optional

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.utils.log import log_error, log_info

try:
    from sqlalchemy import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

TABLE_TYPE = "authz_users"
COLUMN = "user_type"


def _index_name(table_name: str) -> str:
    # The name table creation gives a column index, so a migrated table matches a new one
    return f"idx_{table_name}_{COLUMN}"


def _postgres_table(db: Any, table_name: str) -> str:
    db_type = type(db).__name__
    db_schema = db.db_schema or "public"
    return f"{quote_db_identifier(db_type, db_schema)}.{quote_db_identifier(db_type, table_name)}"


_PG_TABLE_EXISTS = text(
    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table)"
)
_PG_COLUMN_EXISTS = text(
    "SELECT 1 FROM information_schema.columns WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
)
_PG_INDEX_EXISTS = text(
    "SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND tablename = :table AND indexname = :index"
)


def _add_statements(db: Any, table_name: str, has_column: bool, has_index: bool, postgres: bool) -> List[Any]:
    """The statements that bring the table up to date, given what it already has."""
    full_table = _postgres_table(db, table_name) if postgres else table_name
    index = quote_db_identifier(type(db).__name__, _index_name(table_name)) if postgres else _index_name(table_name)
    statements = []
    if not has_column:
        statements.append(text(f"ALTER TABLE {full_table} ADD COLUMN {COLUMN} TEXT"))
    if not has_index:
        statements.append(text(f"CREATE INDEX {index} ON {full_table} ({COLUMN})"))
    return statements


def _drop_statements(db: Any, table_name: str, has_column: bool, postgres: bool) -> List[Any]:
    """The statements that remove the column and its index, given what the table has."""
    if not has_column:
        return []
    full_table = _postgres_table(db, table_name) if postgres else table_name
    if postgres:
        db_type = type(db).__name__
        db_schema = db.db_schema or "public"
        index = f"{quote_db_identifier(db_type, db_schema)}.{quote_db_identifier(db_type, _index_name(table_name))}"
    else:
        index = _index_name(table_name)
    # SQLite drops a column only once no index uses it
    return [text(f"DROP INDEX IF EXISTS {index}"), text(f"ALTER TABLE {full_table} DROP COLUMN {COLUMN}")]


def _pg_params(db: Any, table_name: str) -> dict:
    return {
        "schema": db.db_schema or "public",
        "table": table_name,
        "column": COLUMN,
        "index": _index_name(table_name),
    }


def _sqlite_state(sess: Any, table_name: str) -> Optional[tuple]:
    """(has_column, has_index) for a SQLite table, or None when the table does not exist."""
    exists = sess.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table"), {"table": table_name}
    ).scalar()
    if not exists:
        return None
    columns = {row[1] for row in sess.execute(text(f"PRAGMA table_info({table_name})")).fetchall()}
    indexes = {row[1] for row in sess.execute(text(f"PRAGMA index_list({table_name})")).fetchall()}
    return COLUMN in columns, _index_name(table_name) in indexes


async def _async_sqlite_state(sess: Any, table_name: str) -> Optional[tuple]:
    """Async version of :func:`_sqlite_state`."""
    exists = (
        await sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table"), {"table": table_name}
        )
    ).scalar()
    if not exists:
        return None
    columns = {row[1] for row in (await sess.execute(text(f"PRAGMA table_info({table_name})"))).fetchall()}
    indexes = {row[1] for row in (await sess.execute(text(f"PRAGMA index_list({table_name})"))).fetchall()}
    return COLUMN in columns, _index_name(table_name) in indexes


def _pg_state(sess: Any, db: Any, table_name: str) -> Optional[tuple]:
    """(has_column, has_index) for a PostgreSQL table, or None when the table does not exist."""
    params = _pg_params(db, table_name)
    if not sess.execute(_PG_TABLE_EXISTS, params).scalar():
        return None
    has_column = sess.execute(_PG_COLUMN_EXISTS, params).scalar() is not None
    has_index = sess.execute(_PG_INDEX_EXISTS, params).scalar() is not None
    return has_column, has_index


async def _async_pg_state(sess: Any, db: Any, table_name: str) -> Optional[tuple]:
    """Async version of :func:`_pg_state`."""
    params = _pg_params(db, table_name)
    if not (await sess.execute(_PG_TABLE_EXISTS, params)).scalar():
        return None
    has_column = (await sess.execute(_PG_COLUMN_EXISTS, params)).scalar() is not None
    has_index = (await sess.execute(_PG_INDEX_EXISTS, params)).scalar() is not None
    return has_column, has_index


def _run(db: BaseDb, table_name: str, adding: bool) -> bool:
    postgres = type(db).__name__ == "PostgresDb"
    with db.Session() as sess, sess.begin():  # type: ignore[attr-defined]
        state = _pg_state(sess, db, table_name) if postgres else _sqlite_state(sess, table_name)
        if state is None:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        has_column, has_index = state
        statements = (
            _add_statements(db, table_name, has_column, has_index, postgres)
            if adding
            else _drop_statements(db, table_name, has_column, postgres)
        )
        for statement in statements:
            log_info(f"-- {statement.text}")
            sess.execute(statement)
        return bool(statements)


async def _arun(db: AsyncBaseDb, table_name: str, adding: bool) -> bool:
    postgres = type(db).__name__ == "AsyncPostgresDb"
    async with db.async_session_factory() as sess, sess.begin():  # type: ignore[attr-defined]
        state = await (_async_pg_state(sess, db, table_name) if postgres else _async_sqlite_state(sess, table_name))
        if state is None:
            log_info(f"Table {table_name} does not exist, skipping migration")
            return False
        has_column, has_index = state
        statements = (
            _add_statements(db, table_name, has_column, has_index, postgres)
            if adding
            else _drop_statements(db, table_name, has_column, postgres)
        )
        for statement in statements:
            log_info(f"-- {statement.text}")
            await sess.execute(statement)
        return bool(statements)


_SYNC_BACKENDS = ("PostgresDb", "SqliteDb")
_ASYNC_BACKENDS = ("AsyncPostgresDb", "AsyncSqliteDb")


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Add user_type to the user directory. Returns True if the table changed."""
    if table_type != TABLE_TYPE or type(db).__name__ not in _SYNC_BACKENDS:
        return False
    try:
        return _run(db, table_name, adding=True)
    except Exception as e:
        log_error(f"Error running migration v3.2.2 for {type(db).__name__} on table {table_name}: {e}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async version of :func:`up`."""
    if table_type != TABLE_TYPE or type(db).__name__ not in _ASYNC_BACKENDS:
        return False
    try:
        return await _arun(db, table_name, adding=True)
    except Exception as e:
        log_error(f"Error running migration v3.2.2 for {type(db).__name__} on table {table_name}: {e}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Drop user_type from the user directory. Returns True if the table changed."""
    if table_type != TABLE_TYPE or type(db).__name__ not in _SYNC_BACKENDS:
        return False
    try:
        return _run(db, table_name, adding=False)
    except Exception as e:
        log_error(f"Error reverting migration v3.2.2 for {type(db).__name__} on table {table_name}: {e}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async version of :func:`down`."""
    if table_type != TABLE_TYPE or type(db).__name__ not in _ASYNC_BACKENDS:
        return False
    try:
        return await _arun(db, table_name, adding=False)
    except Exception as e:
        log_error(f"Error reverting migration v3.2.2 for {type(db).__name__} on table {table_name}: {e}")
        raise
