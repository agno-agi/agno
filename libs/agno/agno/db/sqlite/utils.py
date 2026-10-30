import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agno.db.sqlite.schemas import get_table_schema_definition
from agno.db.utils import (
    OS_METRICS_COUNT_MAP_COLUMNS,
    OS_METRICS_MAX_COLUMNS,
    OS_METRICS_SUM_COLUMNS,
    OS_METRICS_TOKEN_FIELDS,
    empty_os_metrics_totals,
    os_metrics_day_ranges,
    os_metrics_days_to_read,
    os_metrics_nested_run_ids,
)
from agno.utils.log import log_debug, log_error, log_warning

try:
    from sqlalchemy import String, Table, and_, case, cast, func, literal, or_, select, true, union_all
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.engine import Engine
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


# SQLite takes as few as 999 bind parameters per statement, and a stored row's key binds four,
# so IN lists are sent in chunks
OS_METRICS_IN_LIST_LIMIT = 200

# Rows a rebuild reads at a time, so a day or a month of many rows is never held or decoded in one step
OS_METRICS_BATCH_SIZE = 1000

# The values of a stored details object that a model call that served nothing reports, as json_extract reads them
_OS_METRICS_EMPTY_DETAILS = ("{}", "[]", "", "0", "0.0")

# The keys of a stored run that hold the runs nested inside it, in the order the rollup walks them
_OS_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses", "workflow_agent_run")


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


# -- Metrics util methods --


def bulk_upsert_metrics(session: Session, table: Table, metrics_records: list[dict]) -> list[dict]:
    """Bulk upsert metrics into the database.

    Args:
        table (Table): The table to upsert into.
        metrics_records (list[dict]): The metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    results = []
    stmt = sqlite.insert(table)

    # Columns to update in case of conflict
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in ["id", "date", "created_at", "aggregation_period", "user_id"]
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "date", "aggregation_period"], set_=update_columns
    ).returning(table)  # type: ignore
    result = session.execute(stmt, metrics_records)
    results = [row._mapping for row in result.fetchall()]
    session.commit()

    return results  # type: ignore


async def abulk_upsert_metrics(session: AsyncSession, table: Table, metrics_records: list[dict]) -> list[dict]:
    """Bulk upsert metrics into the database.

    Args:
        table (Table): The table to upsert into.
        metrics_records (list[dict]): The metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    results = []
    stmt = sqlite.insert(table)

    # Columns to update in case of conflict
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in ["id", "date", "created_at", "aggregation_period", "user_id"]
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "date", "aggregation_period"], set_=update_columns
    ).returning(table)  # type: ignore
    result = await session.execute(stmt, metrics_records)
    results = [dict(row._mapping) for row in result.fetchall()]
    await session.commit()

    return results  # type: ignore


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[dict]:
    """Calculate metrics for the given single date, bucketed per user.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data to calculate metrics for.

    Returns:
        List[dict]: One metrics record per user_id seen on this date. Sessions without a
            user_id aggregate under the empty-string owner.
    """

    def _empty_metric_record() -> Dict[str, Any]:
        return {
            "users_count": 0,
            "agent_sessions_count": 0,
            "team_sessions_count": 0,
            "workflow_sessions_count": 0,
            "agent_runs_count": 0,
            "team_runs_count": 0,
            "workflow_runs_count": 0,
            "token_metrics": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "audio_total_tokens": 0,
                "audio_input_tokens": 0,
                "audio_output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "reasoning_tokens": 0,
            },
            "model_counts": {},
        }

    session_types = [
        ("agent", "agent_sessions_count", "agent_runs_count"),
        ("team", "team_sessions_count", "team_runs_count"),
        ("workflow", "workflow_sessions_count", "workflow_runs_count"),
    ]

    per_user: Dict[str, Dict[str, Any]] = {}

    for session_type, sessions_count_key, runs_count_key in session_types:
        sessions = sessions_data.get(session_type, []) or []

        for session in sessions:
            bucket_key = session.get("user_id") or ""
            bucket = per_user.setdefault(bucket_key, _empty_metric_record())
            bucket[sessions_count_key] += 1

            # Parse runs from JSON string
            if runs := session.get("runs", []):
                runs = json.loads(runs) if isinstance(runs, str) else runs
                bucket[runs_count_key] += len(runs)
                for run in runs:
                    if model_id := run.get("model"):
                        model_provider = run.get("model_provider", "")
                        key = f"{model_id}:{model_provider}"
                        bucket["model_counts"][key] = bucket["model_counts"].get(key, 0) + 1

            # Parse session_data from JSON string
            session_data = session.get("session_data") or {}
            if isinstance(session_data, str):
                session_data = json.loads(session_data)
            session_metrics = session_data.get("session_metrics") or {}
            for field in bucket["token_metrics"]:
                bucket["token_metrics"][field] += session_metrics.get(field, 0)

    current_time = int(time.time())
    completed = date_to_process < datetime.now(timezone.utc).date()

    records: List[dict] = []
    for user_id, bucket in per_user.items():
        model_metrics = []
        for model, count in bucket["model_counts"].items():
            model_id, model_provider = model.rsplit(":", 1)
            model_metrics.append({"model_id": model_id, "model_provider": model_provider, "count": count})

        # The unowned bucket has no user to count, so summing rows still gives the distinct user count.
        users_count = 0 if user_id == "" else 1

        records.append(
            {
                "id": str(uuid4()),
                "date": date_to_process,
                "completed": completed,
                "token_metrics": bucket["token_metrics"],
                "model_metrics": model_metrics,
                "created_at": current_time,
                "updated_at": current_time,
                "aggregation_period": "daily",
                "user_id": user_id,
                "users_count": users_count,
                "agent_sessions_count": bucket["agent_sessions_count"],
                "team_sessions_count": bucket["team_sessions_count"],
                "workflow_sessions_count": bucket["workflow_sessions_count"],
                "agent_runs_count": bucket["agent_runs_count"],
                "team_runs_count": bucket["team_runs_count"],
                "workflow_runs_count": bucket["workflow_runs_count"],
            }
        )

    return records


