"""Migration v2.9.0: add Studio provenance and durable manual triggers.

Generic schedule names stay globally unique within the generic surface. Studio
names occupy a separate actor-scoped namespace, so a private Studio record is
neither a name oracle nor a collision for an unrelated actor.
"""

import re
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
_V2_9_COLUMNS = (*_PROVENANCE_COLUMNS, "pending_trigger_count", "manual_trigger_claimed")
_LEGACY_SQLITE_COLUMNS = (
    "id",
    "name",
    "description",
    "method",
    "endpoint",
    "payload",
    "cron_expr",
    "timezone",
    "timeout_seconds",
    "max_retries",
    "retry_delay_seconds",
    "enabled",
    "next_run_at",
    "locked_by",
    "locked_at",
    "created_at",
    "updated_at",
)


def _duplicate_error() -> ValueError:
    return ValueError(
        "Cannot enforce scoped unique schedule names because duplicates already exist; "
        "remove or rename duplicate schedule rows, then retry the v2.9.0 migration."
    )


def _studio_data_error() -> ValueError:
    return ValueError(
        "Cannot remove Studio schedule provenance while Studio-managed schedules or their run history exist; "
        "delete those schedules and runs, then retry the v2.9.0 downgrade."
    )


def _pending_trigger_error() -> ValueError:
    return ValueError(
        "Cannot remove durable schedule triggers while pending or claimed manual triggers exist; "
        "allow the scheduler to consume them, then retry the v2.9.0 downgrade."
    )


