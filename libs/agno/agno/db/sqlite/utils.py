import json
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agno.db.sqlite.schemas import get_table_schema_definition
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
        BigInteger,
        Float,
        Table,
        Text,
        and_,
        case,
        cast,
        false,
        func,
        literal,
        or_,
        select,
        true,
        union_all,
        update,
    )
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.engine import Engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


# SQLite takes as few as 999 bind parameters per statement, so IN lists are sent in chunks
METRICS_IN_LIST_LIMIT = 900

# A stored row's key binds five parameters, so stale rows are deleted 150 at a time
METRICS_STALE_KEYS_LIMIT = 150

# The keys of a stored run that hold the runs nested inside it, in the order the rollup walks them
_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses", "workflow_agent_run")


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


def is_table_available(session: Session, table_name: str, db_schema: Optional[str] = None) -> bool:
    """
    Check if a table with the given name exists.
    Note: db_schema parameter is ignored in SQLite but kept for API compatibility.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        # SQLite uses sqlite_master instead of information_schema
        exists_query = text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table")
        exists = session.execute(exists_query, {"table": table_name}).scalar() is not None
        return exists
    except Exception as e:
        log_error(f"Error checking if table exists: {str(e)}")
        return False


async def ais_table_available(session: AsyncSession, table_name: str, db_schema: Optional[str] = None) -> bool:
    """
    Check if a table with the given name exists.
    Note: db_schema parameter is ignored in SQLite but kept for API compatibility.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        exists_query = text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table")
        exists = (await session.execute(exists_query, {"table": table_name})).scalar() is not None
        return exists
    except Exception as e:
        log_error(f"Error checking if table exists: {str(e)}")
        return False


def is_valid_table(db_engine: Engine, table_name: str, table_type: str) -> bool:
    """
    Check if the existing table has the expected column names.

    Args:
        db_engine (Engine): Database engine
        table_name (str): Name of the table to validate
        table_type (str): Type of table to get expected schema

    Returns:
        bool: True if table has all expected columns, False if expected columns are missing

    Raises:
        Any error from inspecting the table, so a failed inspection is not read as a stale schema.
    """
    try:
        expected_table_schema = get_table_schema_definition(table_type)
        expected_columns = {col_name for col_name in expected_table_schema.keys() if not col_name.startswith("_")}

        # Get existing columns (no schema parameter for SQLite)
        inspector = inspect(db_engine)
        existing_columns_info = inspector.get_columns(table_name)  # No schema parameter
        existing_columns = set(col["name"] for col in existing_columns_info)

        # Check if all expected columns exist
        missing_columns = expected_columns - existing_columns
        if missing_columns:
            log_warning(f"Missing columns {missing_columns} in table {table_name}")
            return False

        return True
    except Exception as e:
        log_error(f"Error validating table schema for {table_name}: {str(e)}")
        raise


