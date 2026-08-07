"""Migration v2.9.0: add server-owned Studio schedule provenance.

The fields are nullable so existing generic schedules remain generic. Schedule
names become database-unique, matching the scheduler API's existing contract
and closing check-then-insert races.
"""

from typing import Any

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.db.schemas.scheduler import STUDIO_SCHEDULE_MANAGED_BY
from agno.utils.log import log_info

try:
    from sqlalchemy import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


_PROVENANCE_COLUMNS = (
    "managed_by",
    "owner_actor_id",
    "target_type",
    "target_id",
    "created_by_run_id",
    "created_by_session_id",
    "updated_by_run_id",
    "updated_by_session_id",
)


def _duplicate_error() -> ValueError:
    return ValueError(
        "Cannot enforce unique schedule names because duplicate names already exist; "
        "remove or rename duplicate schedule rows, then retry the v2.9.0 migration."
    )


def _studio_data_error() -> ValueError:
    return ValueError(
        "Cannot remove Studio schedule provenance while Studio-managed schedules or their run history exist; "
        "delete those schedules and runs, then retry the v2.9.0 downgrade."
    )


def _studio_schedule_exists_query(db_type: str, table: str) -> Any:
    managed_by = quote_db_identifier(db_type, "managed_by")
    return text(f"SELECT 1 FROM {table} WHERE {managed_by} = :managed_by LIMIT 1")


def _assert_no_studio_schedule_data(session: Any, db_type: str, table: str) -> None:
    """Refuse to erase the only ownership boundary for Studio schedule data.

    Schedule runs are owned through their parent schedule and are deleted with
    it, so retaining a Studio schedule also retains every private run payload.
    This check must run under the same write lock as the schema change.
    """
    studio_schedule = session.execute(
        _studio_schedule_exists_query(db_type, table),
        {"managed_by": STUDIO_SCHEDULE_MANAGED_BY},
    ).scalar()
    if studio_schedule is not None:
        raise _studio_data_error()


async def _assert_no_studio_schedule_data_async(session: Any, db_type: str, table: str) -> None:
    studio_schedule = (
        await session.execute(
            _studio_schedule_exists_query(db_type, table),
            {"managed_by": STUDIO_SCHEDULE_MANAGED_BY},
        )
    ).scalar()
    if studio_schedule is not None:
        raise _studio_data_error()


def _is_sqlite(db: Any) -> bool:
    from agno.db.sqlite.sqlite import SqliteDb

    return isinstance(db, SqliteDb)


def _is_postgres(db: Any) -> bool:
    from agno.db.postgres.postgres import PostgresDb

    return isinstance(db, PostgresDb)


def _is_async_sqlite(db: Any) -> bool:
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    return isinstance(db, AsyncSqliteDb)


def _is_async_postgres(db: Any) -> bool:
    from agno.db.postgres.async_postgres import AsyncPostgresDb

    return isinstance(db, AsyncPostgresDb)


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Apply the schedule migration for synchronous SQLite and PostgreSQL."""
    if table_type != "schedules":
        return False
    db_type = type(db).__name__
    if _is_sqlite(db):
        return _migrate_sqlite(db, table_name)
    if _is_postgres(db):
        return _migrate_postgres(db, table_name)
    log_info(f"{db_type} does not require the v2.9.0 schedule migration")
    return False


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Apply the schedule migration for asynchronous SQLite and PostgreSQL."""
    if table_type != "schedules":
        return False
    db_type = type(db).__name__
    if _is_async_sqlite(db):
        return await _migrate_async_sqlite(db, table_name)
    if _is_async_postgres(db):
        return await _migrate_async_postgres(db, table_name)
    log_info(f"{db_type} does not require the v2.9.0 schedule migration")
    return False


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Remove schedule provenance only after Studio-managed data is gone."""
    if table_type != "schedules":
        return False
    if _is_sqlite(db):
        return _revert_sqlite(db, table_name)
    if _is_postgres(db):
        return _revert_postgres(db, table_name)
    return False


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Remove schedule provenance asynchronously only when no Studio data remains."""
    if table_type != "schedules":
        return False
    if _is_async_sqlite(db):
        return await _revert_async_sqlite(db, table_name)
    if _is_async_postgres(db):
        return await _revert_async_postgres(db, table_name)
    return False