def _sqlite_schema_error(schema_objects: list[str]) -> ValueError:
    details = ", ".join(sorted(schema_objects))
    return ValueError(
        "Cannot safely rebuild the SQLite schedule table because it contains caller-owned or "
        f"unrecognized schema: {details}. Remove or migrate that schema explicitly, then retry the v2.9.0 downgrade."
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


def _assert_no_pending_triggers(
    session: Any,
    table: str,
    *,
    has_pending_count: bool,
    has_claimed_marker: bool,
) -> None:
    predicates = []
    if has_pending_count:
        predicates.append("pending_trigger_count > 0")
    if has_claimed_marker:
        predicates.append("manual_trigger_claimed = TRUE")
    if not predicates:
        return
    pending = session.execute(text(f"SELECT 1 FROM {table} WHERE {' OR '.join(predicates)} LIMIT 1")).scalar()
    if pending is not None:
        raise _pending_trigger_error()


async def _assert_no_pending_triggers_async(
    session: Any,
    table: str,
    *,
    has_pending_count: bool,
    has_claimed_marker: bool,
) -> None:
    predicates = []
    if has_pending_count:
        predicates.append("pending_trigger_count > 0")
    if has_claimed_marker:
        predicates.append("manual_trigger_claimed = TRUE")
    if not predicates:
        return
    pending = (await session.execute(text(f"SELECT 1 FROM {table} WHERE {' OR '.join(predicates)} LIMIT 1"))).scalar()
    if pending is not None:
        raise _pending_trigger_error()


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


def _index_names(db_type: str, table_name: str) -> dict[str, str]:
    return {
        "legacy": quote_db_identifier(db_type, f"{table_name}_uq_name"),
        "generic": quote_db_identifier(db_type, f"{table_name}_uq_generic_name"),
        "studio": quote_db_identifier(db_type, f"{table_name}_uq_studio_owner_name"),
        "managed": quote_db_identifier(db_type, f"idx_{table_name}_managed_by"),
        "owner": quote_db_identifier(db_type, f"idx_{table_name}_owner_actor_id"),
    }


def _sqlite_names(table_name: str) -> tuple[str, dict[str, str]]:
    return quote_db_identifier("SqliteDb", table_name), _index_names("SqliteDb", table_name)


def _sqlite_legacy_indexes(table_name: str) -> tuple[str, ...]:
    return (
        f"CREATE INDEX {quote_db_identifier('SqliteDb', f'idx_{table_name}_name')} "
        f"ON {quote_db_identifier('SqliteDb', table_name)} (name)",
        f"CREATE INDEX {quote_db_identifier('SqliteDb', f'idx_{table_name}_next_run_at')} "
        f"ON {quote_db_identifier('SqliteDb', table_name)} (next_run_at)",
        f"CREATE INDEX {quote_db_identifier('SqliteDb', f'idx_{table_name}_created_at')} "
        f"ON {quote_db_identifier('SqliteDb', table_name)} (created_at)",
        f"CREATE INDEX {quote_db_identifier('SqliteDb', f'idx_{table_name}_enabled_next_run_at')} "
        f"ON {quote_db_identifier('SqliteDb', table_name)} (enabled, next_run_at)",
    )


def _sqlite_split_table_definitions(definitions: str) -> list[str]:
    """Split a CREATE TABLE body without splitting nested expressions."""
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(definitions):
        char = definitions[index]
        if quote is not None:
            if quote == "[":
                if char == "]":
                    quote = None
            elif char == quote:
                if index + 1 < len(definitions) and definitions[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in ("'", '"', "`", "["):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(definitions[start:index].strip())
            start = index + 1
        index += 1
    parts.append(definitions[start:].strip())
    return [part for part in parts if part]


def _sqlite_definition_name(definition: str) -> str:
    match = re.match(r'^\s*(?:"((?:""|[^"])*)"|`((?:``|[^`])*)`|\[([^]]+)\]|([^\s]+))', definition)
    if match is None:
        return ""
    for value in match.groups():
        if value is not None:
            return value.replace('""', '"').replace("``", "`")
    return ""


def _sqlite_legacy_table_sql(source_sql: str, temporary_table_name: str) -> str:
    """Remove only v2.9 columns while retaining the legacy table definition."""
    open_paren = source_sql.find("(")
    if open_paren < 0:
        raise _sqlite_schema_error(["unreadable table definition"])

    depth = 0
    quote: str | None = None
    close_paren = -1
    index = open_paren
    while index < len(source_sql):
        char = source_sql[index]
        if quote is not None:
            if quote == "[":
                if char == "]":
                    quote = None
            elif char == quote:
                if index + 1 < len(source_sql) and source_sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in ("'", '"', "`", "["):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
        index += 1
    if close_paren < 0:
        raise _sqlite_schema_error(["unreadable table definition"])

    definitions = _sqlite_split_table_definitions(source_sql[open_paren + 1 : close_paren])
    legacy_definitions = [
        definition for definition in definitions if _sqlite_definition_name(definition) not in _V2_9_COLUMNS
    ]
    if len(definitions) - len(legacy_definitions) != len(
        {_sqlite_definition_name(definition) for definition in definitions}.intersection(_V2_9_COLUMNS)
    ):
        raise _sqlite_schema_error(["ambiguous v2.9 column definitions"])

    temporary_table = quote_db_identifier("SqliteDb", temporary_table_name)
    suffix = source_sql[close_paren + 1 :].strip()
    suffix_sql = f" {suffix}" if suffix else ""
    return f"CREATE TABLE {temporary_table} ({', '.join(legacy_definitions)}){suffix_sql}"


def _sqlite_expected_index_specs(
    table_name: str, indexes: dict[str, str]
) -> dict[str, tuple[tuple[str, ...], bool, bool, str | None]]:
    return {
        f"idx_{table_name}_name": (("name",), False, False, None),
        f"idx_{table_name}_next_run_at": (("next_run_at",), False, False, None),
        f"idx_{table_name}_created_at": (("created_at",), False, False, None),
        f"idx_{table_name}_enabled_next_run_at": (("enabled", "next_run_at"), False, False, None),
        indexes["legacy"].strip('"'): (("name",), True, False, None),
        indexes["managed"].strip('"'): (("managed_by",), False, False, None),
        indexes["owner"].strip('"'): (("owner_actor_id",), False, False, None),
        indexes["generic"].strip('"'): (
            ("name",),
            True,
            True,
            "managed_by is null or managed_by <> 'studio'",
        ),
        indexes["studio"].strip('"'): (
            ("owner_actor_id", "name"),
            True,
            True,
            "managed_by = 'studio'",
        ),
    }


def _sqlite_normalize_predicate(index_sql: str | None) -> str | None:
    if index_sql is None or re.search(r"\bwhere\b", index_sql, flags=re.IGNORECASE) is None:
        return None
    predicate = re.split(r"\bwhere\b", index_sql, maxsplit=1, flags=re.IGNORECASE)[1]
    return " ".join(predicate.strip().lower().split())


def _sqlite_schema_issues(
    *,
    table_name: str,
    indexes: dict[str, str],
    table_sql: str | None,
    columns: list[Any],
    index_rows: list[Any],
    index_columns: dict[str, tuple[str, ...]],
    index_sql: dict[str, str | None],
    trigger_names: list[str],
    foreign_keys: list[Any],
    dependent_view_names: list[str],
    temporary_object: str | None,
) -> list[str]:
    issues: list[str] = []
    column_names = {row[1] for row in columns}
    unknown_columns = column_names.difference((*_LEGACY_SQLITE_COLUMNS, *_V2_9_COLUMNS))
    missing_columns = set(_LEGACY_SQLITE_COLUMNS).difference(column_names)
    issues.extend(f"column {name!r}" for name in sorted(unknown_columns))
    issues.extend(f"missing legacy column {name!r}" for name in sorted(missing_columns))
    issues.extend(f"generated or hidden column {row[1]!r}" for row in columns if len(row) > 6 and row[6])

    expected_indexes = _sqlite_expected_index_specs(table_name, indexes)
    for row in index_rows:
        name = row[1]
        unique = bool(row[2])
        origin = row[3] if len(row) > 3 else "c"
        partial = bool(row[4]) if len(row) > 4 else False
        columns_for_index = index_columns.get(name, ())
        if origin == "pk" and columns_for_index == ("id",):
            continue
        expected = expected_indexes.get(name)
        if expected is None:
            issues.append(f"index {name!r}")
            continue
        expected_columns, expected_unique, expected_partial, expected_predicate = expected
        if (
            columns_for_index != expected_columns
            or unique != expected_unique
            or partial != expected_partial
            or _sqlite_normalize_predicate(index_sql.get(name)) != expected_predicate
        ):
            issues.append(f"unrecognized definition for index {name!r}")

    issues.extend(f"trigger {name!r}" for name in trigger_names)
    if foreign_keys:
        issues.append("outbound foreign key constraints")
    issues.extend(f"dependent view {name!r}" for name in dependent_view_names)
    if temporary_object is not None:
        issues.append(f"existing downgrade temporary object {temporary_object!r}")

    if table_sql is None:
        issues.append("missing table definition")
    else:
        unsupported_features = re.findall(
            r"\b(?:check|collate|generated|references|foreign\s+key|unique|without\s+rowid|strict|autoincrement)\b",
            table_sql,
            flags=re.IGNORECASE,
        )
        issues.extend(f"table feature {feature.lower()!r}" for feature in sorted(set(unsupported_features)))
    return issues


def _sqlite_rebuild_legacy_table(session: Any, table_name: str, table: str, source_sql: str) -> None:
    temporary_table_name = f"{table_name}__v2_9_down"
    temporary_table = quote_db_identifier("SqliteDb", temporary_table_name)
    legacy_columns = ", ".join(quote_db_identifier("SqliteDb", column) for column in _LEGACY_SQLITE_COLUMNS)
    session.execute(text(_sqlite_legacy_table_sql(source_sql, temporary_table_name)))
    session.execute(text(f"INSERT INTO {temporary_table} ({legacy_columns}) SELECT {legacy_columns} FROM {table}"))
    session.execute(text(f"DROP TABLE {table}"))
    session.execute(text(f"ALTER TABLE {temporary_table} RENAME TO {quote_db_identifier('SqliteDb', table_name)}"))
    for statement in _sqlite_legacy_indexes(table_name):
        session.execute(text(statement))


async def _sqlite_rebuild_legacy_table_async(session: Any, table_name: str, table: str, source_sql: str) -> None:
    temporary_table_name = f"{table_name}__v2_9_down"
    temporary_table = quote_db_identifier("AsyncSqliteDb", temporary_table_name)
    legacy_columns = ", ".join(quote_db_identifier("AsyncSqliteDb", column) for column in _LEGACY_SQLITE_COLUMNS)
    await session.execute(text(_sqlite_legacy_table_sql(source_sql, temporary_table_name)))
    await session.execute(
        text(f"INSERT INTO {temporary_table} ({legacy_columns}) SELECT {legacy_columns} FROM {table}")
    )
    await session.execute(text(f"DROP TABLE {table}"))
    await session.execute(
        text(f"ALTER TABLE {temporary_table} RENAME TO {quote_db_identifier('AsyncSqliteDb', table_name)}")
    )
    for statement in _sqlite_legacy_indexes(table_name):
        await session.execute(text(statement))


def _sqlite_table_exists(session: Any, table_name: str) -> bool:
    return (
        session.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).scalar()
        is not None
    )


def _assert_sqlite_downgrade_schema_safe(session: Any, table_name: str, table: str, indexes: dict[str, str]) -> str:
    table_sql = session.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:table_name"),
        {"table_name": table_name},
    ).scalar()
    columns = list(session.execute(text(f"PRAGMA table_xinfo({table})")).fetchall())
    index_rows = list(session.execute(text(f"PRAGMA index_list({table})")).fetchall())
    index_columns: dict[str, tuple[str, ...]] = {}
    index_sql: dict[str, str | None] = {}
    for row in index_rows:
        name = row[1]
        quoted_name = quote_db_identifier("SqliteDb", name)
        index_columns[name] = tuple(
            index_row[2]
            for index_row in session.execute(text(f"PRAGMA index_info({quoted_name})")).fetchall()
            if index_row[2] is not None
        )
        index_sql[name] = session.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:name"), {"name": name}
        ).scalar()
    trigger_names = [
        row[0]
        for row in session.execute(
            text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=:table_name"),
            {"table_name": table_name},
        ).fetchall()
    ]
    foreign_keys = list(session.execute(text(f"PRAGMA foreign_key_list({table})")).fetchall())
    dependent_view_names = [
        row[0]
        for row in session.execute(text("SELECT name, sql FROM sqlite_master WHERE type='view'")).fetchall()
        if row[1] is not None and table_name.casefold() in row[1].casefold()
    ]
    temporary_table_name = f"{table_name}__v2_9_down"
    temporary_object = session.execute(
        text("SELECT type || ' ' || name FROM sqlite_master WHERE name=:name"),
        {"name": temporary_table_name},
    ).scalar()
    issues = _sqlite_schema_issues(
        table_name=table_name,
        indexes=indexes,
        table_sql=table_sql,
        columns=columns,
        index_rows=index_rows,
        index_columns=index_columns,
        index_sql=index_sql,
        trigger_names=trigger_names,
        foreign_keys=foreign_keys,
        dependent_view_names=dependent_view_names,
        temporary_object=temporary_object,
    )
    if issues:
        raise _sqlite_schema_error(issues)
    return table_sql