def fetch_all_sessions_data(
    sessions: List[Dict[str, Any]], dates_to_process: list[date], start_timestamp: int
) -> Optional[dict]:
    """Return all session data for the given dates, for all session types.

    Args:
        dates_to_process (list[date]): The dates to fetch session data for.

    Returns:
        dict: A dictionary with dates as keys and session data as values, for all session types.

    Example:
    {
        "2000-01-01": {
            "agent": [<session1>, <session2>, ...],
            "team": [...],
            "workflow": [...],
        }
    }
    """
    if not dates_to_process:
        return None

    all_sessions_data: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        date_to_process.isoformat(): {"agent": [], "team": [], "workflow": []} for date_to_process in dates_to_process
    }

    for session in sessions:
        session_date = (
            datetime.fromtimestamp(session.get("created_at", start_timestamp), tz=timezone.utc).date().isoformat()
        )
        if session_date in all_sessions_data:
            all_sessions_data[session_date][session["session_type"]].append(session)

    return all_sessions_data


def get_dates_to_calculate_metrics_for(starting_date: date) -> list[date]:
    """Return the list of dates to calculate metrics for.

    Args:
        starting_date (date): The starting date to calculate metrics for.

    Returns:
        list[date]: The list of dates to calculate metrics for.
    """
    today = datetime.now(timezone.utc).date()
    days_diff = (today - starting_date).days + 1
    if days_diff <= 0:
        return []
    return [starting_date + timedelta(days=x) for x in range(days_diff)]


# -- OS metrics util methods --


def begin_os_metrics_rebuild(session: Session, wait_for_rebuild: bool) -> bool:
    """Begin the session's transaction as the only writer of the database, so one rebuild runs at a time.

    SQLite has no lock of its own a transaction can take, so the rebuild takes the database's write lock with
    BEGIN IMMEDIATE. It is released when the transaction ends.

    Args:
        session (Session): The session to begin, before any other statement of its transaction.
        wait_for_rebuild (bool): Wait for a writer that holds the lock, as long as the connection's busy timeout.
            When False, return at once instead.

    Returns:
        bool: Whether the transaction holds the lock.
    """
    if wait_for_rebuild:
        session.execute(text("BEGIN IMMEDIATE"))
        return True

    busy_timeout = session.execute(text("PRAGMA busy_timeout")).scalar_one()
    try:
        session.execute(text("PRAGMA busy_timeout = 0"))
        session.execute(text("BEGIN IMMEDIATE"))
    except OperationalError as e:
        if "database is locked" not in str(e):
            raise
        return False
    finally:
        session.execute(text(f"PRAGMA busy_timeout = {int(busy_timeout)}"))
    return True


