"""Utility functions for the MySQL database class."""

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agno.db.mysql.schemas import get_table_schema_definition
from agno.db.utils import (
    COMPONENT_METRICS_KEY_COLUMNS,
    METRICS_COST_FIELDS,
    METRICS_COUNT_MAP_COLUMNS,
    METRICS_MAX_COLUMNS,
    METRICS_SUM_FIELDS,
    METRICS_TOKEN_DETAILS_FIELDS,
    METRICS_TOKEN_FIELDS,
    AGGREGATE_METRICS_KEY_COLUMNS,
    build_aggregate_metrics_row,
    metrics_day_ranges,
    metrics_days_to_read,
)
from agno.utils.log import log_debug, log_error, log_warning

try:
    from sqlalchemy import (
        JSON,
        BigInteger,
        Engine,
        Integer,
        Numeric,
        Table,
        and_,
        case,
        cast,
        false,
        func,
        literal,
        literal_column,
        or_,
        select,
        true,
        type_coerce,
        union_all,
        update,
    )
    from sqlalchemy.dialects import mysql
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


# MySQL caps a statement at max_allowed_packet, so IN lists are sent in chunks
METRICS_IN_LIST_LIMIT = 10000

# MySQL scans the whole table for a long IN list of row values, so stale rows are deleted in smaller chunks
METRICS_STALE_KEYS_LIMIT = 1000


# Every assistant message's position, role, whether it was carried over from an earlier run, and its request duration
_METRICS_MESSAGES: Any = literal_column(
    "'$.messages[*]' COLUMNS (position FOR ORDINALITY, role VARCHAR(32) PATH '$.role', "
    "from_history JSON PATH '$.from_history', duration JSON PATH '$.metrics.duration')"
)

# JSON false, read from a JSON document: MariaDB has no CAST to JSON
_METRICS_JSON_FALSE: Any = literal_column("JSON_EXTRACT('false', '$')")

# The keys of a stored run that hold the runs nested inside it, in the order the rollup walks them
_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses", "workflow_agent_run")

# Every run of one of those lists, with its position in the list
_METRICS_NESTED_RUNS: Any = literal_column("'$[*]' COLUMNS (ordinality FOR ORDINALITY, value JSON PATH '$')")

# The one run a key holds on its own. MySQL's $[*] matches nothing in an object
_METRICS_NESTED_RUN: Any = literal_column("'$' COLUMNS (ordinality FOR ORDINALITY, value JSON PATH '$')")

# Every run of a session's legacy runs column, with what the runs table keeps of it
_METRICS_LEGACY_RUNS: Any = literal_column(
    "'$[*]' COLUMNS (run_id VARCHAR(255) PATH '$.run_id', agent_id VARCHAR(255) PATH '$.agent_id', "
    "team_id VARCHAR(255) PATH '$.team_id', workflow_id VARCHAR(255) PATH '$.workflow_id', "
    "parent_run_id VARCHAR(255) PATH '$.parent_run_id', called_from_run_id VARCHAR(255) PATH '$.called_from_run_id', "
    "status VARCHAR(50) PATH '$.status', "
    "created_at BIGINT PATH '$.created_at', run_data JSON PATH '$')"
)

# Every key of a JSON object
_METRICS_KEYS: Any = literal_column("'$[*]' COLUMNS (entry_key VARCHAR(255) PATH '$')")

# The JSON_TYPE of a JSON number
_METRICS_NUMBER_TYPES = ("INTEGER", "UNSIGNED INTEGER", "DOUBLE", "DECIMAL")


# -- DB util methods --
def apply_sorting(stmt, table: Table, sort_by: Optional[str] = None, sort_order: Optional[str] = None):
    """Apply sorting to the given SQLAlchemy statement.

    Args:
        stmt: The SQLAlchemy statement to modify
        table: The table being queried
        sort_by: The field to sort by
        sort_order: The sort order ('asc' or 'desc')

    Returns:
        The modified statement with sorting applied

    Note:
        For 'updated_at' sorting, uses COALESCE(updated_at, created_at) to fall back
        to created_at when updated_at is NULL. This ensures pre-2.0 records (which may
        have NULL updated_at) are sorted correctly by their creation time.
    """
    if sort_by is None:
        return stmt

    if not hasattr(table.c, sort_by):
        log_debug(f"Invalid sort field: '{sort_by}'. Will not apply any sorting.")
        return stmt

    # For updated_at, use COALESCE to fall back to created_at if updated_at is NULL
    # This handles pre-2.0 records that may have NULL updated_at values
    if sort_by == "updated_at" and hasattr(table.c, "created_at"):
        sort_column = func.coalesce(table.c.updated_at, table.c.created_at)
    else:
        sort_column = getattr(table.c, sort_by)

    if sort_order and sort_order == "asc":
        return stmt.order_by(sort_column.asc())
    else:
        return stmt.order_by(sort_column.desc())