async def _assert_sqlite_downgrade_schema_safe_async(
    session: Any, table_name: str, table: str, indexes: dict[str, str]
) -> str:
    table_sql = (
        await session.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        )
    ).scalar()
    columns = list((await session.execute(text(f"PRAGMA table_xinfo({table})"))).fetchall())
    index_rows = list((await session.execute(text(f"PRAGMA index_list({table})"))).fetchall())
    index_columns: dict[str, tuple[str, ...]] = {}
    index_sql: dict[str, str | None] = {}
    for row in index_rows:
        name = row[1]
        quoted_name = quote_db_identifier("AsyncSqliteDb", name)
        index_columns[name] = tuple(
            index_row[2]
            for index_row in (await session.execute(text(f"PRAGMA index_info({quoted_name})"))).fetchall()
            if index_row[2] is not None
        )
        index_sql[name] = (
            await session.execute(
                text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:name"), {"name": name}
            )
        ).scalar()
    trigger_names = [
        row[0]
        for row in (
            await session.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=:table_name"),
                {"table_name": table_name},
            )
        ).fetchall()
    ]
    foreign_keys = list((await session.execute(text(f"PRAGMA foreign_key_list({table})"))).fetchall())
    dependent_view_names = [
        row[0]
        for row in (await session.execute(text("SELECT name, sql FROM sqlite_master WHERE type='view'"))).fetchall()
        if row[1] is not None and table_name.casefold() in row[1].casefold()
    ]
    temporary_table_name = f"{table_name}__v2_9_down"
    temporary_object = (
        await session.execute(
            text("SELECT type || ' ' || name FROM sqlite_master WHERE name=:name"),
            {"name": temporary_table_name},
        )
    ).scalar()
    issues = _sqlite_schema_issues(
        table_name=table_name,
        indexes=indexes,
        table_sql=table_sql,
        columns=columns,
        index_rows=index_rows,
        index_columns=index_columns,
        index_sql=index_sql,
        trigger_names=trigger_names,
        foreign_keys=foreign_keys,
        dependent_view_names=dependent_view_names,
        temporary_object=temporary_object,
    )
    if issues:
        raise _sqlite_schema_error(issues)
    return table_sql


