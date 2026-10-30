"""Utility functions for the MySQL database class."""

import hashlib
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import uuid4

from agno.db.mysql.schemas import get_table_schema_definition
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
    from sqlalchemy import (
        JSON,
        BigInteger,
        Engine,
        Integer,
        Numeric,
        Table,
        and_,
        cast,
        func,
        literal,
        literal_column,
        or_,
        select,
        true,
        union_all,
    )
    from sqlalchemy.dialects import mysql
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


# MySQL caps a statement at max_allowed_packet, so IN lists are sent in chunks
OS_METRICS_IN_LIST_LIMIT = 10000

# MySQL scans the whole table for a long IN list of row values, so stale rows are deleted in smaller chunks
OS_METRICS_STALE_KEYS_LIMIT = 1000

# Rows a rebuild reads at a time, so a day or a month of many rows is never held or decoded in one step
OS_METRICS_BATCH_SIZE = 1000

# Every assistant message's position, role, whether it was carried over from an earlier run, and its request duration
_OS_METRICS_MESSAGES: Any = literal_column(
    "'$.messages[*]' COLUMNS (position FOR ORDINALITY, role VARCHAR(32) PATH '$.role', "
    "from_history JSON PATH '$.from_history', duration JSON PATH '$.metrics.duration')"
)

# The values of a stored details object that a model call that served nothing reports, as text
_OS_METRICS_EMPTY_DETAILS = ("{}", "[]", '""', "0", "false", "null")

# The keys of a stored run that hold the runs nested inside it, in the order the rollup walks them
_OS_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses", "workflow_agent_run")

# Every run of one of those lists, with its position in the list
_OS_METRICS_NESTED_RUNS: Any = literal_column("'$[*]' COLUMNS (ordinality FOR ORDINALITY, value JSON PATH '$')")

# The one run a key holds on its own. MySQL's $[*] matches nothing in an object
_OS_METRICS_NESTED_RUN: Any = literal_column("'$' COLUMNS (ordinality FOR ORDINALITY, value JSON PATH '$')")

# Every key of a JSON object
_OS_METRICS_KEYS: Any = literal_column("'$[*]' COLUMNS (entry_key VARCHAR(255) PATH '$')")

# Every model of model_metrics
_OS_METRICS_MODELS: Any = literal_column(
    "'$[*]' COLUMNS ("
    "model_id VARCHAR(512) PATH '$.model_id', "
    "model_provider VARCHAR(512) PATH '$.model_provider', "
    "model_count BIGINT PATH '$.count')"
)

# The JSON_TYPE of a JSON number
_OS_METRICS_NUMBER_TYPES = ("INTEGER", "UNSIGNED INTEGER", "DOUBLE", "DECIMAL")


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