def create_schema(session: Session, db_schema: str) -> None:
    """Create the database schema if it doesn't exist.

    Args:
        session: The SQLAlchemy session to use
        db_schema (str): The definition of the database schema to create
    """
    try:
        log_debug(f"Creating database if not exists: {db_schema}")
        # MySQL uses CREATE DATABASE instead of CREATE SCHEMA
        session.execute(text(f"CREATE DATABASE IF NOT EXISTS {db_schema};"))
    except Exception as e:
        log_warning(f"Could not create database {db_schema}: {str(e)}")


def is_table_available(session: Session, table_name: str, db_schema: str) -> bool:
    """
    Check if a table with the given name exists in the given schema.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        exists_query = text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table"
        )
        exists = session.execute(exists_query, {"schema": db_schema, "table": table_name}).scalar() is not None
        return exists

    except Exception as e:
        log_error(f"Error checking if table exists: {str(e)}")
        return False


def is_valid_table(db_engine: Engine, table_name: str, table_type: str, db_schema: str) -> bool:
    """
    Check if the existing table has the expected column names.

    Args:
        db_engine: Database engine
        table_name (str): Name of the table to validate
        table_type (str): Type of table (for schema lookup)
        db_schema (str): Database schema name

    Returns:
        bool: True if table has all expected columns, False if expected columns are missing

    Raises:
        Any error from inspecting the table, so a failed inspection is not read as a stale schema.
    """
    try:
        expected_table_schema = get_table_schema_definition(table_type)
        expected_columns = {col_name for col_name in expected_table_schema.keys() if not col_name.startswith("_")}

        # Get existing columns
        inspector = inspect(db_engine)
        existing_columns_info = inspector.get_columns(table_name, schema=db_schema)
        existing_columns = set(col["name"] for col in existing_columns_info)

        # Check if all expected columns exist
        missing_columns = expected_columns - existing_columns
        if missing_columns:
            log_warning(f"Missing columns {missing_columns} in table {db_schema}.{table_name}")
            return False

        return True
    except Exception as e:
        log_error(f"Error validating table schema for {db_schema}.{table_name}: {str(e)}")
        raise


def set_json_column_types(table: Table, table_type: str) -> None:
    """Give the JSON columns of a table loaded from MariaDB their JSON type.

    MariaDB stores a JSON column as LONGTEXT, so it loads as text: a dict could not be written to it and a read would
    return the JSON as a string.

    Args:
        table (Table): The table, loaded from the database.
        table_type (str): Type of table (for schema lookup)
    """
    for column_name, column_config in get_table_schema_definition(table_type).items():
        if not column_name.startswith("_") and column_config["type"] is JSON and column_name in table.c:
            table.c[column_name].type = JSON()


# -- Component metrics util methods --
def bulk_upsert_component_metrics(session: Session, table: Table, component_metrics_records: list[dict]) -> None:
    """Bulk upsert component metrics into the database, in the session's transaction.

    Args:
        session (Session): The session to upsert with.
        table (Table): The table to upsert into.
        component_metrics_records (list[dict]): The component metrics records to upsert.
    """
    if not component_metrics_records:
        return

    stmt = mysql.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns = {
        col.name: stmt.inserted[col.name]
        for col in table.columns
        if col.name not in [*COMPONENT_METRICS_KEY_COLUMNS, "created_at"]
    }

    stmt = stmt.on_duplicate_key_update(**update_columns)
    session.execute(stmt, component_metrics_records)


async def abulk_upsert_component_metrics(
    session: AsyncSession, table: Table, component_metrics_records: list[dict]
) -> None:
    """Bulk upsert component metrics into the database, in the session's transaction.

    Args:
        session (AsyncSession): The session to upsert with.
        table (Table): The table to upsert into.
        component_metrics_records (list[dict]): The component metrics records to upsert.
    """
    if not component_metrics_records:
        return

    stmt = mysql.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns = {
        col.name: stmt.inserted[col.name]
        for col in table.columns
        if col.name not in [*COMPONENT_METRICS_KEY_COLUMNS, "created_at"]
    }

    stmt = stmt.on_duplicate_key_update(**update_columns)
    await session.execute(stmt, component_metrics_records)


def _aggregate_metrics_upsert(table: Table, aggregate_metrics_row: Dict[str, Any], read_version: Optional[int]) -> Any:
    """Build the upsert of an aggregate metrics row.

    A new row starts at version 1, and every write of a stored one moves its version by one in the same
    statement, so two writers never give it the same version.

    Args:
        table (Table): The aggregate metrics table.
        aggregate_metrics_row (Dict[str, Any]): The row, from build_aggregate_metrics_row.
        read_version (Optional[int]): The version of the stored row read before its rows were rebuilt. None when
            there was no stored row.

    Returns:
        Any: The upsert statement.
    """
    stmt = mysql.insert(table).values({**aggregate_metrics_row, "version": 1})

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns: List[Tuple[str, Any]] = [
        (col.name, stmt.inserted[col.name])
        for col in table.columns
        if col.name not in [*AGGREGATE_METRICS_KEY_COLUMNS, "created_at", "version", "completed"]
    ]
    # Compared in the statement, so a reopen written since the version was read keeps the period open. MySQL sets
    # the columns in order, each seeing the ones before, so the version is compared before it moves
    update_columns.append(
        (
            "completed",
            and_(table.c.version == read_version, stmt.inserted.completed) if read_version is not None else false(),
        )
    )
    update_columns.append(("version", table.c.version + 1))

    return stmt.on_duplicate_key_update(update_columns)


def upsert_aggregate_metrics_row(
    session: Session, table: Table, aggregate_metrics_row: Dict[str, Any], read_version: Optional[int]
) -> None:
    """Upsert an aggregate metrics row into the database, in the session's transaction.

    Args:
        session (Session): The session to upsert with.
        table (Table): The table to upsert into.
        aggregate_metrics_row (Dict[str, Any]): The row, from build_aggregate_metrics_row.
        read_version (Optional[int]): The version of the stored row read before its rows were rebuilt.
    """
    session.execute(_aggregate_metrics_upsert(table, aggregate_metrics_row, read_version))


async def aupsert_aggregate_metrics_row(
    session: AsyncSession, table: Table, aggregate_metrics_row: Dict[str, Any], read_version: Optional[int]
) -> None:
    """Upsert an aggregate metrics row into the database, in the session's transaction.

    Args:
        session (AsyncSession): The session to upsert with.
        table (Table): The table to upsert into.
        aggregate_metrics_row (Dict[str, Any]): The row, from build_aggregate_metrics_row.
        read_version (Optional[int]): The version of the stored row read before its rows were rebuilt.
    """
    await session.execute(_aggregate_metrics_upsert(table, aggregate_metrics_row, read_version))


def _aggregate_metrics_rows_upsert(table: Table) -> Any:
    """Build the bulk upsert of user rows of the aggregate metrics table. A user row is written with its period's
    everyone row, so its completed and version are never compared."""
    stmt = mysql.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns: Dict[str, Any] = {
        col.name: stmt.inserted[col.name]
        for col in table.columns
        if col.name not in [*AGGREGATE_METRICS_KEY_COLUMNS, "created_at", "version"]
    }
    # Inlined: the driver sends many rows as one INSERT only when every parameter is in its VALUES
    update_columns["version"] = table.c.version + literal_column("1")
    return stmt.on_duplicate_key_update(**update_columns)


def bulk_upsert_aggregate_metrics_rows(session: Session, table: Table, aggregate_metrics_rows: List[Dict[str, Any]]) -> None:
    """Bulk upsert the user rows of a period into the aggregate metrics table, in the session's transaction.

    Args:
        session (Session): The session to upsert with.
        table (Table): The aggregate metrics table.
        aggregate_metrics_rows (List[Dict[str, Any]]): The user rows, from build_aggregate_metrics_rows.
    """
    if not aggregate_metrics_rows:
        return
    session.execute(_aggregate_metrics_rows_upsert(table), [{**row, "version": 1} for row in aggregate_metrics_rows])


async def abulk_upsert_aggregate_metrics_rows(
    session: AsyncSession, table: Table, aggregate_metrics_rows: List[Dict[str, Any]]
) -> None:
    """Bulk upsert the user rows of a period into the aggregate metrics table, in the session's transaction.

    Args:
        session (AsyncSession): The session to upsert with.
        table (Table): The aggregate metrics table.
        aggregate_metrics_rows (List[Dict[str, Any]]): The user rows, from build_aggregate_metrics_rows.
    """
    if not aggregate_metrics_rows:
        return
    await session.execute(_aggregate_metrics_rows_upsert(table), [{**row, "version": 1} for row in aggregate_metrics_rows])


def _reopen_metrics_row(table: Table, row_date: date, aggregation_period: str) -> Any:
    """Build the reopen of a day's or a month's everyone row of the aggregate metrics table, inserting an empty open row
    when it has none."""
    stmt = mysql.insert(table).values(
        {**build_aggregate_metrics_row([], aggregation_period, row_date, completed=False), "version": 1}
    )
    return stmt.on_duplicate_key_update(completed=False, version=table.c.version + 1)


def reopen_metrics_day(session: Session, table: Table, day: date) -> None:
    """Reopen a day's aggregate metrics row, in the session's transaction, so the next calculation rebuilds the day.

    Args:
        session (Session): The session of the write that changed the day.
        table (Table): The aggregate metrics table.
        day (date): The day, from metrics_day_to_reopen.
    """
    session.execute(_reopen_metrics_row(table, day, "daily"))


async def areopen_metrics_day(session: AsyncSession, table: Table, day: date) -> None:
    """Reopen a day's aggregate metrics row, in the session's transaction, so the next calculation rebuilds the day.

    Args:
        session (AsyncSession): The session of the write that changed the day.
        table (Table): The aggregate metrics table.
        day (date): The day, from metrics_day_to_reopen.
    """
    await session.execute(_reopen_metrics_row(table, day, "daily"))


def _metrics_days_from(table: Table, starting_date: date) -> Any:
    """Build the read of the date of every day's everyone row of the aggregate metrics table from the given date on."""
    return select(table.c.date).where(
        table.c.aggregation_period == "daily", table.c.user_id == "", table.c.date >= starting_date
    )