def _migrate_sqlite(db: BaseDb, table_name: str) -> bool:
    table, indexes = _sqlite_names(table_name)
    with db.Session() as session, session.begin():  # type: ignore[attr-defined]
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if not _sqlite_table_exists(session, table_name):
            return False
        columns = {row[1] for row in session.execute(text(f"PRAGMA table_info({table})")).fetchall()}
        # SQLite may persist ALTER TABLE even when a surrounding ORM
        # transaction later fails. Preflight legacy uniqueness before the
        # first DDL statement so a rejected migration leaves no new columns.
        if "managed_by" not in columns:
            legacy_duplicate = session.execute(
                text(f"SELECT 1 FROM {table} GROUP BY name HAVING COUNT(*) > 1 LIMIT 1")
            ).scalar()
            if legacy_duplicate is not None:
                raise _duplicate_error()
        else:
            generic_duplicate = session.execute(
                text(
                    f"SELECT 1 FROM {table} WHERE managed_by IS NULL OR managed_by <> :studio "
                    "GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"
                ),
                {"studio": STUDIO_SCHEDULE_MANAGED_BY},
            ).scalar()
            studio_group = "owner_actor_id, name" if "owner_actor_id" in columns else "name"
            studio_duplicate = session.execute(
                text(
                    f"SELECT 1 FROM {table} WHERE managed_by = :studio "
                    f"GROUP BY {studio_group} HAVING COUNT(*) > 1 LIMIT 1"
                ),
                {"studio": STUDIO_SCHEDULE_MANAGED_BY},
            ).scalar()
            if generic_duplicate is not None or studio_duplicate is not None:
                raise _duplicate_error()
        applied = False
        for column in _PROVENANCE_COLUMNS:
            if column not in columns:
                quoted_column = quote_db_identifier("SqliteDb", column)
                session.execute(text(f"ALTER TABLE {table} ADD COLUMN {quoted_column} TEXT"))
                applied = True
        if "pending_trigger_count" not in columns:
            session.execute(text(f"ALTER TABLE {table} ADD COLUMN pending_trigger_count INTEGER NOT NULL DEFAULT 0"))
            applied = True
        if "manual_trigger_claimed" not in columns:
            session.execute(text(f"ALTER TABLE {table} ADD COLUMN manual_trigger_claimed INTEGER NOT NULL DEFAULT 0"))
            applied = True

        generic_duplicate = session.execute(
            text(
                f"SELECT 1 FROM {table} WHERE managed_by IS NULL OR managed_by <> :studio "
                "GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"
            ),
            {"studio": STUDIO_SCHEDULE_MANAGED_BY},
        ).scalar()
        studio_duplicate = session.execute(
            text(
                f"SELECT 1 FROM {table} WHERE managed_by = :studio "
                "GROUP BY owner_actor_id, name HAVING COUNT(*) > 1 LIMIT 1"
            ),
            {"studio": STUDIO_SCHEDULE_MANAGED_BY},
        ).scalar()
        if generic_duplicate is not None or studio_duplicate is not None:
            raise _duplicate_error()

        index_names = {row[1] for row in session.execute(text(f"PRAGMA index_list({table})")).fetchall()}
        if indexes["legacy"].strip('"') in index_names:
            session.execute(text(f"DROP INDEX {indexes['legacy']}"))
            applied = True
        statements = {
            "managed": f"CREATE INDEX {indexes['managed']} ON {table} (managed_by)",
            "owner": f"CREATE INDEX {indexes['owner']} ON {table} (owner_actor_id)",
            "generic": (
                f"CREATE UNIQUE INDEX {indexes['generic']} ON {table} (name) "
                "WHERE managed_by IS NULL OR managed_by <> 'studio'"
            ),
            "studio": (
                f"CREATE UNIQUE INDEX {indexes['studio']} ON {table} (owner_actor_id, name) WHERE managed_by = 'studio'"
            ),
        }
        for key, statement in statements.items():
            if indexes[key].strip('"') not in index_names:
                session.execute(text(statement))
                applied = True
        return applied