def _sqlite_names(table_name: str) -> tuple[str, str, str, str]:
    table = quote_db_identifier("SqliteDb", table_name)
    unique_index = quote_db_identifier("SqliteDb", f"{table_name}_uq_name")
    managed_index = quote_db_identifier("SqliteDb", f"idx_{table_name}_managed_by")
    owner_index = quote_db_identifier("SqliteDb", f"idx_{table_name}_owner_actor_id")
    return table, unique_index, managed_index, owner_index


def _sqlite_table_exists(session: Any, table_name: str) -> bool:
    return (
        session.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()
        is not None
    )


def _migrate_sqlite(db: BaseDb, table_name: str) -> bool:
    table, unique_index, managed_index, owner_index = _sqlite_names(table_name)
    with db.Session() as session, session.begin():  # type: ignore[attr-defined]
        if not _sqlite_table_exists(session, table_name):
            return False
        duplicate = session.execute(text(f"SELECT 1 FROM {table} GROUP BY name HAVING COUNT(*) > 1 LIMIT 1")).scalar()
        if duplicate is not None:
            raise _duplicate_error()
        columns = {row[1] for row in session.execute(text(f"PRAGMA table_info({table})")).fetchall()}
        applied = False
        for column in _PROVENANCE_COLUMNS:
            if column not in columns:
                quoted_column = quote_db_identifier("SqliteDb", column)
                session.execute(text(f"ALTER TABLE {table} ADD COLUMN {quoted_column} TEXT"))
                applied = True
        index_names = {row[1] for row in session.execute(text(f"PRAGMA index_list({table})")).fetchall()}
        for index, column, unique in (
            (managed_index, "managed_by", False),
            (owner_index, "owner_actor_id", False),
            (unique_index, "name", True),
        ):
            raw_index = index.strip('"')
            if raw_index not in index_names:
                unique_sql = "UNIQUE " if unique else ""
                quoted_column = quote_db_identifier("SqliteDb", column)
                session.execute(text(f"CREATE {unique_sql}INDEX {index} ON {table} ({quoted_column})"))
                applied = True
        return applied


async def _migrate_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
    table, unique_index, managed_index, owner_index = _sqlite_names(table_name)
    async with db.async_session_factory() as session, session.begin():  # type: ignore[attr-defined]
        exists = (
            await session.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
                {"table_name": table_name},
            )
        ).scalar()
        if exists is None:
            return False
        duplicate = (
            await session.execute(text(f"SELECT 1 FROM {table} GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"))
        ).scalar()
        if duplicate is not None:
            raise _duplicate_error()
        columns = {row[1] for row in (await session.execute(text(f"PRAGMA table_info({table})"))).fetchall()}
        applied = False
        for column in _PROVENANCE_COLUMNS:
            if column not in columns:
                quoted_column = quote_db_identifier("AsyncSqliteDb", column)
                await session.execute(text(f"ALTER TABLE {table} ADD COLUMN {quoted_column} TEXT"))
                applied = True
        index_names = {row[1] for row in (await session.execute(text(f"PRAGMA index_list({table})"))).fetchall()}
        for index, column, unique in (
            (managed_index, "managed_by", False),
            (owner_index, "owner_actor_id", False),
            (unique_index, "name", True),
        ):
            raw_index = index.strip('"')
            if raw_index not in index_names:
                unique_sql = "UNIQUE " if unique else ""
                quoted_column = quote_db_identifier("AsyncSqliteDb", column)
                await session.execute(text(f"CREATE {unique_sql}INDEX {index} ON {table} ({quoted_column})"))
                applied = True
        return applied


