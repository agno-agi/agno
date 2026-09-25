"""Utility functions for the Postgres database class."""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agno.db.postgres.schemas import get_table_schema_definition
from agno.db.utils import OS_METRICS_FIXED_KEYS
from agno.utils.log import log_debug, log_error, log_warning

try:
    from sqlalchemy import (
        BigInteger,
        Select,
        Table,
        and_,
        cast,
        column,
        func,
        literal,
        literal_column,
        select,
        true,
        union_all,
    )
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.exc import NoSuchTableError
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
        log_debug(f"Ensuring schema {db_schema}", log_level=2)
        session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {db_schema};"))
    except Exception as e:
        log_warning(f"Could not create schema {db_schema}: {str(e)}")


async def acreate_schema(session: AsyncSession, db_schema: str) -> None:
    """Create the database schema if it doesn't exist.

    Args:
        session: The SQLAlchemy session to use
        db_schema (str): The definition of the database schema to create
    """
    try:
        log_debug(f"Ensuring schema {db_schema}", log_level=2)
        await session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {db_schema};"))
    except Exception as e:
        log_warning(f"Could not create schema {db_schema}: {str(e)}")


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


async def ais_table_available(session: AsyncSession, table_name: str, db_schema: str) -> bool:
    """
    Check if a table with the given name exists in the given schema.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        exists_query = text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table"
        )
        exists = (await session.execute(exists_query, {"schema": db_schema, "table": table_name})).scalar() is not None
        return exists
    except Exception as e:
        log_error(f"Error checking if table exists: {str(e)}")
        return False


def is_valid_table(db_engine: Engine, table_name: str, table_type: str, db_schema: str) -> bool:
    """
    Check if the existing table has the expected column names.

    Args:
        table_name (str): Name of the table to validate
        schema (str): Database schema name

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


async def ais_valid_table(db_engine: AsyncEngine, table_name: str, table_type: str, db_schema: str) -> bool:
    """
    Check if the existing table has the expected column names.

    Args:
        table_name (str): Name of the table to validate
        schema (str): Database schema name

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
    except NoSuchTableError as e:
        log_error(f"Table {db_schema}.{table_name} does not exist: {str(e)}")
        return False
    except Exception as e:
        log_error(f"Error validating table schema for {db_schema}.{table_name}: {str(e)}")
        raise


def _get_table_columns(conn, table_name: str, db_schema: str) -> set[str]:
    """Helper function to get table columns using sync inspector."""
    inspector = inspect(conn)
    columns_info = inspector.get_columns(table_name, schema=db_schema)
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
    stmt = postgresql.insert(table)

    # Columns to update in case of conflict. user_id is part of the conflict key, so never overwrite it.
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in ["id", "date", "created_at", "aggregation_period", "user_id"]
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "date", "aggregation_period"], set_=update_columns
    ).returning(  # type: ignore
        table
    )
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
    stmt = postgresql.insert(table)

    # Columns to update in case of conflict. user_id is part of the conflict key, so never overwrite it.
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in ["id", "date", "created_at", "aggregation_period", "user_id"]
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "date", "aggregation_period"], set_=update_columns
    ).returning(  # type: ignore
        table
    )
    result = await session.execute(stmt, metrics_records)
    results = [row._mapping for row in result.fetchall()]
    await session.commit()

    return results  # type: ignore


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[dict]:
    """Calculate metrics for the given single date, bucketed per user.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data to calculate metrics for.

    Returns:
        List[dict]: The calculated metrics, one record per user. Sessions without a
            ``user_id`` are bucketed under ``""``.
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

            session_data = session.get("session_data", {}) or {}
            session_metrics = session_data.get("session_metrics", {}) or {}
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

        # One distinct user per bucket, and none for the unowned one, so summed counts stay correct.
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

# Every assistant message's request duration, skipping messages carried over from an earlier run
_OS_METRICS_CALL_DURATIONS_PATH: Any = literal_column(
    """'$.messages[*] ? (@.role == "assistant" && (!exists(@.from_history) || @.from_history == false))"""
    """.metrics.duration'::jsonpath"""
)


def bulk_upsert_os_metrics(session: Session, table: Table, os_metrics_records: List[Dict[str, Any]]) -> None:
    """Bulk upsert OS metrics into the database, in the session's transaction.

    Args:
        session (Session): The session to upsert with.
        table (Table): The table to upsert into.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    stmt = postgresql.insert(table)

    # Columns to update in case of conflict. The conflict key, id and created_at are never overwritten.
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name
        not in ["id", "created_at", "user_id", "date", "aggregation_period", "agent_id", "team_id", "workflow_id"]
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "date", "aggregation_period", "agent_id", "team_id", "workflow_id"],
        set_=update_columns,
    )
    session.execute(stmt, os_metrics_records)


async def abulk_upsert_os_metrics(
    session: AsyncSession, table: Table, os_metrics_records: List[Dict[str, Any]]
) -> None:
    """Bulk upsert OS metrics into the database, in the session's transaction.

    Args:
        session (AsyncSession): The session to upsert with.
        table (Table): The table to upsert into.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    stmt = postgresql.insert(table)

    # Columns to update in case of conflict. The conflict key, id and created_at are never overwritten.
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name
        not in ["id", "created_at", "user_id", "date", "aggregation_period", "agent_id", "team_id", "workflow_id"]
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "date", "aggregation_period", "agent_id", "team_id", "workflow_id"],
        set_=update_columns,
    )
    await session.execute(stmt, os_metrics_records)