async def _migrate_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
    table, indexes = _sqlite_names(table_name)
    async with db.async_session_factory() as session, session.begin():  # type: ignore[attr-defined]
        await session.execute(text("BEGIN IMMEDIATE"))
        exists = (
            await session.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
                {"table_name": table_name},
            )
        ).scalar()
        if exists is None:
            return False
        columns = {row[1] for row in (await session.execute(text(f"PRAGMA table_info({table})"))).fetchall()}
        if "managed_by" not in columns:
            legacy_duplicate = (
                await session.execute(text(f"SELECT 1 FROM {table} GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"))
            ).scalar()
            if legacy_duplicate is not None:
                raise _duplicate_error()
        else:
            generic_duplicate = (
                await session.execute(
                    text(
                        f"SELECT 1 FROM {table} WHERE managed_by IS NULL OR managed_by <> :studio "
                        "GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"
                    ),
                    {"studio": STUDIO_SCHEDULE_MANAGED_BY},
                )
            ).scalar()
            studio_group = "owner_actor_id, name" if "owner_actor_id" in columns else "name"
            studio_duplicate = (
                await session.execute(
                    text(
                        f"SELECT 1 FROM {table} WHERE managed_by = :studio "
                        f"GROUP BY {studio_group} HAVING COUNT(*) > 1 LIMIT 1"
                    ),
                    {"studio": STUDIO_SCHEDULE_MANAGED_BY},
                )
            ).scalar()
            if generic_duplicate is not None or studio_duplicate is not None:
                raise _duplicate_error()
        applied = False
        for column in _PROVENANCE_COLUMNS:
            if column not in columns:
                quoted_column = quote_db_identifier("AsyncSqliteDb", column)
                await session.execute(text(f"ALTER TABLE {table} ADD COLUMN {quoted_column} TEXT"))
                applied = True
        if "pending_trigger_count" not in columns:
            await session.execute(
                text(f"ALTER TABLE {table} ADD COLUMN pending_trigger_count INTEGER NOT NULL DEFAULT 0")
            )
            applied = True
        if "manual_trigger_claimed" not in columns:
            await session.execute(
                text(f"ALTER TABLE {table} ADD COLUMN manual_trigger_claimed INTEGER NOT NULL DEFAULT 0")
            )
            applied = True

        generic_duplicate = (
            await session.execute(
                text(
                    f"SELECT 1 FROM {table} WHERE managed_by IS NULL OR managed_by <> :studio "
                    "GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"
                ),
                {"studio": STUDIO_SCHEDULE_MANAGED_BY},
            )
        ).scalar()
        studio_duplicate = (
            await session.execute(
                text(
                    f"SELECT 1 FROM {table} WHERE managed_by = :studio "
                    "GROUP BY owner_actor_id, name HAVING COUNT(*) > 1 LIMIT 1"
                ),
                {"studio": STUDIO_SCHEDULE_MANAGED_BY},
            )
        ).scalar()
        if generic_duplicate is not None or studio_duplicate is not None:
            raise _duplicate_error()

        index_names = {row[1] for row in (await session.execute(text(f"PRAGMA index_list({table})"))).fetchall()}
        if indexes["legacy"].strip('"') in index_names:
            await session.execute(text(f"DROP INDEX {indexes['legacy']}"))
            applied = True
        statements = {
            "managed": f"CREATE INDEX {indexes['managed']} ON {table} (managed_by)",
            "owner": f"CREATE INDEX {indexes['owner']} ON {table} (owner_actor_id)",
            "generic": (
                f"CREATE UNIQUE INDEX {indexes['generic']} ON {table} (name) "
                "WHERE managed_by IS NULL OR managed_by <> 'studio'"
            ),
            "studio": (
                f"CREATE UNIQUE INDEX {indexes['studio']} ON {table} (owner_actor_id, name) WHERE managed_by = 'studio'"
            ),
        }
        for key, statement in statements.items():
            if indexes[key].strip('"') not in index_names:
                await session.execute(text(statement))
                applied = True
        return applied