def _postgres_names(db: Any, table_name: str) -> tuple[str, str, str, str]:
    db_type = type(db).__name__
    schema = quote_db_identifier(db_type, db.db_schema)
    table = quote_db_identifier(db_type, table_name)
    full_table = f"{schema}.{table}"
    unique_index = quote_db_identifier(db_type, f"{table_name}_uq_name")
    managed_index = quote_db_identifier(db_type, f"idx_{table_name}_managed_by")
    owner_index = quote_db_identifier(db_type, f"idx_{table_name}_owner_actor_id")
    return full_table, unique_index, managed_index, owner_index


def _migrate_postgres(db: BaseDb, table_name: str) -> bool:
    full_table, unique_index, managed_index, owner_index = _postgres_names(db, table_name)
    with db.Session() as session, session.begin():  # type: ignore[attr-defined]
        exists = session.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_schema=:schema AND table_name=:table"),
            {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
        ).scalar()
        if exists is None:
            return False
        duplicate = session.execute(
            text(f"SELECT 1 FROM {full_table} GROUP BY name HAVING COUNT(*) > 1 LIMIT 1")
        ).scalar()
        if duplicate is not None:
            raise _duplicate_error()
        for column in _PROVENANCE_COLUMNS:
            quoted_column = quote_db_identifier(type(db).__name__, column)
            session.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS {quoted_column} VARCHAR"))
        session.execute(text(f"CREATE INDEX IF NOT EXISTS {managed_index} ON {full_table} (managed_by)"))
        session.execute(text(f"CREATE INDEX IF NOT EXISTS {owner_index} ON {full_table} (owner_actor_id)"))
        session.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {unique_index} ON {full_table} (name)"))
        return True


async def _migrate_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    full_table, unique_index, managed_index, owner_index = _postgres_names(db, table_name)
    async with db.async_session_factory() as session, session.begin():  # type: ignore[attr-defined]
        exists = (
            await session.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_schema=:schema AND table_name=:table"),
                {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
            )
        ).scalar()
        if exists is None:
            return False
        duplicate = (
            await session.execute(text(f"SELECT 1 FROM {full_table} GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"))
        ).scalar()
        if duplicate is not None:
            raise _duplicate_error()
        for column in _PROVENANCE_COLUMNS:
            quoted_column = quote_db_identifier(type(db).__name__, column)
            await session.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS {quoted_column} VARCHAR"))
        await session.execute(text(f"CREATE INDEX IF NOT EXISTS {managed_index} ON {full_table} (managed_by)"))
        await session.execute(text(f"CREATE INDEX IF NOT EXISTS {owner_index} ON {full_table} (owner_actor_id)"))
        await session.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {unique_index} ON {full_table} (name)"))
        return True


