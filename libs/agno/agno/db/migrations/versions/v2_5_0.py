"""Migration v2.5.0: add dedicated agno_replays table."""

from __future__ import annotations

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.utils.log import log_error, log_info

try:
    from sqlalchemy import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    db_type = type(db).__name__
    if table_type != "replays":
        return False

    try:
        if db_type in {"PostgresDb", "SqliteDb"}:
            db._get_table(table_type="replays", create_table_if_not_found=True)  # type: ignore[attr-defined]
            return True
        log_info(f"{db_type} does not support SQL replay migration. Skipping.")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.5.0 for {db_type} on table {table_name}: {e}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    db_type = type(db).__name__
    if table_type != "replays":
        return False

    try:
        if db_type in {"AsyncPostgresDb", "AsyncSqliteDb"}:
            await db._get_table(table_type="replays", create_table_if_not_found=True)  # type: ignore[attr-defined]
            return True
        log_info(f"{db_type} does not support SQL replay migration. Skipping.")
        return False
    except Exception as e:
        log_error(f"Error running async migration v2.5.0 for {db_type} on table {table_name}: {e}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    db_type = type(db).__name__
    if table_type != "replays":
        return False

    try:
        if db_type == "PostgresDb":
            quoted_schema = quote_db_identifier(db_type, db.db_schema)  # type: ignore[attr-defined]
            quoted_table = quote_db_identifier(db_type, table_name)
            with db.Session() as sess, sess.begin():  # type: ignore[attr-defined]
                sess.execute(text(f"DROP TABLE IF EXISTS {quoted_schema}.{quoted_table}"))
            return True
        if db_type == "SqliteDb":
            quoted_table = quote_db_identifier(db_type, table_name)
            with db.Session() as sess, sess.begin():  # type: ignore[attr-defined]
                sess.execute(text(f"DROP TABLE IF EXISTS {quoted_table}"))
            return True
        log_info(f"Down migration for replay table is not supported for {db_type}.")
        return False
    except Exception as e:
        log_error(f"Error reverting migration v2.5.0 for {db_type} on table {table_name}: {e}")
        raise


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    db_type = type(db).__name__
    if table_type != "replays":
        return False

    try:
        if db_type == "AsyncPostgresDb":
            quoted_schema = quote_db_identifier(db_type, db.db_schema)  # type: ignore[attr-defined]
            quoted_table = quote_db_identifier(db_type, table_name)
            async with db.async_session_factory() as sess, sess.begin():  # type: ignore[attr-defined]
                await sess.execute(text(f"DROP TABLE IF EXISTS {quoted_schema}.{quoted_table}"))
            return True
        if db_type == "AsyncSqliteDb":
            quoted_table = quote_db_identifier(db_type, table_name)
            async with db.async_session_factory() as sess, sess.begin():  # type: ignore[attr-defined]
                await sess.execute(text(f"DROP TABLE IF EXISTS {quoted_table}"))
            return True
        log_info(f"Async down migration for replay table is not supported for {db_type}.")
        return False
    except Exception as e:
        log_error(f"Error reverting async migration v2.5.0 for {db_type} on table {table_name}: {e}")
        raise