def _postgres_names(db: Any, table_name: str) -> tuple[str, dict[str, str]]:
    db_type = type(db).__name__
    schema = quote_db_identifier(db_type, db.db_schema)
    table = quote_db_identifier(db_type, table_name)
    full_table = f"{schema}.{table}"
    return full_table, _index_names(db_type, table_name)


def _migrate_postgres(db: BaseDb, table_name: str) -> bool:
    full_table, indexes = _postgres_names(db, table_name)
    schema = full_table.rsplit(".", 1)[0]
    with db.Session() as session, session.begin():  # type: ignore[attr-defined]
        exists = session.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_schema=:schema AND table_name=:table"),
            {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
        ).scalar()
        if exists is None:
            return False
        for column in _PROVENANCE_COLUMNS:
            quoted_column = quote_db_identifier(type(db).__name__, column)
            session.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS {quoted_column} VARCHAR"))
        session.execute(
            text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS pending_trigger_count BIGINT NOT NULL DEFAULT 0")
        )
        session.execute(
            text(
                f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS manual_trigger_claimed BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        generic_duplicate = session.execute(
            text(
                f"SELECT 1 FROM {full_table} WHERE managed_by IS DISTINCT FROM :studio "
                "GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"
            ),
            {"studio": STUDIO_SCHEDULE_MANAGED_BY},
        ).scalar()
        studio_duplicate = session.execute(
            text(
                f"SELECT 1 FROM {full_table} WHERE managed_by = :studio "
                "GROUP BY owner_actor_id, name HAVING COUNT(*) > 1 LIMIT 1"
            ),
            {"studio": STUDIO_SCHEDULE_MANAGED_BY},
        ).scalar()
        if generic_duplicate is not None or studio_duplicate is not None:
            raise _duplicate_error()
        session.execute(text(f"DROP INDEX IF EXISTS {schema}.{indexes['legacy']}"))
        session.execute(text(f"CREATE INDEX IF NOT EXISTS {indexes['managed']} ON {full_table} (managed_by)"))
        session.execute(text(f"CREATE INDEX IF NOT EXISTS {indexes['owner']} ON {full_table} (owner_actor_id)"))
        session.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {indexes['generic']} ON {full_table} (name) "
                "WHERE managed_by IS DISTINCT FROM 'studio'"
            )
        )
        session.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {indexes['studio']} ON {full_table} (owner_actor_id, name) "
                "WHERE managed_by = 'studio'"
            )
        )
        return True