async def abegin_os_metrics_rebuild(session: AsyncSession, wait_for_rebuild: bool) -> bool:
    """Begin the session's transaction as the only writer of the database, so one rebuild runs at a time.

    SQLite has no lock of its own a transaction can take, so the rebuild takes the database's write lock with
    BEGIN IMMEDIATE. It is released when the transaction ends.

    Args:
        session (AsyncSession): The session to begin, before any other statement of its transaction.
        wait_for_rebuild (bool): Wait for a writer that holds the lock, as long as the connection's busy timeout.
            When False, return at once instead.

    Returns:
        bool: Whether the transaction holds the lock.
    """
    if wait_for_rebuild:
        await session.execute(text("BEGIN IMMEDIATE"))
        return True

    busy_timeout = (await session.execute(text("PRAGMA busy_timeout"))).scalar_one()
    try:
        await session.execute(text("PRAGMA busy_timeout = 0"))
        await session.execute(text("BEGIN IMMEDIATE"))
    except OperationalError as e:
        if "database is locked" not in str(e):
            raise
        return False
    finally:
        await session.execute(text(f"PRAGMA busy_timeout = {int(busy_timeout)}"))
    return True


def bulk_upsert_os_metrics(session: Session, table: Table, os_metrics_records: list[dict]) -> None:
    """Bulk upsert OS metrics into the database, in the session's transaction.

    Args:
        session (Session): The session to upsert with.
        table (Table): The table to upsert into.
        os_metrics_records (list[dict]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    stmt = sqlite.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name
        not in [
            "aggregation_period",
            "date",
            "user_id",
            "component_type",
            "component_id",
            "parent_component_id",
            "created_at",
        ]
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=[
            "aggregation_period",
            "date",
            "user_id",
            "component_type",
            "component_id",
            "parent_component_id",
        ],
        set_=update_columns,
    )
    # No RETURNING: no caller reads the rows back
    session.execute(stmt, os_metrics_records)


async def abulk_upsert_os_metrics(session: AsyncSession, table: Table, os_metrics_records: list[dict]) -> None:
    """Bulk upsert OS metrics into the database, in the session's transaction.

    Args:
        session (AsyncSession): The session to upsert with.
        table (Table): The table to upsert into.
        os_metrics_records (list[dict]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    stmt = sqlite.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name
        not in [
            "aggregation_period",
            "date",
            "user_id",
            "component_type",
            "component_id",
            "parent_component_id",
            "created_at",
        ]
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=[
            "aggregation_period",
            "date",
            "user_id",
            "component_type",
            "component_id",
            "parent_component_id",
        ],
        set_=update_columns,
    )
    # No RETURNING: no caller reads the rows back
    await session.execute(stmt, os_metrics_records)


def _os_metrics_totals_upsert(table: Table, totals_row: Dict[str, Any]) -> Any:
    """Build the upsert of an OS metrics totals row.

    A new row starts at version 1, and every write of a stored one moves its version by one in the same
    statement, so two writers never give it the same version.

    Args:
        table (Table): The OS metrics totals table.
        totals_row (Dict[str, Any]): The row, from build_os_metrics_totals_row.

    Returns:
        The upsert statement.
    """
    stmt = sqlite.insert(table).values({**totals_row, "version": 1})

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns: Dict[str, Any] = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in ["aggregation_period", "date", "created_at", "version"]
    }
    update_columns["version"] = table.c.version + 1

    return stmt.on_conflict_do_update(index_elements=["aggregation_period", "date"], set_=update_columns)


def upsert_os_metrics_totals_row(session: Session, table: Table, totals_row: Dict[str, Any]) -> None:
    """Upsert an OS metrics totals row into the database, in the session's transaction.

    Args:
        session (Session): The session to upsert with.
        table (Table): The table to upsert into.
        totals_row (Dict[str, Any]): The row, from build_os_metrics_totals_row.
    """
    session.execute(_os_metrics_totals_upsert(table, totals_row))


async def aupsert_os_metrics_totals_row(session: AsyncSession, table: Table, totals_row: Dict[str, Any]) -> None:
    """Upsert an OS metrics totals row into the database, in the session's transaction.

    Args:
        session (AsyncSession): The session to upsert with.
        table (Table): The table to upsert into.
        totals_row (Dict[str, Any]): The row, from build_os_metrics_totals_row.
    """
    await session.execute(_os_metrics_totals_upsert(table, totals_row))