def _reopen_metrics_days_in(table: Table, days: List[date]) -> Any:
    """Build the reopen of the given days' everyone rows of the aggregate metrics table."""
    return (
        update(table)
        .where(table.c.aggregation_period == "daily", table.c.user_id == "", table.c.date.in_(days))
        .values(completed=False, version=table.c.version + 1)
    )


def reopen_metrics_days_from(session: Session, table: Table, starting_date: date) -> None:
    """Reopen every day's aggregate metrics row from the given date on, in the session's transaction, as a write reopens
    a day, so the next calculation rebuilds them.

    Args:
        session (Session): The session to reopen with.
        table (Table): The aggregate metrics table.
        starting_date (date): The first day to reopen.
    """
    # Read first, then reopened by key: an update over a range of dates locks the user rows of those days too, which a
    # day's calculation writes before its everyone row
    days = list(session.execute(_metrics_days_from(table, starting_date)).scalars().all())
    for start in range(0, len(days), METRICS_IN_LIST_LIMIT):
        session.execute(_reopen_metrics_days_in(table, days[start : start + METRICS_IN_LIST_LIMIT]))


async def areopen_metrics_days_from(session: AsyncSession, table: Table, starting_date: date) -> None:
    """Reopen every day's aggregate metrics row from the given date on, in the session's transaction, as a write reopens
    a day, so the next calculation rebuilds them.

    Args:
        session (AsyncSession): The session to reopen with.
        table (Table): The aggregate metrics table.
        starting_date (date): The first day to reopen.
    """
    # Read first, then reopened by key: an update over a range of dates locks the user rows of those days too, which a
    # day's calculation writes before its everyone row
    days = list((await session.execute(_metrics_days_from(table, starting_date))).scalars().all())
    for start in range(0, len(days), METRICS_IN_LIST_LIMIT):
        await session.execute(_reopen_metrics_days_in(table, days[start : start + METRICS_IN_LIST_LIMIT]))


