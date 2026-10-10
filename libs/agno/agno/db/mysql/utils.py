"""Utility functions for the MySQL database class."""

import hashlib
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import uuid4

from agno.db.mysql.schemas import get_table_schema_definition
from agno.db.utils import (
    OS_METRICS_FIXED_KEYS,
    OS_METRICS_STATE_ID,
    build_os_metrics_state,
    build_os_metrics_state_row,
    os_metrics_day_ranges,
    os_metrics_nested_run_ids,
)
from agno.utils.log import log_debug, log_error, log_warning

try:
    from sqlalchemy import (
        JSON,
        BigInteger,
        Engine,
        Select,
        Table,
        and_,
        cast,
        false,
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


# -- OS metrics util methods --

# The values of a stored details object that a model call that served nothing reports, as text
_OS_METRICS_EMPTY_DETAILS = ("{}", "[]", '""', "0", "false", "null")

# In the order the rollup walks them
_OS_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses")

_OS_METRICS_MESSAGES: Any = literal_column(
    "'$.messages[*]' COLUMNS (role VARCHAR(32) PATH '$.role', from_history JSON PATH '$.from_history', "
    "duration JSON PATH '$.metrics.duration')"
)

_OS_METRICS_NESTED_RUNS: Any = literal_column("'$[*]' COLUMNS (ordinality FOR ORDINALITY, value JSON PATH '$')")

# Ids are compared byte for byte: the default collation makes "Alice" and "alice" equal
_OS_METRICS_COLLATION = "utf8mb4_bin"

# Keeps a statement below the packet size the server takes
OS_METRICS_IN_LIST_LIMIT = 10000


def os_metrics_lock_name(table_name: str) -> str:
    """The name of the lock one rebuild of the given OS metrics table holds.

    Hashed, since a lock name takes 64 characters at most and is shared by every database of the server.
    """
    return "agno_os_metrics_" + hashlib.md5(table_name.encode()).hexdigest()


def bulk_upsert_os_metrics(session: Session, table: Table, os_metrics_records: list[dict]) -> None:
    """Bulk upsert OS metrics into the database, in the session's transaction.

    Args:
        session (Session): The SQLAlchemy session
        table (Table): The table to upsert into.
        os_metrics_records (list[dict]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    stmt = mysql.insert(table)

    # Columns to update in case of conflict. The conflict key, id and created_at are never overwritten.
    update_columns = {
        col.name: stmt.inserted[col.name]
        for col in table.columns
        if col.name
        not in [
            "id",
            "created_at",
            "user_id",
            "date",
            "aggregation_period",
            "agent_id",
            "team_id",
            "workflow_id",
            "parent_id",
        ]
    }

    stmt = stmt.on_duplicate_key_update(**update_columns)
    session.execute(stmt, os_metrics_records)


async def abulk_upsert_os_metrics(session: AsyncSession, table: Table, os_metrics_records: list[dict]) -> None:
    """Bulk upsert OS metrics into the database, in the session's transaction.

    Args:
        session (AsyncSession): The async SQLAlchemy session
        table (Table): The table to upsert into.
        os_metrics_records (list[dict]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    stmt = mysql.insert(table)

    # Columns to update in case of conflict. The conflict key, id and created_at are never overwritten.
    update_columns = {
        col.name: stmt.inserted[col.name]
        for col in table.columns
        if col.name
        not in [
            "id",
            "created_at",
            "user_id",
            "date",
            "aggregation_period",
            "agent_id",
            "team_id",
            "workflow_id",
            "parent_id",
        ]
    }

    stmt = stmt.on_duplicate_key_update(**update_columns)
    await session.execute(stmt, os_metrics_records)


def get_stored_os_metrics_state(session: Session, table: Table) -> Dict[str, Any]:
    """Get the state of the OS metrics table, from the state row.

    Args:
        session (Session): The session to read with.
        table (Table): The OS metrics table.

    Returns:
        Dict[str, Any]: The state, as build_os_metrics_state builds it. Empty for a table no rebuild has
            written to.
    """
    state = session.execute(
        select(table.c.updated_at, table.c.metadata).where(table.c.id == OS_METRICS_STATE_ID)
    ).first()
    if state is None:
        return {}
    updated_at, state_metadata = state
    return {**(state_metadata or {}), "updated_at": updated_at}


def update_os_metrics_state(
    session: Session,
    table: Table,
    changed_rows: Sequence[Dict[str, Any]],
    stale_ids: Sequence[str],
    day: Optional[date] = None,
) -> None:
    """Save the state row of the OS metrics table, in the session's transaction.

    Called after a rebuild wrote or deleted rows in the session, so the state moves with them or not at all.

    Args:
        session (Session): The session to save with.
        table (Table): The OS metrics table.
        changed_rows (Sequence[Dict[str, Any]]): The rows the rebuild wrote in the session.
        stale_ids (Sequence[str]): The ids of the rows the rebuild deleted in the session.
        day (Optional[date]): The day the rows are of. ``None`` for the rows of a month.
    """
    previous_state = get_stored_os_metrics_state(session, table)
    state_row = build_os_metrics_state_row(
        build_os_metrics_state(previous_state, int(time.time()), changed_rows, stale_ids, day)
    )
    # The row is found by its id: it is dated the day of the rebuild, and the date is part of the unique key
    stmt = mysql.insert(table).values(state_row)
    stmt = stmt.on_duplicate_key_update(
        **{column: stmt.inserted[column] for column in ["date", "updated_at", "metadata"]}
    )
    session.execute(stmt)


async def aget_stored_os_metrics_state(session: AsyncSession, table: Table) -> Dict[str, Any]:
    """Get the state of the OS metrics table, from the state row.

    Args:
        session (AsyncSession): The session to read with.
        table (Table): The OS metrics table.

    Returns:
        Dict[str, Any]: The state, as build_os_metrics_state builds it. Empty for a table no rebuild has
            written to.
    """
    result = await session.execute(
        select(table.c.updated_at, table.c.metadata).where(table.c.id == OS_METRICS_STATE_ID)
    )
    state = result.first()
    if state is None:
        return {}
    updated_at, state_metadata = state
    return {**(state_metadata or {}), "updated_at": updated_at}


async def aupdate_os_metrics_state(
    session: AsyncSession,
    table: Table,
    changed_rows: Sequence[Dict[str, Any]],
    stale_ids: Sequence[str],
    day: Optional[date] = None,
) -> None:
    """Save the state row of the OS metrics table, in the session's transaction.

    Called after a rebuild wrote or deleted rows in the session, so the state moves with them or not at all.

    Args:
        session (AsyncSession): The session to save with.
        table (Table): The OS metrics table.
        changed_rows (Sequence[Dict[str, Any]]): The rows the rebuild wrote in the session.
        stale_ids (Sequence[str]): The ids of the rows the rebuild deleted in the session.
        day (Optional[date]): The day the rows are of. ``None`` for the rows of a month.
    """
    previous_state = await aget_stored_os_metrics_state(session, table)
    state_row = build_os_metrics_state_row(
        build_os_metrics_state(previous_state, int(time.time()), changed_rows, stale_ids, day)
    )
    # The row is found by its id: it is dated the day of the rebuild, and the date is part of the unique key
    stmt = mysql.insert(table).values(state_row)
    stmt = stmt.on_duplicate_key_update(
        **{column: stmt.inserted[column] for column in ["date", "updated_at", "metadata"]}
    )
    await session.execute(stmt)


def _os_metrics_run_metrics(run_data: Any, keys: Sequence[str] = ()) -> Any:
    """The metrics of a stored run with only what OS metrics count."""
    pairs: List[Any] = []
    for key in (*OS_METRICS_FIXED_KEYS["token_metrics"], *keys):
        pairs.extend([key, func.json_extract(run_data, f"$.metrics.{key}")])
    details = cast(func.json_extract(run_data, "$.metrics.details"), mysql.CHAR)
    pairs.extend(["details", details.notin_(_OS_METRICS_EMPTY_DETAILS)])
    return func.json_object(*pairs)


def _os_metrics_call_durations(run_data: Any) -> Any:
    """Every assistant message's request duration, skipping messages carried over from an earlier run."""
    message = func.json_table(run_data, _OS_METRICS_MESSAGES).table_valued("role", "from_history", "duration")
    return (
        select(func.json_arrayagg(message.c.duration))
        .where(
            message.c.role == "assistant",
            func.json_type(message.c.duration) != "NULL",
            or_(
                message.c.from_history.is_(None),
                func.json_type(message.c.from_history) == "NULL",
                message.c.from_history == literal_column("CAST('false' AS JSON)"),
            ),
        )
        .scalar_subquery()
    )


def build_os_metrics_runs_query(table: Table, start_timestamp: int, end_timestamp: int) -> Select:
    """Build the query that reads the runs created in the given time range, with only what OS metrics count.

    Args:
        table (Table): The runs table.
        start_timestamp (int): The start of the range, included.
        end_timestamp (int): The end of the range, not included.

    Returns:
        Select: The query. Of the messages it reads only each request's duration, of the metrics only what
            OS metrics count, and of the runs nested inside a run, at any depth, only the same.
    """
    # One row per nested run, read a level at a time. The path orders them the way the rollup walks them
    nested_selects = []
    for position, key in enumerate(_OS_METRICS_NESTED_RUN_KEYS):
        nested_run = func.json_table(
            func.json_extract(table.c.run_data, f"$.{key}"), _OS_METRICS_NESTED_RUNS
        ).table_valued("ordinality", "value")
        nested_selects.append(
            select(
                table.c.run_id.label("parent_run_id"),
                cast(func.concat(str(position), func.lpad(nested_run.c.ordinality, 9, "0")), mysql.CHAR(1000)).label(
                    "path"
                ),
                literal(1).label("depth"),
                literal(key).label("key"),
                nested_run.c.value.label("run_data"),
            )
            .select_from(table.join(nested_run, true()))
            .where(
                table.c.created_at >= start_timestamp,
                table.c.created_at < end_timestamp,
                func.json_type(nested_run.c.value) == "OBJECT",
            )
        )
    # The first list starts the recursion, and the other lists follow it ahead of the levels below
    nested = nested_selects[0].cte("nested", recursive=True)
    nested_selects = nested_selects[1:]
    for position, key in enumerate(_OS_METRICS_NESTED_RUN_KEYS):
        nested_run = func.json_table(
            func.json_extract(nested.c.run_data, f"$.{key}"), _OS_METRICS_NESTED_RUNS
        ).table_valued("ordinality", "value")
        nested_selects.append(
            select(
                nested.c.parent_run_id,
                func.concat(nested.c.path, str(position), func.lpad(nested_run.c.ordinality, 9, "0")),
                nested.c.depth + 1,
                literal(key),
                nested_run.c.value,
            )
            .select_from(nested.join(nested_run, true()))
            .where(func.json_type(nested_run.c.value) == "OBJECT")
        )
    nested = nested.union_all(*nested_selects)
    nested_run_rows = select(
        nested.c.parent_run_id,
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
            _os_metrics_call_durations(nested.c.run_data),
        ).label("nested_run"),
    ).subquery("nested_run_rows")
    nested_runs = (
        select(
            nested_run_rows.c.parent_run_id,
            func.json_arrayagg(nested_run_rows.c.nested_run).label("nested_runs"),
        )
        .group_by(nested_run_rows.c.parent_run_id)
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
            _os_metrics_run_metrics(table.c.run_data, ["duration", "time_to_first_token"]).cast(JSON).label("metrics"),
            func.json_extract(table.c.run_data, "$.model", type_=JSON).label("model"),
            func.json_extract(table.c.run_data, "$.model_provider", type_=JSON).label("model_provider"),
            _os_metrics_call_durations(table.c.run_data).cast(JSON).label("call_durations"),
            nested_runs.c.nested_runs.cast(JSON).label("nested_runs"),
        )
        .select_from(table.outerjoin(nested_runs, nested_runs.c.parent_run_id == table.c.run_id))
        .where(table.c.created_at >= start_timestamp, table.c.created_at < end_timestamp)
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
    for nested_run in sorted(nested_runs, key=lambda nested_run: nested_run.pop("path")):
        depth = nested_run.pop("depth")
        nested_run["messages"] = [
            {"role": "assistant", "metrics": {"duration": duration}}
            for duration in nested_run.pop("call_durations") or []
        ]
        parents[depth - 1].setdefault(nested_run.pop("key"), []).append(nested_run)
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


def build_os_metrics_total_dates_query(
    table: Table,
    aggregation_periods: Sequence[str],
    starting_date: Optional[date] = None,
    ending_date: Optional[date] = None,
) -> Select:
    """Build the query that reads which dates have a total row of the given periods.

    Args:
        table (Table): The OS metrics table.
        aggregation_periods (Sequence[str]): "daily_total", "monthly_total" or both.
        starting_date (Optional[date]): The first date to read. ``None`` reads from the first one stored.
        ending_date (Optional[date]): The last date to read. ``None`` reads to the last one stored.

    Returns:
        Select: The query, one row per date and period. A month row is dated the first day of its month.
    """
    conditions = [table.c.user_id == "", table.c.aggregation_period.in_(aggregation_periods)]
    if starting_date is not None:
        conditions.append(table.c.date >= starting_date)
    if ending_date is not None:
        conditions.append(table.c.date <= ending_date)
    return select(table.c.date, table.c.aggregation_period).where(*conditions)


def build_os_metrics_totals_queries(
    table: Table,
    starting_date: date,
    ending_date: date,
    user_id: Optional[str],
    fields: Sequence[str],
    month_starts: Optional[Sequence[date]] = None,
    total_days: Optional[Sequence[date]] = None,
    row_days: Optional[Sequence[date]] = None,
) -> Dict[str, Any]:
    """Build the queries that total the OS metrics rows of each day in the given date range.

    Args:
        table (Table): The OS metrics table.
        starting_date (date): The first day to total.
        ending_date (date): The last day to total.
        user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner.
        fields (Sequence[str]): The columns to total.
        month_starts (Optional[Sequence[date]]): The first day of every month to total from its month rows.
        total_days (Optional[Sequence[date]]): The days to total from their total row.
        row_days (Optional[Sequence[date]]): The days to total from their rows. ``None`` totals every day of
            the date range from its rows.

    Returns:
        Dict[str, Any]: The queries, keyed "totals", "duration_buckets" and "model_metrics".
    """
    conditions = [table.c.aggregation_period == "daily"]
    if row_days is None:
        conditions.extend([table.c.date >= starting_date, table.c.date <= ending_date])
    else:
        # Days that follow one another are looked up as one range
        day_ranges = [
            and_(table.c.date >= first_day, table.c.date <= last_day)
            for first_day, last_day in os_metrics_day_ranges(row_days)
        ]
        conditions.append(or_(false(), *day_ranges))
    if user_id is not None:
        conditions.append(table.c.user_id == user_id)
    # Each period is read by its own SELECT: MySQL walks the whole date index for periods joined by OR
    wheres = [and_(*conditions)]
    if total_days:
        wheres.append(
            and_(table.c.user_id == "", table.c.aggregation_period == "daily_total", table.c.date.in_(total_days))
        )
    if month_starts and user_id is None:
        wheres.append(
            and_(table.c.user_id == "", table.c.aggregation_period == "monthly_total", table.c.date.in_(month_starts))
        )
    elif month_starts:
        wheres.append(
            and_(table.c.user_id == user_id, table.c.aggregation_period == "monthly", table.c.date.in_(month_starts))
        )

    totals = [func.max(table.c.updated_at).label("updated_at")]
    for field in fields:
        if field in ["sessions_count", "runs_count"]:
            totals.append(func.sum(table.c[field]).label(field))
        elif field in OS_METRICS_FIXED_KEYS:
            # Each key of the JSON column totalled on its own, and gathered back into one object
            key_totals: List[Any] = []
            for key in OS_METRICS_FIXED_KEYS[field]:
                value = cast(func.json_extract(table.c[field], f"$.{key}"), BigInteger)
                is_max = key in ["max_duration_ms", "max_time_to_first_token_ms", "max_model_call_ms"]
                key_totals.extend([literal(key), func.max(value) if is_max else func.sum(value)])
            totals.append(func.json_object(*key_totals).cast(JSON).label(field))
    queries: Dict[str, Any] = {
        "totals": union_all(*(select(table.c.date, *totals).where(where).group_by(table.c.date) for where in wheres))
    }

    if "duration_buckets" in fields:
        bucket_queries: List[Any] = []
        for bucket_field in ["duration_ms_buckets", "time_to_first_token_ms_buckets", "model_call_ms_buckets"]:
            # MySQL has no function listing an object's key and value pairs, so its keys are listed and each is read
            bucket = func.json_table(
                func.json_keys(table.c.duration_metrics, f"$.{bucket_field}"),
                literal_column("'$[*]' COLUMNS (bucket VARCHAR(32) PATH '$')"),
            ).table_valued("bucket")
            count = func.json_extract(table.c.duration_metrics, func.concat(f"$.{bucket_field}.", bucket.c.bucket))
            bucket_queries.extend(
                select(
                    table.c.date,
                    literal(bucket_field).label("bucket_field"),
                    bucket.c.bucket.label("bucket"),
                    func.sum(cast(count, BigInteger)).label("count"),
                )
                .select_from(table.join(bucket, true()))
                .where(where)
                .group_by(table.c.date, bucket.c.bucket)
                for where in wheres
            )
        queries["duration_buckets"] = union_all(*bucket_queries)

    if "model_metrics" in fields:
        # Each id is read byte for byte, so two models whose ids differ only in case stay two entries
        model = func.json_table(
            table.c.model_metrics,
            literal_column(
                "'$[*]' COLUMNS ("
                f"entry_model_id VARCHAR(512) CHARACTER SET utf8mb4 COLLATE {_OS_METRICS_COLLATION} PATH '$.model_id', "
                f"entry_model_provider VARCHAR(512) CHARACTER SET utf8mb4 COLLATE {_OS_METRICS_COLLATION} "
                "PATH '$.model_provider', "
                f"entry_agent_id VARCHAR(128) CHARACTER SET utf8mb4 COLLATE {_OS_METRICS_COLLATION} PATH '$.agent_id', "
                f"entry_team_id VARCHAR(128) CHARACTER SET utf8mb4 COLLATE {_OS_METRICS_COLLATION} PATH '$.team_id', "
                f"entry_workflow_id VARCHAR(128) CHARACTER SET utf8mb4 COLLATE {_OS_METRICS_COLLATION} "
                "PATH '$.workflow_id', "
                "entry_count BIGINT PATH '$.count')"
            ),
        ).table_valued(
            "entry_model_id",
            "entry_model_provider",
            "entry_agent_id",
            "entry_team_id",
            "entry_workflow_id",
            "entry_count",
        )
        # Labelled apart from the table's own agent_id, team_id and workflow_id, which GROUP BY would pick instead
        queries["model_metrics"] = union_all(
            *(
                select(
                    table.c.date,
                    func.coalesce(model.c.entry_model_id, "").label("model_id"),
                    func.coalesce(model.c.entry_model_provider, "").label("model_provider"),
                    func.coalesce(model.c.entry_agent_id, "").label("model_agent_id"),
                    func.coalesce(model.c.entry_team_id, "").label("model_team_id"),
                    func.coalesce(model.c.entry_workflow_id, "").label("model_workflow_id"),
                    func.sum(model.c.entry_count).label("count"),
                )
                .select_from(table.join(model, true()))
                .where(where)
                .group_by(
                    table.c.date, "model_id", "model_provider", "model_agent_id", "model_team_id", "model_workflow_id"
                )
                for where in wheres
            )
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
            last updated. A month totalled from its month rows is one dict, dated its first day.
    """
    totals_by_date: Dict[date, Dict[str, Any]] = {}
    latest_updated_at: Optional[int] = None
    for row in rows_by_query["totals"]:
        day_totals: Dict[str, Any] = {"date": row.date}
        for field in fields:
            if field in ["sessions_count", "runs_count"]:
                day_totals[field] = int(getattr(row, field) or 0)
            elif field in OS_METRICS_FIXED_KEYS:
                # A key no row reported stays out, as it would in a stored row
                day_totals[field] = {key: int(value) for key, value in getattr(row, field).items() if value is not None}
            elif field == "model_metrics":
                day_totals[field] = []
            else:
                day_totals[field] = {}
        totals_by_date[row.date] = day_totals
        if row.updated_at is not None and (latest_updated_at is None or row.updated_at > latest_updated_at):
            latest_updated_at = row.updated_at

    for row in rows_by_query.get("duration_buckets", []):
        bucket_totals = totals_by_date.get(row.date)
        if bucket_totals is not None:
            bucket_totals["duration_buckets"].setdefault(row.bucket_field, {})[row.bucket] = int(row.count)

    for row in rows_by_query.get("model_metrics", []):
        model_totals = totals_by_date.get(row.date)
        if model_totals is None:
            continue
        model: Dict[str, Any] = {"model_id": row.model_id, "model_provider": row.model_provider}
        if row.model_agent_id:
            model["agent_id"] = row.model_agent_id
        if row.model_team_id:
            model["team_id"] = row.model_team_id
        if row.model_workflow_id:
            model["workflow_id"] = row.model_workflow_id
        model["count"] = int(row.count or 0)
        model_totals["model_metrics"].append(model)

    return [totals_by_date[day] for day in sorted(totals_by_date)], latest_updated_at