def _os_metrics_run_metrics(run_data: Any, keys: Sequence[str] = ()) -> Any:
    """Build the metrics of a stored run with only token counts, the given keys and whether details were reported."""
    pairs: List[Any] = []
    for key in list(OS_METRICS_TOKEN_FIELDS) + list(keys):
        pairs.extend([key, func.json_extract(run_data, f"$.metrics.{key}")])
    details = cast(func.json_extract(run_data, "$.metrics.details"), String)
    pairs.extend(["details", case((details.notin_(_OS_METRICS_EMPTY_DETAILS), 1))])
    return func.json_object(*pairs)


def _os_metrics_call_durations(run_data: Any) -> Any:
    """Build every assistant message's request duration, skipping messages carried over from an earlier run: those
    from history, and those a forked run copied from the run it was forked from."""
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


def _os_metrics_nested_runs(run_data: Any, key: Any) -> Any:
    """Build the runs a stored run holds under the given key: a list of runs, or the one run a key holds on its
    own."""
    path = literal("$.") + key
    return func.json_each(
        case(
            (func.json_type(run_data, path) == "object", func.json_array(func.json_extract(run_data, path))),
            else_=func.json_extract(run_data, path),
        )
    ).table_valued("key", "value", "type")


def build_os_metrics_runs_query(table: Table, start_timestamp: int, end_timestamp: int) -> Any:
    """Build the query that reads the runs created in the given time range, with only what OS metrics count.

    Args:
        table (Table): The runs table.
        start_timestamp (int): The start of the range, included.
        end_timestamp (int): The end of the range, not included.

    Returns:
        Any: The query. Of the messages it reads only each request's duration, of the metrics only what
            OS metrics count, and of the runs nested inside a run, at any depth, only the same.
    """
    nested_keys = union_all(
        *[
            select(literal(position).label("position"), literal(key).label("key"))
            for position, key in enumerate(_OS_METRICS_NESTED_RUN_KEYS)
        ]
    ).subquery("nested_keys")
    nested_run = _os_metrics_nested_runs(table.c.run_data, nested_keys.c.key)
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
    nested_run = _os_metrics_nested_runs(nested.c.run_data, nested_keys.c.key)
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
                "metrics",
                _os_metrics_run_metrics(nested.c.run_data),
                "model",
                func.json_extract(nested.c.run_data, "$.model"),
                "model_provider",
                func.json_extract(nested.c.run_data, "$.model_provider"),
                "call_durations",
                func.json(_os_metrics_call_durations(nested.c.run_data)),
            )
        )
    ).scalar_subquery()
    return select(
        table.c.run_id,
        table.c.run_type,
        table.c.agent_id,
        table.c.team_id,
        table.c.workflow_id,
        table.c.user_id,
        table.c.parent_run_id,
        table.c.status,
        _os_metrics_run_metrics(table.c.run_data, ["duration", "time_to_first_token"]).label("metrics"),
        func.json_extract(table.c.run_data, "$.model").label("model"),
        func.json_extract(table.c.run_data, "$.model_provider").label("model_provider"),
        _os_metrics_call_durations(table.c.run_data).label("call_durations"),
        nested_runs.label("nested_runs"),
    ).where(
        table.c.created_at >= start_timestamp,
        table.c.created_at < end_timestamp,
        # A run copied into a forked session repeats a run counted in the session it was made in
        func.json_extract(table.c.run_data, "$.forked_from_session_id").is_(None),
    )