def reopen_metrics_month(session: Session, table: Table, month_start: date) -> None:
    """Reopen a month's aggregate metrics row, in the session's transaction, so the next calculation rebuilds the month.

    Args:
        session (Session): The session of the day rebuilt in the month.
        table (Table): The aggregate metrics table.
        month_start (date): The first day of the month.
    """
    session.execute(_reopen_metrics_row(table, month_start, "monthly"))


async def areopen_metrics_month(session: AsyncSession, table: Table, month_start: date) -> None:
    """Reopen a month's aggregate metrics row, in the session's transaction, so the next calculation rebuilds the month.

    Args:
        session (AsyncSession): The session of the day rebuilt in the month.
        table (Table): The aggregate metrics table.
        month_start (date): The first day of the month.
    """
    await session.execute(_reopen_metrics_row(table, month_start, "monthly"))


def _metrics_call_durations(run_data: Any) -> Any:
    """Build every assistant message's request duration, skipping messages carried over from an earlier run: those
    from history, and those a forked run copied from the run it was forked from."""
    message = func.json_table(run_data, _METRICS_MESSAGES).table_valued("position", "role", "from_history", "duration")
    skip = func.coalesce(cast(func.json_extract(run_data, "$.forked_from_message_index"), Integer), 0)
    return (
        # Read through JSON_EXTRACT so each duration stays a number: MariaDB adds a JSON_TABLE column as text
        select(func.json_arrayagg(func.json_extract(message.c.duration, "$"), type_=JSON))
        .where(
            message.c.position > skip,
            message.c.role == "assistant",
            or_(message.c.from_history.is_(None), message.c.from_history == _METRICS_JSON_FALSE),
        )
        .scalar_subquery()
    )


def _metrics_nested_run(path: Any, depth: Any, key: str, run_data: Any) -> Any:
    """Build a run nested inside a stored run with only what component metrics count, and where it sits.

    Built where the run is read: MySQL rejects a JSON_TABLE over a column of the recursive query from outside it.
    """
    return func.json_object(
        "path",
        path,
        "depth",
        depth,
        "key",
        key,
        "run_id",
        func.json_extract(run_data, "$.run_id"),
        "agent_id",
        func.json_extract(run_data, "$.agent_id"),
        "team_id",
        func.json_extract(run_data, "$.team_id"),
        "session_id",
        func.json_extract(run_data, "$.session_id"),
        "parent_run_id",
        func.json_extract(run_data, "$.parent_run_id"),
        "metrics",
        func.json_extract(run_data, "$.metrics"),
        "model",
        func.json_extract(run_data, "$.model"),
        "model_provider",
        func.json_extract(run_data, "$.model_provider"),
        "call_durations",
        _metrics_call_durations(run_data),
        type_=JSON,
    )