def _revert_sqlite(db: BaseDb, table_name: str) -> bool:
    table, unique_index, managed_index, owner_index = _sqlite_names(table_name)
    with db.Session() as session:  # type: ignore[attr-defined]
        # Prevent a Studio schedule from being inserted between the safety
        # check and the DDL that removes its ownership marker.
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        try:
            if not _sqlite_table_exists(session, table_name):
                session.rollback()
                return False
            index_names = {row[1] for row in session.execute(text(f"PRAGMA index_list({table})")).fetchall()}
            columns = {row[1] for row in session.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            if "managed_by" in columns:
                _assert_no_studio_schedule_data(session, "SqliteDb", table)
            applied = False
            for index in (unique_index, managed_index, owner_index):
                if index.strip('"') in index_names:
                    session.execute(text(f"DROP INDEX IF EXISTS {index}"))
                    applied = True
            for column in reversed(_PROVENANCE_COLUMNS):
                if column in columns:
                    quoted_column = quote_db_identifier("SqliteDb", column)
                    session.execute(text(f"ALTER TABLE {table} DROP COLUMN {quoted_column}"))
                    applied = True
            session.commit()
            return applied
        except Exception:
            session.rollback()
            raise


async def _revert_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
    table, unique_index, managed_index, owner_index = _sqlite_names(table_name)
    async with db.async_session_factory() as session:  # type: ignore[attr-defined]
        await session.execute(text("BEGIN IMMEDIATE"))
        try:
            exists = (
                await session.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
                    {"table_name": table_name},
                )
            ).scalar()
            if exists is None:
                await session.rollback()
                return False
            index_names = {row[1] for row in (await session.execute(text(f"PRAGMA index_list({table})"))).fetchall()}
            columns = {row[1] for row in (await session.execute(text(f"PRAGMA table_info({table})"))).fetchall()}
            if "managed_by" in columns:
                await _assert_no_studio_schedule_data_async(session, "AsyncSqliteDb", table)
            applied = False
            for index in (unique_index, managed_index, owner_index):
                if index.strip('"') in index_names:
                    await session.execute(text(f"DROP INDEX IF EXISTS {index}"))
                    applied = True
            for column in reversed(_PROVENANCE_COLUMNS):
                if column in columns:
                    quoted_column = quote_db_identifier("AsyncSqliteDb", column)
                    await session.execute(text(f"ALTER TABLE {table} DROP COLUMN {quoted_column}"))
                    applied = True
            await session.commit()
            return applied
        except Exception:
            await session.rollback()
            raise


def _revert_postgres(db: BaseDb, table_name: str) -> bool:
    full_table, unique_index, managed_index, owner_index = _postgres_names(db, table_name)
    schema = full_table.rsplit(".", 1)[0]
    with db.Session() as session, session.begin():  # type: ignore[attr-defined]
        exists = session.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_schema=:schema AND table_name=:table"),
            {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
        ).scalar()
        if exists is None:
            return False
        session.execute(text(f"LOCK TABLE {full_table} IN ACCESS EXCLUSIVE MODE"))
        managed_by_exists = session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema=:schema AND table_name=:table AND column_name='managed_by'"
            ),
            {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
        ).scalar()
        if managed_by_exists is not None:
            _assert_no_studio_schedule_data(session, type(db).__name__, full_table)
        for index in (unique_index, managed_index, owner_index):
            session.execute(text(f"DROP INDEX IF EXISTS {schema}.{index}"))
        for column in reversed(_PROVENANCE_COLUMNS):
            quoted_column = quote_db_identifier(type(db).__name__, column)
            session.execute(text(f"ALTER TABLE {full_table} DROP COLUMN IF EXISTS {quoted_column}"))
        return True


async def _revert_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    full_table, unique_index, managed_index, owner_index = _postgres_names(db, table_name)
    schema = full_table.rsplit(".", 1)[0]
    async with db.async_session_factory() as session, session.begin():  # type: ignore[attr-defined]
        exists = (
            await session.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_schema=:schema AND table_name=:table"),
                {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
            )
        ).scalar()
        if exists is None:
            return False
        await session.execute(text(f"LOCK TABLE {full_table} IN ACCESS EXCLUSIVE MODE"))
        managed_by_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema=:schema AND table_name=:table AND column_name='managed_by'"
                ),
                {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
            )
        ).scalar()
        if managed_by_exists is not None:
            await _assert_no_studio_schedule_data_async(session, type(db).__name__, full_table)
        for index in (unique_index, managed_index, owner_index):
            await session.execute(text(f"DROP INDEX IF EXISTS {schema}.{index}"))
        for column in reversed(_PROVENANCE_COLUMNS):
            quoted_column = quote_db_identifier(type(db).__name__, column)
            await session.execute(text(f"ALTER TABLE {full_table} DROP COLUMN IF EXISTS {quoted_column}"))
        return True