async def ais_valid_table(db_engine: AsyncEngine, table_name: str, table_type: str) -> bool:
    """
    Check if the existing table has the expected column names.

    Args:
        db_engine (Engine): Database engine
        table_name (str): Name of the table to validate
        table_type (str): Type of table to get expected schema

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
            existing_columns = await conn.run_sync(_get_table_columns, table_name)

        missing_columns = expected_columns - existing_columns
        if missing_columns:
            log_warning(f"Missing columns {missing_columns} in table {table_name}")
            return False

        return True

    except Exception as e:
        log_error(f"Error validating table schema for {table_name}: {str(e)}")
        raise


def _get_table_columns(conn, table_name: str) -> set[str]:
    """Helper function to get table columns using sync inspector."""
    inspector = inspect(conn)
    columns_info = inspector.get_columns(table_name)
    return {col["name"] for col in columns_info}


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

    stmt = sqlite.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in [*COMPONENT_METRICS_KEY_COLUMNS, "created_at"]
    }

    stmt = stmt.on_conflict_do_update(index_elements=list(COMPONENT_METRICS_KEY_COLUMNS), set_=update_columns)
    # No RETURNING: no caller reads the rows back
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

    stmt = sqlite.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in [*COMPONENT_METRICS_KEY_COLUMNS, "created_at"]
    }

    stmt = stmt.on_conflict_do_update(index_elements=list(COMPONENT_METRICS_KEY_COLUMNS), set_=update_columns)
    # No RETURNING: no caller reads the rows back
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
    stmt = sqlite.insert(table).values({**aggregate_metrics_row, "version": 1})

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns: Dict[str, Any] = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in [*AGGREGATE_METRICS_KEY_COLUMNS, "created_at", "version"]
    }
    update_columns["version"] = table.c.version + 1
    # Compared in the statement, so a reopen written since the version was read keeps the period open
    update_columns["completed"] = (
        and_(table.c.version == read_version, stmt.excluded.completed) if read_version is not None else false()
    )

    return stmt.on_conflict_do_update(index_elements=list(AGGREGATE_METRICS_KEY_COLUMNS), set_=update_columns)


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
    stmt = sqlite.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns: Dict[str, Any] = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in [*AGGREGATE_METRICS_KEY_COLUMNS, "created_at", "version"]
    }
    update_columns["version"] = table.c.version + 1
    # No RETURNING: no caller reads the rows back
    return stmt.on_conflict_do_update(index_elements=list(AGGREGATE_METRICS_KEY_COLUMNS), set_=update_columns)


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
    stmt = sqlite.insert(table).values(
        {**build_aggregate_metrics_row([], aggregation_period, row_date, completed=False), "version": 1}
    )
    return stmt.on_conflict_do_update(
        index_elements=list(AGGREGATE_METRICS_KEY_COLUMNS),
        set_={"completed": False, "version": table.c.version + 1},
    )


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


def _reopen_metrics_days_from(table: Table, starting_date: date) -> Any:
    """Build the reopen of every day's everyone row of the aggregate metrics table from the given date on."""
    return (
        update(table)
        .where(table.c.aggregation_period == "daily", table.c.user_id == "", table.c.date >= starting_date)
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
    session.execute(_reopen_metrics_days_from(table, starting_date))


async def areopen_metrics_days_from(session: AsyncSession, table: Table, starting_date: date) -> None:
    """Reopen every day's aggregate metrics row from the given date on, in the session's transaction, as a write reopens
    a day, so the next calculation rebuilds them.

    Args:
        session (AsyncSession): The session to reopen with.
        table (Table): The aggregate metrics table.
        starting_date (date): The first day to reopen.
    """
    await session.execute(_reopen_metrics_days_from(table, starting_date))


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
    """Build each request duration of a stored run, skipping messages carried over from an earlier run: those from
    history, and those a forked run copied from the run it was forked from."""
    message = func.json_each(run_data, "$.messages").table_valued("key", "value")
    duration = func.json_extract(message.c.value, "$.metrics.duration")
    return (
        select(func.json_group_array(duration))
        .where(
            message.c.key >= func.coalesce(func.json_extract(run_data, "$.forked_from_message_index"), 0),
            func.json_extract(message.c.value, "$.role") == "assistant",
            func.coalesce(func.json_extract(message.c.value, "$.from_history"), 0) == 0,
            duration.is_not(None),
        )
        .scalar_subquery()
    )


def _metrics_nested_runs(run_data: Any, key: Any) -> Any:
    """Build the runs a stored run holds under the given key: a list of runs, or the one run a key holds on its
    own."""
    path = literal("$.") + key
    return func.json_each(
        case(
            (func.json_type(run_data, path) == "object", func.json_array(func.json_extract(run_data, path))),
            else_=func.json_extract(run_data, path),
        )
    ).table_valued("key", "value", "type")


def metrics_parent_run_id(table: Table) -> Any:
    """Build the id of the run that started a stored run: its team's or workflow's run, or the run whose tool call
    started it."""
    return func.coalesce(table.c.parent_run_id, func.json_extract(table.c.run_data, "$.called_from_run_id"))


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
    # Read in the database, so a run is never read whole
    nested_keys = union_all(
        *[
            select(literal(position).label("position"), literal(key).label("key"))
            for position, key in enumerate(_METRICS_NESTED_RUN_KEYS)
        ]
    ).subquery("nested_keys")
    nested_run = _metrics_nested_runs(table.c.run_data, nested_keys.c.key)
    # One row per nested run, read a level at a time. The path orders them the way the rollup walks them
    nested = (
        select(
            func.printf("%d%08d", nested_keys.c.position, nested_run.c.key).label("path"),
            literal(1).label("depth"),
            nested_keys.c.key.label("key"),
            nested_run.c.value.label("run_data"),
        )
        .select_from(nested_keys.join(nested_run, true()))
        .where(nested_run.c.type == "object")
        .correlate(table)
        .cte("nested", recursive=True, nesting=True)
    )
    nested_run = _metrics_nested_runs(nested.c.run_data, nested_keys.c.key)
    nested = nested.union_all(
        select(
            func.printf("%s%d%08d", nested.c.path, nested_keys.c.position, nested_run.c.key),
            nested.c.depth + 1,
            nested_keys.c.key,
            nested_run.c.value,
        )
        .select_from(nested.join(nested_keys, true()).join(nested_run, true()))
        .where(nested_run.c.type == "object")
    )
    # SQLite orders no aggregate before 3.44, so each nested run carries its path to be ordered by
    nested_runs = select(
        func.json_group_array(
            func.json_object(
                "path",
                nested.c.path,
                "depth",
                nested.c.depth,
                "key",
                nested.c.key,
                "run_id",
                func.json_extract(nested.c.run_data, "$.run_id"),
                "agent_id",
                func.json_extract(nested.c.run_data, "$.agent_id"),
                "team_id",
                func.json_extract(nested.c.run_data, "$.team_id"),
                "session_id",
                func.json_extract(nested.c.run_data, "$.session_id"),
                "parent_run_id",
                func.json_extract(nested.c.run_data, "$.parent_run_id"),
                "metrics",
                func.json_extract(nested.c.run_data, "$.metrics"),
                "model",
                func.json_extract(nested.c.run_data, "$.model"),
                "model_provider",
                func.json_extract(nested.c.run_data, "$.model_provider"),
                "call_durations",
                func.json(_metrics_call_durations(nested.c.run_data)),
            )
        )
    ).scalar_subquery()
    return select(
        table.c.run_id,
        table.c.session_id,
        table.c.run_type,
        table.c.agent_id,
        table.c.team_id,
        table.c.workflow_id,
        table.c.user_id,
        metrics_parent_run_id(table).label("parent_run_id"),
        table.c.status,
        func.json_extract(table.c.run_data, "$.metrics").label("metrics"),
        func.json_extract(table.c.run_data, "$.model").label("model"),
        func.json_extract(table.c.run_data, "$.model_provider").label("model_provider"),
        _metrics_call_durations(table.c.run_data).label("call_durations"),
        # Walked only for a run with runs nested inside it
        case(
            (
                or_(*[func.json_type(table.c.run_data, f"$.{key}").is_not(None) for key in _METRICS_NESTED_RUN_KEYS]),
                nested_runs,
            )
        ).label("nested_runs"),
        table.c.created_at,
    ).where(
        table.c.created_at >= start_timestamp,
        table.c.created_at < end_timestamp,
        # A run copied into a forked session repeats a run counted in the session it was made in
        func.json_extract(table.c.run_data, "$.forked_from_session_id").is_(None),
    )


def build_component_metrics_legacy_runs_table(
    sessions_table: Table, runs_table: Optional[Table], start_timestamp: int, end_timestamp: int
) -> Optional[Any]:
    """Build the runs not yet migrated out of the sessions table's legacy runs column, in the runs table's shape.

    Args:
        sessions_table (Table): The sessions table.
        runs_table (Optional[Table]): The runs table. A run it also holds is read from there.
        start_timestamp (int): The start of the range the legacy runs are read for, included.
        end_timestamp (int): The end of that range, not included.

    Returns:
        Optional[Any]: The legacy runs, for build_component_metrics_runs_query. None when there is no legacy runs
            column.
    """
    if "runs" not in sessions_table.c:
        return None

    # Extracted in the database instead of loading the column, as calculate_metrics does
    legacy_runs = sessions_table.c.runs
    legacy_run = func.json_each(
        case(
            (func.json_type(legacy_runs) == "array", legacy_runs),
            else_=func.json_array(),
        )
    ).table_valued("value", "type")
    # As text, the way the runs table stores it
    legacy_run_id = cast(func.json_extract(legacy_run.c.value, "$.run_id"), Text)
    # A legacy run is dated and typed the way the v3.0.0 migration writes it to the runs table
    legacy_runs_stmt = select(
        legacy_run_id.label("run_id"),
        sessions_table.c.session_id,
        case(
            (func.coalesce(func.json_extract(legacy_run.c.value, "$.agent_id"), "") != "", "agent"),
            (func.coalesce(func.json_extract(legacy_run.c.value, "$.team_id"), "") != "", "team"),
            else_="workflow",
        ).label("run_type"),
        func.json_extract(legacy_run.c.value, "$.agent_id").label("agent_id"),
        func.json_extract(legacy_run.c.value, "$.team_id").label("team_id"),
        func.json_extract(legacy_run.c.value, "$.workflow_id").label("workflow_id"),
        sessions_table.c.user_id,
        func.json_extract(legacy_run.c.value, "$.parent_run_id").label("parent_run_id"),
        func.json_extract(legacy_run.c.value, "$.status").label("status"),
        legacy_run.c.value.label("run_data"),
        func.coalesce(
            cast(func.json_extract(legacy_run.c.value, "$.created_at"), BigInteger), sessions_table.c.created_at
        ).label("created_at"),
    ).select_from(sessions_table.join(legacy_run, true()))
    legacy_runs_stmt = legacy_runs_stmt.where(
        # A session holds runs created after it started and before it was last written
        sessions_table.c.created_at < end_timestamp,
        func.coalesce(sessions_table.c.updated_at, sessions_table.c.created_at) >= start_timestamp,
        # The migration skips what is no run
        legacy_run.c.type == "object",
        func.json_extract(legacy_run.c.value, "$.run_id").isnot(None),
    )
    if runs_table is not None:
        # The runs table wins on a run in both, as merge_runs_table_with_legacy_blob does
        legacy_runs_stmt = legacy_runs_stmt.where(
            ~select(runs_table.c.run_id).where(runs_table.c.run_id == legacy_run_id).exists()
        )
    return legacy_runs_stmt.subquery("legacy_runs")


def build_component_metrics_run(row: Any) -> Dict[str, Any]:
    """Build a run in its stored shape from a row of the component metrics runs query.

    Args:
        row (Any): A row of build_component_metrics_runs_query.

    Returns:
        Dict[str, Any]: The run, with the run_data calculate_date_component_metrics reads.
    """
    run = dict(row._mapping)
    # SQLite returns the JSON objects and arrays a query builds as text
    nested_runs = json.loads(run.pop("nested_runs") or "[]")
    run["run_data"] = {
        "metrics": json.loads(run.pop("metrics") or "null"),
        "model": run.pop("model"),
        "model_provider": run.pop("model_provider"),
        "messages": [
            {"role": "assistant", "metrics": {"duration": duration}}
            for duration in json.loads(run.pop("call_durations") or "[]")
        ],
    }
    # A nested run comes after the run it is nested inside, so the last run met at each depth is its parent
    parents = [run["run_data"]]
    for nested_run in sorted(nested_runs, key=lambda x: x["path"]):
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


def _metrics_column(table: Table, field: str) -> Any:
    """Build a column of a metrics row to total: the column itself, its key of token_details for a token count or the
    cost kept there, the total of the audio counts, the sessions of every type, or the runs no other run started."""
    if field == "audio_total_tokens":
        return func.coalesce(_metrics_column(table, "audio_input_tokens"), 0) + func.coalesce(
            _metrics_column(table, "audio_output_tokens"), 0
        )
    if field == "cost":
        return cast(func.json_extract(table.c.token_details, f"$.{field}"), Float)
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
    provider = func.json_each(table.c.model_metrics).table_valued("key", "value")
    model = func.json_each(provider.c.value).table_valued("key", "value")
    return (
        table.join(provider, true()).join(model, true()),
        provider.c.key.label("model_provider"),
        model.c.key.label("model_id"),
        cast(func.json_extract(model.c.value, "$.count"), BigInteger),
        cast(func.json_extract(model.c.value, "$.cost"), Float),
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
    # Days that follow one another are looked up as one range, so a long date range binds a few parameters
    # instead of one per day
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

    # Each key of a map of counts totalled on its own
    count_map_queries = []
    for field in fields:
        if field in METRICS_COUNT_MAP_COLUMNS:
            entry = func.json_each(table.c[field]).table_valued("key", "value")
            count_map_queries.append(
                select(
                    table.c.date,
                    literal(field).label("field"),
                    entry.c.key.label("key"),
                    func.sum(entry.c.value).label("count"),
                )
                .select_from(table.join(entry, true()))
                .where(where)
                .group_by(table.c.date, entry.c.key)
            )
    if count_map_queries:
        queries["count_maps"] = union_all(*count_map_queries)

    # Only the numbers of additional_metrics are totalled; the rest keeps no meaning across rows
    if "additional_metrics" in fields:
        entry = func.json_each(table.c.additional_metrics).table_valued("key", "value", "type")
        queries["additional_metrics"] = (
            select(
                table.c.date,
                entry.c.key.label("key"),
                func.sum(entry.c.value).label("value"),
            )
            .select_from(table.join(entry, true()))
            .where(where, entry.c.type.in_(["integer", "real"]))
            .group_by(table.c.date, entry.c.key)
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