def metrics_parent_run_id(table: Table) -> Any:
    """Build the id of the run that started a stored run: its team's or workflow's run, or the run whose tool call
    started it."""
    return func.coalesce(
        table.c.parent_run_id, func.json_unquote(func.json_extract(table.c.run_data, "$.called_from_run_id"))
    )


def build_component_metrics_legacy_runs_query(
    sessions_table: Table, runs_table: Optional[Table], start_timestamp: int, end_timestamp: int
) -> Optional[Any]:
    """Build the query that reads the runs not yet migrated out of the sessions table's legacy runs column, created in
    the given time range, in the runs table's shape.

    Args:
        sessions_table (Table): The sessions table.
        runs_table (Optional[Table]): The runs table. A run it also holds is read from there.
        start_timestamp (int): The start of the range, included.
        end_timestamp (int): The end of the range, not included.

    Returns:
        Optional[Any]: The query. Each run is read whole: MySQL rejects a JSON_TABLE over a column of a JSON_TABLE in
            the recursive query build_component_metrics_runs_query reads nested runs with. None when there is no
            legacy runs column.
    """
    if "runs" not in sessions_table.c:
        return None

    # Extracted in the database instead of loading the column, as calculate_metrics does
    legacy_run = func.json_table(sessions_table.c.runs, _METRICS_LEGACY_RUNS).table_valued(
        "run_id",
        "agent_id",
        "team_id",
        "workflow_id",
        "parent_run_id",
        "called_from_run_id",
        "status",
        "created_at",
        "run_data",
    )
    created_at = func.coalesce(legacy_run.c.created_at, sessions_table.c.created_at)
    # A legacy run is dated and typed the way the v3.0.0 migration writes it to the runs table
    legacy_runs_stmt = select(
        legacy_run.c.run_id,
        sessions_table.c.session_id,
        case(
            (func.coalesce(legacy_run.c.agent_id, "") != "", "agent"),
            (func.coalesce(legacy_run.c.team_id, "") != "", "team"),
            else_="workflow",
        ).label("run_type"),
        legacy_run.c.agent_id,
        legacy_run.c.team_id,
        legacy_run.c.workflow_id,
        sessions_table.c.user_id,
        func.coalesce(legacy_run.c.parent_run_id, legacy_run.c.called_from_run_id).label("parent_run_id"),
        legacy_run.c.status,
        type_coerce(legacy_run.c.run_data, JSON).label("run_data"),
        created_at.label("created_at"),
    ).select_from(sessions_table.join(legacy_run, true()))
    legacy_runs_stmt = legacy_runs_stmt.where(
        # A session holds runs created after it started and before it was last written
        sessions_table.c.created_at < end_timestamp,
        func.coalesce(sessions_table.c.updated_at, sessions_table.c.created_at) >= start_timestamp,
        created_at >= start_timestamp,
        created_at < end_timestamp,
        # The migration skips what is no run
        func.json_type(legacy_run.c.run_data) == "OBJECT",
        legacy_run.c.run_id.isnot(None),
        # A run copied into a forked session repeats a run counted in the session it was made in
        func.json_extract(legacy_run.c.run_data, "$.forked_from_session_id").is_(None),
    )
    if runs_table is not None:
        # The runs table wins on a run in both, as merge_runs_table_with_legacy_blob does
        legacy_runs_stmt = legacy_runs_stmt.where(
            ~select(runs_table.c.run_id).where(runs_table.c.run_id == legacy_run.c.run_id).exists()
        )
    return legacy_runs_stmt