def build_os_metrics_run(row: Any) -> Dict[str, Any]:
    """Build a run in its stored shape from a row of the OS metrics runs query.

    Args:
        row (Any): A row of build_os_metrics_runs_query.

    Returns:
        Dict[str, Any]: The run, with the run_data calculate_date_os_metrics reads.
    """
    run = dict(row._mapping)
    # SQLite returns the JSON objects and arrays a query builds as text
    nested_runs = json.loads(run.pop("nested_runs") or "[]")
    run["run_data"] = {
        "metrics": json.loads(run.pop("metrics")),
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


def build_os_metrics_runs(rows: Sequence[Any]) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Build the runs of a day in their stored shape from the rows of the OS metrics runs query.

    Args:
        rows (Sequence[Any]): The rows of build_os_metrics_runs_query.

    Returns:
        Tuple[List[Dict[str, Any]], Set[str]]: The runs, and the ids of every run nested inside them.
    """
    runs = [build_os_metrics_run(row) for row in rows]
    return runs, os_metrics_nested_run_ids(runs)


def build_os_metrics_totals_queries(
    table: Table,
    starting_date: date,
    ending_date: date,
    user_id: Optional[str],
    fields: Sequence[str],
    month_starts: Sequence[date] = (),
) -> Dict[str, Any]:
    """Build the queries that total the OS metrics of each day in the given date range.

    Args:
        table (Table): The OS metrics totals table to total every user, or the OS metrics table to total one.
        starting_date (date): The first day to total.
        ending_date (date): The last day to total.
        user_id (Optional[str]): The user whose OS metrics rows are totalled. ``None`` for the totals table.
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
        for first_day, last_day in os_metrics_day_ranges(
            os_metrics_days_to_read(starting_date, ending_date, month_starts)
        )
    ]
    filters = []
    if day_ranges:
        filters.append(and_(table.c.aggregation_period == "daily", or_(*day_ranges)))
    if month_starts:
        filters.append(and_(table.c.aggregation_period == "monthly", table.c.date.in_(month_starts)))
    if not filters:
        return {}
    where = or_(*filters)
    if user_id is not None:
        where = and_(table.c.user_id == user_id, where)

    totals = [func.max(table.c.updated_at).label("updated_at")]
    for field in fields:
        if field in OS_METRICS_SUM_COLUMNS:
            totals.append(func.sum(table.c[field]).label(field))
        elif field in OS_METRICS_MAX_COLUMNS:
            totals.append(func.max(table.c[field]).label(field))
    queries: Dict[str, Any] = {"totals": select(table.c.date, *totals).where(where).group_by(table.c.date)}

    # Each key of a map of counts totalled on its own
    count_map_queries = []
    for field in fields:
        if field in OS_METRICS_COUNT_MAP_COLUMNS:
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
        model = func.json_each(table.c.model_metrics).table_valued("value")
        model_id = func.json_extract(model.c.value, "$.model_id").label("model_id")
        model_provider = func.json_extract(model.c.value, "$.model_provider").label("model_provider")
        queries["model_metrics"] = (
            select(
                table.c.date,
                model_id,
                model_provider,
                func.sum(func.json_extract(model.c.value, "$.count")).label("count"),
            )
            .select_from(table.join(model, true()))
            .where(where)
            .group_by(table.c.date, model_id, model_provider)
        )

    return queries


def build_os_metrics_totals(
    fields: Sequence[str],
    rows_by_query: Dict[str, Sequence[Any]],
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Build the OS metrics totals of each date from the rows of the totals queries.

    Args:
        fields (Sequence[str]): The columns that were totalled.
        rows_by_query (Dict[str, Sequence[Any]]): The rows of each query of build_os_metrics_totals_queries.

    Returns:
        Tuple[List[Dict[str, Any]], Optional[int]]: One dict per date, oldest first, and when the rows were
            last updated. A month totalled from its month row is one dict, dated its first day.
    """
    totals_by_date: Dict[date, Dict[str, Any]] = {}
    latest_updated_at: Optional[int] = None
    for row in rows_by_query.get("totals", []):
        day_totals: Dict[str, Any] = {"date": row.date, **empty_os_metrics_totals(fields)}
        for field in fields:
            if field in OS_METRICS_SUM_COLUMNS:
                day_totals[field] = int(getattr(row, field) or 0)
            elif field in OS_METRICS_MAX_COLUMNS and getattr(row, field) is not None:
                day_totals[field] = int(getattr(row, field))
        totals_by_date[row.date] = day_totals
        if row.updated_at is not None and (latest_updated_at is None or row.updated_at > latest_updated_at):
            latest_updated_at = row.updated_at

    for row in rows_by_query.get("count_maps", []):
        totals_by_date[row.date][row.field][row.key] = int(row.count)

    for row in rows_by_query.get("additional_metrics", []):
        # A whole number comes back a whole number
        value = int(row.value) if row.value == int(row.value) else float(row.value)
        totals_by_date[row.date]["additional_metrics"][row.key] = value

    for row in sorted(rows_by_query.get("model_metrics", []), key=lambda x: (x.model_id, x.model_provider)):
        totals_by_date[row.date]["model_metrics"].append(
            {"model_id": row.model_id, "model_provider": row.model_provider, "count": int(row.count)}
        )

    return [totals_by_date[day] for day in sorted(totals_by_date)], latest_updated_at