async def _migrate_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    full_table, indexes = _postgres_names(db, table_name)
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
        for column in _PROVENANCE_COLUMNS:
            quoted_column = quote_db_identifier(type(db).__name__, column)
            await session.execute(text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS {quoted_column} VARCHAR"))
        await session.execute(
            text(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS pending_trigger_count BIGINT NOT NULL DEFAULT 0")
        )
        await session.execute(
            text(
                f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS manual_trigger_claimed BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        generic_duplicate = (
            await session.execute(
                text(
                    f"SELECT 1 FROM {full_table} WHERE managed_by IS DISTINCT FROM :studio "
                    "GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"
                ),
                {"studio": STUDIO_SCHEDULE_MANAGED_BY},
            )
        ).scalar()
        studio_duplicate = (
            await session.execute(
                text(
                    f"SELECT 1 FROM {full_table} WHERE managed_by = :studio "
                    "GROUP BY owner_actor_id, name HAVING COUNT(*) > 1 LIMIT 1"
                ),
                {"studio": STUDIO_SCHEDULE_MANAGED_BY},
            )
        ).scalar()
        if generic_duplicate is not None or studio_duplicate is not None:
            raise _duplicate_error()
        await session.execute(text(f"DROP INDEX IF EXISTS {schema}.{indexes['legacy']}"))
        await session.execute(text(f"CREATE INDEX IF NOT EXISTS {indexes['managed']} ON {full_table} (managed_by)"))
        await session.execute(text(f"CREATE INDEX IF NOT EXISTS {indexes['owner']} ON {full_table} (owner_actor_id)"))
        await session.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {indexes['generic']} ON {full_table} (name) "
                "WHERE managed_by IS DISTINCT FROM 'studio'"
            )
        )
        await session.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {indexes['studio']} ON {full_table} (owner_actor_id, name) "
                "WHERE managed_by = 'studio'"
            )
        )
        return True