def build_component_metrics_runs_query(table: Table, start_timestamp: int, end_timestamp: int) -> Any:
    """Build the query that reads the runs created in the given time range, with only what component metrics count.

    Args:
        table (Table): The runs table.
        start_timestamp (int): The start of the range, included.
        end_timestamp (int): The end of the range, not included.

    Returns:
        Any: The query. Of the messages it reads only each request's duration, of the metrics only what
            component metrics count, and of the runs nested inside a run, at any depth, only the same.
    """
    # One row per nested run, read a level at a time. The path orders them the way the rollup walks them
    nested_selects = []
    for position, key in enumerate(_METRICS_NESTED_RUN_KEYS):
        nested_run = func.json_table(
            func.json_extract(table.c.run_data, f"$.{key}"),
            _METRICS_NESTED_RUN if key == "workflow_agent_run" else _METRICS_NESTED_RUNS,
        ).table_valued("ordinality", "value")
        path: Any = cast(func.concat(str(position), func.lpad(nested_run.c.ordinality, 9, "0")), mysql.CHAR(1000))
        nested_selects.append(
            select(
                table.c.run_id.label("parent_run_id"),
                path.label("path"),
                literal(1).label("depth"),
                nested_run.c.value.label("run_data"),
                _metrics_nested_run(path, 1, key, nested_run.c.value).label("nested_run"),
            )
            .select_from(table.join(nested_run, true()))
            .where(
                table.c.created_at >= start_timestamp,
                table.c.created_at < end_timestamp,
                func.json_type(nested_run.c.value) == "OBJECT",
            )
        )
    # MySQL takes every SELECT that starts the recursion ahead of the ones that follow it
    nested = nested_selects[0].cte("nested", recursive=True)
    nested_selects = nested_selects[1:]
    for position, key in enumerate(_METRICS_NESTED_RUN_KEYS):
        nested_run = func.json_table(
            func.json_extract(nested.c.run_data, f"$.{key}"),
            _METRICS_NESTED_RUN if key == "workflow_agent_run" else _METRICS_NESTED_RUNS,
        ).table_valued("ordinality", "value")
        path = func.concat(nested.c.path, str(position), func.lpad(nested_run.c.ordinality, 9, "0"))
        nested_selects.append(
            select(
                nested.c.parent_run_id,
                path,
                nested.c.depth + 1,
                nested_run.c.value,
                _metrics_nested_run(path, nested.c.depth + 1, key, nested_run.c.value),
            )
            .select_from(nested.join(nested_run, true()))
            .where(func.json_type(nested_run.c.value) == "OBJECT")
        )
    nested = nested.union_all(*nested_selects)
    nested_runs = (
        select(
            nested.c.parent_run_id,
            # JSON_ARRAYAGG takes no ORDER BY, so each run carries its path and build_component_metrics_run orders them
            func.json_arrayagg(nested.c.nested_run, type_=JSON).label("nested_runs"),
        )
        .group_by(nested.c.parent_run_id)
        .subquery("nested_runs")
    )
    return (
        select(
            table.c.run_id,
            table.c.session_id,
            table.c.run_type,
            table.c.agent_id,
            table.c.team_id,
            table.c.workflow_id,
            table.c.user_id,
            metrics_parent_run_id(table).label("parent_run_id"),
            table.c.status,
            func.json_extract(table.c.run_data, "$.metrics", type_=JSON).label("metrics"),
            func.json_extract(table.c.run_data, "$.model", type_=JSON).label("model"),
            func.json_extract(table.c.run_data, "$.model_provider", type_=JSON).label("model_provider"),
            _metrics_call_durations(table.c.run_data).label("call_durations"),
            nested_runs.c.nested_runs,
            table.c.created_at,
        )
        .select_from(table.outerjoin(nested_runs, nested_runs.c.parent_run_id == table.c.run_id))
        .where(
            table.c.created_at >= start_timestamp,
            table.c.created_at < end_timestamp,
            # A run copied into a forked session repeats a run counted in the session it was made in
            func.json_extract(table.c.run_data, "$.forked_from_session_id").is_(None),
        )
    )


def build_component_metrics_run(row: Any) -> Dict[str, Any]:
    """Build a run in its stored shape from a row of the component metrics runs query.

    Args:
        row (Any): A row of build_component_metrics_runs_query.

    Returns:
        Dict[str, Any]: The run, with the run_data calculate_date_component_metrics reads.
    """
    run = dict(row._mapping)
    nested_runs = run.pop("nested_runs") or []
    run["run_data"] = {
        "metrics": run.pop("metrics"),
        "model": run.pop("model"),
        "model_provider": run.pop("model_provider"),
        "messages": [
            {"role": "assistant", "metrics": {"duration": duration}} for duration in run.pop("call_durations") or []
        ],
    }
    # A nested run comes after the run it is nested inside, so the last run met at each depth is its parent
    parents = [run["run_data"]]
    for nested_run in sorted(nested_runs, key=lambda nested_run: nested_run["path"]):
        nested_run.pop("path")
        depth = nested_run.pop("depth")
        nested_run["messages"] = [
            {"role": "assistant", "metrics": {"duration": duration}}
            for duration in nested_run.pop("call_durations") or []
        ]
        key = nested_run.pop("key")
        # A workflow agent's run is stored as the run itself, the other nested runs in lists
        if key == "workflow_agent_run":
            parents[depth - 1][key] = nested_run
        else:
            parents[depth - 1].setdefault(key, []).append(nested_run)
        parents[depth:] = [nested_run]
    return run


def _metrics_entries(column: Any) -> Any:
    """Build the key of every entry of a JSON object, one row each. It reads the row it is joined to, so it needs no
    join condition."""
    return func.json_table(func.json_keys(column), _METRICS_KEYS).table_valued("entry_key", joins_implicitly=True)


def _metrics_entry(column: Any, *keys: Any) -> Any:
    """Build the value of a JSON object column under the given keys, one level down per key."""
    path: List[Any] = ["$"]
    for key in keys:
        path.extend(['."', key, '"'])
    return func.json_extract(column, func.concat(*path))