def build_os_metrics_runs_query(table: Table, start_timestamp: int, end_timestamp: int) -> Select:
    """Build the query that reads the runs created in the given time range, with only what OS metrics count.

    Args:
        table (Table): The runs table.
        start_timestamp (int): The start of the range, included.
        end_timestamp (int): The end of the range, not included.

    Returns:
        Select: The query. Of the messages it reads only each request's duration.
    """
    return select(
        table.c.run_id,
        table.c.run_type,
        table.c.agent_id,
        table.c.team_id,
        table.c.workflow_id,
        table.c.user_id,
        table.c.parent_run_id,
        table.c.status,
        table.c.run_data["metrics"].label("metrics"),
        table.c.run_data["model"].astext.label("model"),
        table.c.run_data["model_provider"].astext.label("model_provider"),
        func.jsonb_path_query_array(table.c.run_data, _OS_METRICS_CALL_DURATIONS_PATH).label("call_durations"),
        table.c.run_data["step_executor_runs"].label("step_executor_runs"),
        table.c.run_data["member_responses"].label("member_responses"),
    ).where(table.c.created_at >= start_timestamp, table.c.created_at < end_timestamp)


def build_os_metrics_run(row: Any) -> Dict[str, Any]:
    """Build a run in its stored shape from a row of the OS metrics runs query.

    Args:
        row (Any): A row of build_os_metrics_runs_query.

    Returns:
        Dict[str, Any]: The run, with the run_data calculate_date_os_metrics reads.
    """
    run = dict(row._mapping)
    run["run_data"] = {
        "metrics": run.pop("metrics"),
        "model": run.pop("model"),
        "model_provider": run.pop("model_provider"),
        "messages": [
            {"role": "assistant", "metrics": {"duration": duration}} for duration in run.pop("call_durations") or []
        ],
        "step_executor_runs": run.pop("step_executor_runs"),
        "member_responses": run.pop("member_responses"),
    }
    return run


def build_os_metrics_totals_queries(
    table: Table,
    starting_date: date,
    ending_date: date,
    user_id: Optional[str],
    fields: Sequence[str],
) -> Dict[str, Any]:
    """Build the queries that total the OS metrics rows of each day in the given date range.

    Args:
        table (Table): The OS metrics table.
        starting_date (date): The first day to total.
        ending_date (date): The last day to total.
        user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner.
        fields (Sequence[str]): The columns to total.

    Returns:
        Dict[str, Any]: The queries, keyed "totals", "duration_buckets" and "model_metrics".
    """
    conditions = [table.c.date >= starting_date, table.c.date <= ending_date]
    if user_id is not None:
        conditions.append(table.c.user_id == user_id)
    where = and_(*conditions)

    totals = [func.max(table.c.updated_at).label("updated_at")]
    for field in fields:
        if field in ["sessions_count", "runs_count"]:
            totals.append(func.sum(table.c[field]).label(field))
        elif field in OS_METRICS_FIXED_KEYS:
            # Each key of the JSON column totalled on its own, and gathered back into one object
            key_totals: List[Any] = []
            for key in OS_METRICS_FIXED_KEYS[field]:
                value = cast(table.c[field][key].astext, BigInteger)
                is_max = key in ["max_duration_ms", "max_time_to_first_token_ms", "max_model_call_ms"]
                key_totals.extend([literal(key), func.max(value) if is_max else func.sum(value)])
            totals.append(func.jsonb_build_object(*key_totals).label(field))
    queries: Dict[str, Any] = {"totals": select(table.c.date, *totals).where(where).group_by(table.c.date)}

    if "duration_buckets" in fields:
        bucket_queries = []
        for bucket_field in ["duration_ms_buckets", "time_to_first_token_ms_buckets", "model_call_ms_buckets"]:
            bucket = func.jsonb_each_text(table.c.duration_metrics[bucket_field]).table_valued("key", "value")
            bucket_queries.append(
                select(
                    table.c.date,
                    literal(bucket_field).label("bucket_field"),
                    bucket.c.key.label("bucket"),
                    func.sum(cast(bucket.c.value, BigInteger)).label("count"),
                )
                .select_from(table.join(bucket, true()))
                .where(where)
                .group_by(table.c.date, bucket.c.key)
            )
        queries["duration_buckets"] = union_all(*bucket_queries)

    if "model_metrics" in fields:
        model = func.jsonb_array_elements(table.c.model_metrics).table_valued(column("value", postgresql.JSONB))
        # Labelled apart from the table's own agent_id, team_id and workflow_id, which GROUP BY would pick instead
        queries["model_metrics"] = (
            select(
                table.c.date,
                func.coalesce(model.c.value["model_id"].astext, "").label("model_id"),
                func.coalesce(model.c.value["model_provider"].astext, "").label("model_provider"),
                func.coalesce(model.c.value["agent_id"].astext, "").label("model_agent_id"),
                func.coalesce(model.c.value["team_id"].astext, "").label("model_team_id"),
                func.coalesce(model.c.value["workflow_id"].astext, "").label("model_workflow_id"),
                func.sum(cast(model.c.value["count"].astext, BigInteger)).label("count"),
            )
            .select_from(table.join(model, true()))
            .where(where)
            .group_by(
                table.c.date, "model_id", "model_provider", "model_agent_id", "model_team_id", "model_workflow_id"
            )
        )

    return queries


def build_os_metrics_totals(
    fields: Sequence[str],
    rows_by_query: Dict[str, Sequence[Any]],
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Build the OS metrics totals of each day from the rows of the totals queries.

    Args:
        fields (Sequence[str]): The columns that were totalled.
        rows_by_query (Dict[str, Sequence[Any]]): The rows of each query of build_os_metrics_totals_queries.

    Returns:
        Tuple[List[Dict[str, Any]], Optional[int]]: One dict per day, oldest first, and when the rows were
            last updated.
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