def _revert_sqlite(db: BaseDb, table_name: str) -> bool:
    table, indexes = _sqlite_names(table_name)
    # SQLite's portable DROP COLUMN path is a table rebuild. Foreign keys must
    # be disabled on this exact connection before the transaction begins so
    # replacing the parent schedule table does not cascade-delete run history.
    with db.db_engine.connect() as session:  # type: ignore[attr-defined]
        foreign_keys_enabled = bool(session.exec_driver_sql("PRAGMA foreign_keys").scalar())
        session.exec_driver_sql("PRAGMA foreign_keys=OFF")
        session.commit()
        try:
            session.exec_driver_sql("BEGIN IMMEDIATE")
            if not _sqlite_table_exists(session, table_name):
                session.rollback()
                return False
            columns = {row[1] for row in session.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            v2_9_columns_present = set(_V2_9_COLUMNS).intersection(columns)
            source_sql = None
            if v2_9_columns_present:
                source_sql = _assert_sqlite_downgrade_schema_safe(session, table_name, table, indexes)
            if "managed_by" in columns:
                _assert_no_studio_schedule_data(session, "SqliteDb", table)
            if "pending_trigger_count" in columns or "manual_trigger_claimed" in columns:
                _assert_no_pending_triggers(
                    session,
                    table,
                    has_pending_count="pending_trigger_count" in columns,
                    has_claimed_marker="manual_trigger_claimed" in columns,
                )
            index_names = {row[1] for row in session.execute(text(f"PRAGMA index_list({table})")).fetchall()}
            applied = bool(v2_9_columns_present) or any(index.strip('"') in index_names for index in indexes.values())
            if applied and v2_9_columns_present:
                assert source_sql is not None
                _sqlite_rebuild_legacy_table(session, table_name, table, source_sql)
            else:
                for index in indexes.values():
                    if index.strip('"') in index_names:
                        session.execute(text(f"DROP INDEX IF EXISTS {index}"))
            session.commit()
            return applied
        except Exception:
            session.rollback()
            raise
        finally:
            session.exec_driver_sql(f"PRAGMA foreign_keys={1 if foreign_keys_enabled else 0}")
            session.commit()


async def _revert_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
    table, indexes = _sqlite_names(table_name)
    async with db.db_engine.connect() as session:  # type: ignore[attr-defined]
        foreign_keys_enabled = bool((await session.exec_driver_sql("PRAGMA foreign_keys")).scalar())
        await session.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await session.commit()
        try:
            await session.exec_driver_sql("BEGIN IMMEDIATE")
            exists = (
                await session.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
                    {"table_name": table_name},
                )
            ).scalar()
            if exists is None:
                await session.rollback()
                return False
            columns = {row[1] for row in (await session.execute(text(f"PRAGMA table_info({table})"))).fetchall()}
            v2_9_columns_present = set(_V2_9_COLUMNS).intersection(columns)
            source_sql = None
            if v2_9_columns_present:
                source_sql = await _assert_sqlite_downgrade_schema_safe_async(session, table_name, table, indexes)
            if "managed_by" in columns:
                await _assert_no_studio_schedule_data_async(session, "AsyncSqliteDb", table)
            if "pending_trigger_count" in columns or "manual_trigger_claimed" in columns:
                await _assert_no_pending_triggers_async(
                    session,
                    table,
                    has_pending_count="pending_trigger_count" in columns,
                    has_claimed_marker="manual_trigger_claimed" in columns,
                )
            index_names = {row[1] for row in (await session.execute(text(f"PRAGMA index_list({table})"))).fetchall()}
            applied = bool(v2_9_columns_present) or any(index.strip('"') in index_names for index in indexes.values())
            if applied and v2_9_columns_present:
                assert source_sql is not None
                await _sqlite_rebuild_legacy_table_async(session, table_name, table, source_sql)
            else:
                for index in indexes.values():
                    if index.strip('"') in index_names:
                        await session.execute(text(f"DROP INDEX IF EXISTS {index}"))
            await session.commit()
            return applied
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.exec_driver_sql(f"PRAGMA foreign_keys={1 if foreign_keys_enabled else 0}")
            await session.commit()


def _revert_postgres(db: BaseDb, table_name: str) -> bool:
    full_table, indexes = _postgres_names(db, table_name)
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
        pending_trigger_exists = session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema=:schema AND table_name=:table AND column_name='pending_trigger_count'"
            ),
            {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
        ).scalar()
        claimed_trigger_exists = session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema=:schema AND table_name=:table AND column_name='manual_trigger_claimed'"
            ),
            {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
        ).scalar()
        if pending_trigger_exists is not None or claimed_trigger_exists is not None:
            _assert_no_pending_triggers(
                session,
                full_table,
                has_pending_count=pending_trigger_exists is not None,
                has_claimed_marker=claimed_trigger_exists is not None,
            )
        for index in indexes.values():
            session.execute(text(f"DROP INDEX IF EXISTS {schema}.{index}"))
        for column in reversed(_V2_9_COLUMNS):
            quoted_column = quote_db_identifier(type(db).__name__, column)
            session.execute(text(f"ALTER TABLE {full_table} DROP COLUMN IF EXISTS {quoted_column}"))
        return True


async def _revert_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    full_table, indexes = _postgres_names(db, table_name)
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
        pending_trigger_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema=:schema AND table_name=:table AND column_name='pending_trigger_count'"
                ),
                {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
            )
        ).scalar()
        claimed_trigger_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema=:schema AND table_name=:table AND column_name='manual_trigger_claimed'"
                ),
                {"schema": db.db_schema, "table": table_name},  # type: ignore[attr-defined]
            )
        ).scalar()
        if pending_trigger_exists is not None or claimed_trigger_exists is not None:
            await _assert_no_pending_triggers_async(
                session,
                full_table,
                has_pending_count=pending_trigger_exists is not None,
                has_claimed_marker=claimed_trigger_exists is not None,
            )
        for index in indexes.values():
            await session.execute(text(f"DROP INDEX IF EXISTS {schema}.{index}"))
        for column in reversed(_V2_9_COLUMNS):
            quoted_column = quote_db_identifier(type(db).__name__, column)
            await session.execute(text(f"ALTER TABLE {full_table} DROP COLUMN IF EXISTS {quoted_column}"))
        return True