def _metrics_column(table: Table, field: str) -> Any:
    """Build a column of a metrics row to total: the column itself, its key of token_details for a token count or the
    cost kept there, the total of the audio counts, the sessions of every type, or the runs no other run started."""
    if field == "audio_total_tokens":
        return func.coalesce(_metrics_column(table, "audio_input_tokens"), 0) + func.coalesce(
            _metrics_column(table, "audio_output_tokens"), 0
        )
    if field == "cost":
        return cast(func.json_extract(table.c.token_details, f"$.{field}"), Numeric(65, 30))
    if field in (*METRICS_TOKEN_DETAILS_FIELDS, *METRICS_COST_FIELDS):
        return cast(func.json_extract(table.c.token_details, f"$.{field}"), BigInteger)
    # The aggregate metrics table keeps the sessions of each type only
    if field == "sessions_count" and field not in table.c:
        return table.c.agent_sessions_count + table.c.team_sessions_count + table.c.workflow_sessions_count
    # The component metrics table keeps the runs of each component: the root runs are those no other run started
    if field == "root_runs_count" and field not in table.c:
        return case((table.c.parent_component_id == "", table.c.runs_count), else_=0)
    return table.c[field]


def _metrics_models(table: Table) -> Tuple[Any, Any, Any, Any, Any]:
    """Build the rows of a metrics table joined to each model of their model_metrics, which maps each provider to the
    count and cost of each of its models, and the provider, the id, the count and the cost of the model."""
    provider = _metrics_entries(table.c.model_metrics)
    model = _metrics_entries(_metrics_entry(table.c.model_metrics, provider.c.entry_key))
    # Binary collation keeps string comparisons case-sensitive, matching other SQL backends.
    return (
        table.join(provider, true()).join(model, true()),
        provider.c.entry_key.collate("utf8mb4_bin").label("model_provider"),
        model.c.entry_key.collate("utf8mb4_bin").label("model_id"),
        cast(_metrics_entry(table.c.model_metrics, provider.c.entry_key, model.c.entry_key, "count"), BigInteger),
        cast(_metrics_entry(table.c.model_metrics, provider.c.entry_key, model.c.entry_key, "cost"), Numeric(65, 30)),
    )


def build_component_metrics_totals_queries(
    table: Table,
    starting_date: date,
    ending_date: date,
    user_id: str,
    fields: Sequence[str],
    month_starts: Sequence[date] = (),
) -> Dict[str, Any]:
    """Build the queries that total the component metrics of each day in the given date range.

    Args:
        table (Table): The aggregate metrics table, or the component metrics table to total the runs with no user.
        starting_date (date): The first day to total.
        ending_date (date): The last day to total.
        user_id (str): The user whose rows are totalled: ``""`` totals the everyone rows of the aggregate metrics table, or
            the rows with no user of the component metrics table.
        fields (Sequence[str]): The columns to total.
        month_starts (Sequence[date]): The first day of every month inside the date range to total from its month
            row instead of its days.

    Returns:
        Dict[str, Any]: The queries, keyed "totals", "count_maps", "additional_metrics" and "model_metrics".
            Empty when there is no day to total.
    """
    # Days that follow one another are looked up as one range, which is planned by the rows it holds,
    # where a list of days is planned as if each day held rows
    day_ranges = [
        and_(table.c.date >= first_day, table.c.date <= last_day)
        for first_day, last_day in metrics_day_ranges(metrics_days_to_read(starting_date, ending_date, month_starts))
    ]
    filters = []
    if day_ranges:
        filters.append(and_(table.c.aggregation_period == "daily", or_(*day_ranges)))
    if month_starts:
        filters.append(and_(table.c.aggregation_period == "monthly", table.c.date.in_(month_starts)))
    if not filters:
        return {}
    where = and_(table.c.user_id == user_id, or_(*filters))

    totals = [func.max(table.c.updated_at).label("updated_at")]
    for field in fields:
        if field in METRICS_SUM_FIELDS:
            totals.append(func.sum(_metrics_column(table, field)).label(field))
        elif field in METRICS_MAX_COLUMNS:
            totals.append(func.max(table.c[field]).label(field))
    queries: Dict[str, Any] = {"totals": select(table.c.date, *totals).where(where).group_by(table.c.date)}

    # Each key of a map of counts totalled on its own. MySQL has no function listing an object's key and value
    # pairs, so its keys are listed and each value is read by its key
    count_map_queries = []
    for field in fields:
        if field in METRICS_COUNT_MAP_COLUMNS:
            entry = _metrics_entries(table.c[field])
            # Binary collation keeps string comparisons case-sensitive, matching other SQL backends.
            entry_key = entry.c.entry_key.collate("utf8mb4_bin")
            count_map_queries.append(
                select(
                    table.c.date,
                    literal(field).label("field"),
                    entry_key.label("key"),
                    func.sum(cast(_metrics_entry(table.c[field], entry.c.entry_key), BigInteger)).label("count"),
                )
                .select_from(table.join(entry, true()))
                .where(where)
                .group_by(table.c.date, entry_key)
            )
    if count_map_queries:
        queries["count_maps"] = union_all(*count_map_queries)

    # Only the numbers of additional_metrics are totalled; the rest keeps no meaning across rows
    if "additional_metrics" in fields:
        entry = _metrics_entries(table.c.additional_metrics)
        entry_key = entry.c.entry_key.collate("utf8mb4_bin")
        value = _metrics_entry(table.c.additional_metrics, entry.c.entry_key)
        queries["additional_metrics"] = (
            select(
                table.c.date,
                entry_key.label("key"),
                func.sum(cast(value, Numeric(65, 30))).label("value"),
            )
            .select_from(table.join(entry, true()))
            .where(where, func.json_type(value).in_(_METRICS_NUMBER_TYPES))
            .group_by(table.c.date, entry_key)
        )

    if "model_metrics" in fields:
        models, model_provider, model_id, count, cost = _metrics_models(table)
        queries["model_metrics"] = (
            select(table.c.date, model_id, model_provider, func.sum(count).label("count"), func.sum(cost).label("cost"))
            .select_from(models)
            .where(where)
            .group_by(table.c.date, model_id, model_provider)
        )

    return queries