# -- Metrics util methods --
def bulk_upsert_metrics(session: Session, table: Table, metrics_records: list[dict]) -> list[dict]:
    """Bulk upsert metrics into the database.

    Args:
        session (Session): The SQLAlchemy session
        table (Table): The table to upsert into.
        metrics_records (list[dict]): The metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    results = []

    # MySQL doesn't support returning in the same way as PostgreSQL
    # We'll need to insert/update and then fetch the records
    for record in metrics_records:
        stmt = mysql.insert(table).values(record)

        # Columns to update in case of conflict. user_id is part of the unique key, so it is never overwritten.
        update_dict = {
            col.name: record.get(col.name)
            for col in table.columns
            if col.name not in ["id", "date", "created_at", "aggregation_period", "user_id"] and col.name in record
        }

        stmt = stmt.on_duplicate_key_update(**update_dict)
        session.execute(stmt)

    # No commit here: the caller owns the transaction, and committing would close it before the SELECT below.

    # Fetch the updated records
    from sqlalchemy import and_, select

    for record in metrics_records:
        select_stmt = select(table).where(
            and_(
                table.c.user_id == record["user_id"],
                table.c.date == record["date"],
                table.c.aggregation_period == record["aggregation_period"],
            )
        )
        result = session.execute(select_stmt).fetchone()
        if result:
            results.append(result._mapping)

    return results  # type: ignore


async def abulk_upsert_metrics(session: AsyncSession, table: Table, metrics_records: list[dict]) -> list[dict]:
    """Async bulk upsert metrics into the database.

    Args:
        session (AsyncSession): The async SQLAlchemy session
        table (Table): The table to upsert into.
        metrics_records (list[dict]): The metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    results = []

    # MySQL doesn't support returning in the same way as PostgreSQL
    # We'll need to insert/update and then fetch the records
    for record in metrics_records:
        stmt = mysql.insert(table).values(record)

        # Columns to update in case of conflict. user_id is part of the unique key, so it is never overwritten.
        update_dict = {
            col.name: record.get(col.name)
            for col in table.columns
            if col.name not in ["id", "date", "created_at", "aggregation_period", "user_id"] and col.name in record
        }

        stmt = stmt.on_duplicate_key_update(**update_dict)
        await session.execute(stmt)

    # Fetch the updated records
    from sqlalchemy import and_, select

    for record in metrics_records:
        select_stmt = select(table).where(
            and_(
                table.c.user_id == record["user_id"],
                table.c.date == record["date"],
                table.c.aggregation_period == record["aggregation_period"],
            )
        )
        result = await session.execute(select_stmt)
        fetched_row = result.fetchone()
        if fetched_row:
            results.append(dict(fetched_row._mapping))

    return results


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[dict]:
    """Calculate metrics for the given single date, bucketed per ``user_id``.

    Sessions without a ``user_id`` aggregate under the empty-string bucket.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data to calculate metrics for.

    Returns:
        List[dict]: The calculated metrics, one record per user.
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

            runs = session.get("runs", []) or []
            bucket[runs_count_key] += len(runs)
            for run in runs:
                if model_id := run.get("model"):
                    model_provider = run.get("model_provider", "")
                    key = f"{model_id}:{model_provider}"
                    bucket["model_counts"][key] = bucket["model_counts"].get(key, 0) + 1

            session_metrics = (session.get("session_data") or {}).get("session_metrics", {}) or {}
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
def os_metrics_lock_name(table_name: str) -> str:
    """Named-lock key serializing the OS metrics rebuilds of one table. Hashed because MySQL caps lock names at
    64 characters and every database of the server shares them."""
    return "agno_os_metrics_" + hashlib.md5(table_name.encode()).hexdigest()


def bulk_upsert_os_metrics(session: Session, table: Table, os_metrics_records: list[dict]) -> None:
    """Bulk upsert OS metrics into the database, in the session's transaction.

    Args:
        session (Session): The session to upsert with.
        table (Table): The table to upsert into.
        os_metrics_records (list[dict]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    stmt = mysql.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns = {
        col.name: stmt.inserted[col.name]
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

    stmt = stmt.on_duplicate_key_update(**update_columns)
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

    stmt = mysql.insert(table)

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns = {
        col.name: stmt.inserted[col.name]
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

    stmt = stmt.on_duplicate_key_update(**update_columns)
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
    stmt = mysql.insert(table).values({**totals_row, "version": 1})

    # Columns to update in case of conflict. The conflict key and created_at are never overwritten.
    update_columns: Dict[str, Any] = {
        col.name: stmt.inserted[col.name]
        for col in table.columns
        if col.name not in ["aggregation_period", "date", "created_at", "version"]
    }
    update_columns["version"] = table.c.version + 1

    return stmt.on_duplicate_key_update(**update_columns)


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
    details = cast(func.json_extract(run_data, "$.metrics.details"), mysql.CHAR)
    pairs.extend(["details", details.notin_(_OS_METRICS_EMPTY_DETAILS)])
    return func.json_object(*pairs, type_=JSON)


def _os_metrics_call_durations(run_data: Any) -> Any:
    """Build every assistant message's request duration, skipping messages carried over from an earlier run: those
    from history, and those a forked run copied from the run it was forked from."""
    message = func.json_table(run_data, _OS_METRICS_MESSAGES).table_valued(
        "position", "role", "from_history", "duration"
    )
    skip = func.coalesce(cast(func.json_extract(run_data, "$.forked_from_message_index"), Integer), 0)
    return (
        select(func.json_arrayagg(message.c.duration, type_=JSON))
        .where(
            message.c.position > skip,
            message.c.role == "assistant",
            or_(message.c.from_history.is_(None), message.c.from_history == literal_column("CAST('false' AS JSON)")),
        )
        .scalar_subquery()
    )


def _os_metrics_nested_run(path: Any, depth: Any, key: str, run_data: Any) -> Any:
    """Build a run nested inside a stored run with only what OS metrics count, and where it sits.

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
        "metrics",
        _os_metrics_run_metrics(run_data),
        "model",
        func.json_extract(run_data, "$.model"),
        "model_provider",
        func.json_extract(run_data, "$.model_provider"),
        "call_durations",
        _os_metrics_call_durations(run_data),
        type_=JSON,
    )


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
    # One row per nested run, read a level at a time. The path orders them the way the rollup walks them
    nested_selects = []
    for position, key in enumerate(_OS_METRICS_NESTED_RUN_KEYS):
        nested_run = func.json_table(
            func.json_extract(table.c.run_data, f"$.{key}"),
            _OS_METRICS_NESTED_RUN if key == "workflow_agent_run" else _OS_METRICS_NESTED_RUNS,
        ).table_valued("ordinality", "value")
        path: Any = cast(func.concat(str(position), func.lpad(nested_run.c.ordinality, 9, "0")), mysql.CHAR(1000))
        nested_selects.append(
            select(
                table.c.run_id.label("parent_run_id"),
                path.label("path"),
                literal(1).label("depth"),
                nested_run.c.value.label("run_data"),
                _os_metrics_nested_run(path, 1, key, nested_run.c.value).label("nested_run"),
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
    for position, key in enumerate(_OS_METRICS_NESTED_RUN_KEYS):
        nested_run = func.json_table(
            func.json_extract(nested.c.run_data, f"$.{key}"),
            _OS_METRICS_NESTED_RUN if key == "workflow_agent_run" else _OS_METRICS_NESTED_RUNS,
        ).table_valued("ordinality", "value")
        path = func.concat(nested.c.path, str(position), func.lpad(nested_run.c.ordinality, 9, "0"))
        nested_selects.append(
            select(
                nested.c.parent_run_id,
                path,
                nested.c.depth + 1,
                nested_run.c.value,
                _os_metrics_nested_run(path, nested.c.depth + 1, key, nested_run.c.value),
            )
            .select_from(nested.join(nested_run, true()))
            .where(func.json_type(nested_run.c.value) == "OBJECT")
        )
    nested = nested.union_all(*nested_selects)
    nested_runs = (
        select(
            nested.c.parent_run_id,
            # JSON_ARRAYAGG takes no ORDER BY, so each run carries its path and build_os_metrics_run orders them
            func.json_arrayagg(nested.c.nested_run, type_=JSON).label("nested_runs"),
        )
        .group_by(nested.c.parent_run_id)
        .subquery("nested_runs")
    )
    return (
        select(
            table.c.run_id,
            table.c.run_type,
            table.c.agent_id,
            table.c.team_id,
            table.c.workflow_id,
            table.c.user_id,
            table.c.parent_run_id,
            table.c.status,
            _os_metrics_run_metrics(table.c.run_data, ["duration", "time_to_first_token"]).label("metrics"),
            func.json_extract(table.c.run_data, "$.model", type_=JSON).label("model"),
            func.json_extract(table.c.run_data, "$.model_provider", type_=JSON).label("model_provider"),
            _os_metrics_call_durations(table.c.run_data).label("call_durations"),
            nested_runs.c.nested_runs,
        )
        .select_from(table.outerjoin(nested_runs, nested_runs.c.parent_run_id == table.c.run_id))
        .where(
            table.c.created_at >= start_timestamp,
            table.c.created_at < end_timestamp,
            # A run copied into a forked session repeats a run counted in the session it was made in
            func.json_extract(table.c.run_data, "$.forked_from_session_id").is_(None),
        )
    )


def build_os_metrics_run(row: Any) -> Dict[str, Any]:
    """Build a run in its stored shape from a row of the OS metrics runs query.

    Args:
        row (Any): A row of build_os_metrics_runs_query.

    Returns:
        Dict[str, Any]: The run, with the run_data calculate_date_os_metrics reads.
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


def build_os_metrics_runs(rows: Sequence[Any]) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Build the runs of a day in their stored shape from the rows of the OS metrics runs query.

    Args:
        rows (Sequence[Any]): The rows of build_os_metrics_runs_query.

    Returns:
        Tuple[List[Dict[str, Any]], Set[str]]: The runs, and the ids of every run nested inside them.
    """
    runs = [build_os_metrics_run(row) for row in rows]
    return runs, os_metrics_nested_run_ids(runs)


def _os_metrics_entries(column: Any) -> Any:
    """Build the key of every entry of a JSON object column, one row each."""
    return func.json_table(func.json_keys(column), _OS_METRICS_KEYS).table_valued("entry_key")


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
    # Days that follow one another are looked up as one range
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

    # Each key of a map of counts totalled on its own. MySQL has no function listing an object's key and value
    # pairs, so its keys are listed and each value is read by its key
    count_map_queries = []
    for field in fields:
        if field in OS_METRICS_COUNT_MAP_COLUMNS:
            entry = _os_metrics_entries(table.c[field])
            # Binary collation keeps string comparisons case-sensitive, matching other SQL backends.
            entry_key = entry.c.entry_key.collate("utf8mb4_bin")
            count = func.json_extract(table.c[field], func.concat('$."', entry.c.entry_key, '"'))
            count_map_queries.append(
                select(
                    table.c.date,
                    literal(field).label("field"),
                    entry_key.label("key"),
                    func.sum(cast(count, BigInteger)).label("count"),
                )
                .select_from(table.join(entry, true()))
                .where(where)
                .group_by(table.c.date, entry_key)
            )
    if count_map_queries:
        queries["count_maps"] = union_all(*count_map_queries)

    # Only the numbers of additional_metrics are totalled; the rest keeps no meaning across rows
    if "additional_metrics" in fields:
        entry = _os_metrics_entries(table.c.additional_metrics)
        entry_key = entry.c.entry_key.collate("utf8mb4_bin")
        value = func.json_extract(table.c.additional_metrics, func.concat('$."', entry.c.entry_key, '"'))
        queries["additional_metrics"] = (
            select(
                table.c.date,
                entry_key.label("key"),
                func.sum(cast(value, Numeric(65, 30))).label("value"),
            )
            .select_from(table.join(entry, true()))
            .where(where, func.json_type(value).in_(_OS_METRICS_NUMBER_TYPES))
            .group_by(table.c.date, entry_key)
        )

    if "model_metrics" in fields:
        model = func.json_table(table.c.model_metrics, _OS_METRICS_MODELS).table_valued(
            "model_id", "model_provider", "model_count"
        )
        model_id = model.c.model_id.collate("utf8mb4_bin")
        model_provider = model.c.model_provider.collate("utf8mb4_bin")
        queries["model_metrics"] = (
            select(
                table.c.date,
                model_id.label("model_id"),
                model_provider.label("model_provider"),
                func.sum(model.c.model_count).label("count"),
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