def build_metrics_by_owner_queries(
    table: Table, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
) -> Dict[str, Any]:
    """Build the queries that total the component metrics of each user and day, for get_metrics.

    Args:
        table (Table): The component metrics table.
        starting_date (Optional[date]): The first day to total.
        ending_date (Optional[date]): The last day to total.
        user_id (Optional[str]): Total only this user's rows. ``None`` totals every user's.

    Returns:
        Dict[str, Any]: The queries, keyed "totals" and "model_metrics", for build_metrics_by_owner.
    """
    filters = [table.c.aggregation_period == "daily"]
    if starting_date:
        filters.append(table.c.date >= starting_date)
    if ending_date:
        filters.append(table.c.date <= ending_date)
    if user_id is not None:
        filters.append(table.c.user_id == user_id)

    totals = select(
        table.c.date,
        table.c.user_id,
        table.c.component_type,
        func.sum(table.c.sessions_count).label("sessions_count"),
        func.sum(table.c.runs_count).label("runs_count"),
        *[func.sum(_metrics_column(table, field)).label(field) for field in [*METRICS_TOKEN_FIELDS, "cost"]],
        func.min(table.c.created_at).label("created_at"),
        func.max(table.c.updated_at).label("updated_at"),
    ).where(*filters)

    models, model_provider, model_id, count, cost = _metrics_models(table)
    model_metrics = (
        select(
            table.c.date,
            table.c.user_id,
            model_id,
            model_provider,
            func.sum(count).label("count"),
            func.sum(cost).label("cost"),
        )
        .select_from(models)
        .where(*filters)
    )

    return {
        "totals": totals.group_by(table.c.date, table.c.user_id, table.c.component_type),
        "model_metrics": model_metrics.group_by(table.c.date, table.c.user_id, model_id, model_provider),
    }


# -- Async DB util methods --
async def acreate_schema(session: AsyncSession, db_schema: str) -> None:
    """Async version: Create the database schema if it doesn't exist.

    Args:
        session: The async SQLAlchemy session to use
        db_schema (str): The definition of the database schema to create
    """
    try:
        log_debug(f"Creating database if not exists: {db_schema}")
        # MySQL uses CREATE DATABASE instead of CREATE SCHEMA
        await session.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db_schema}`;"))
    except Exception as e:
        log_warning(f"Could not create database {db_schema}: {str(e)}")


async def ais_table_available(session: AsyncSession, table_name: str, db_schema: str) -> bool:
    """Async version: Check if a table with the given name exists in the given schema.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        exists_query = text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table"
        )
        result = await session.execute(exists_query, {"schema": db_schema, "table": table_name})
        exists = result.scalar() is not None
        return exists

    except Exception as e:
        log_error(f"Error checking if table exists: {str(e)}")
        return False


async def ais_valid_table(db_engine: AsyncEngine, table_name: str, table_type: str, db_schema: str) -> bool:
    """Async version: Check if the existing table has the expected column names.

    Args:
        db_engine: Async database engine
        table_name (str): Name of the table to validate
        table_type (str): Type of table (for schema lookup)
        db_schema (str): Database schema name

    Returns:
        bool: True if table has all expected columns, False if expected columns are missing

    Raises:
        Any error from inspecting the table, so a failed inspection is not read as a stale schema.
    """
    try:
        expected_table_schema = get_table_schema_definition(table_type)
        expected_columns = {col_name for col_name in expected_table_schema.keys() if not col_name.startswith("_")}

        # Get existing columns from the async engine
        async with db_engine.connect() as conn:
            existing_columns = await conn.run_sync(_get_table_columns, table_name, db_schema)

        # Check if all expected columns exist
        missing_columns = expected_columns - existing_columns
        if missing_columns:
            log_warning(f"Missing columns {missing_columns} in table {db_schema}.{table_name}")
            return False

        return True
    except Exception as e:
        log_error(f"Error validating table schema for {db_schema}.{table_name}: {str(e)}")
        raise


def _get_table_columns(connection, table_name: str, db_schema: str) -> set[str]:
    """Helper function to get table columns using sync inspector."""
    inspector = inspect(connection)
    columns_info = inspector.get_columns(table_name, schema=db_schema)
    return {col["name"] for col in columns_info}
