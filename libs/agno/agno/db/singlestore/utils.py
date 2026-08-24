"""Utility functions for the SingleStore database class."""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import Engine

from agno.db.singlestore.schemas import get_table_schema_definition
from agno.utils.log import log_debug, log_error, log_warning

try:
    from sqlalchemy import Table, and_, func, or_, select
    from sqlalchemy.dialects import mysql
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

    Raises:
        Exception: If the schema creation fails.
    """
    try:
        log_debug(f"Creating schema if not exists: {db_schema}")
        session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {db_schema};"))
    except Exception as e:
        log_warning(f"Could not create schema {db_schema}: {str(e)}")


def is_table_available(session: Session, table_name: str, db_schema: Optional[str]) -> bool:
    """
    Check if a table with the given name exists in the given schema.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        if db_schema is not None:
            exists_query = text(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table"
            )
            exists = session.execute(exists_query, {"schema": db_schema, "table": table_name}).scalar() is not None
        else:
            # Check in current database/schema
            exists_query = text(
                "SELECT 1 FROM information_schema.tables WHERE table_name = :table AND table_schema = DATABASE()"
            )
            exists = session.execute(exists_query, {"table": table_name}).scalar() is not None

        return exists

    except Exception as e:
        log_error(f"Error checking if table exists: {str(e)}")
        return False


def is_valid_table(db_engine: Engine, table_name: str, table_type: str, db_schema: Optional[str]) -> bool:
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
        table_ref = f"{db_schema}.{table_name}" if db_schema else table_name

        inspector = inspect(db_engine)
        try:
            import warnings

            # Suppressing SQLAlchemy warnings about unrecognized SingleStore JSON types, which are expected
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Did not recognize type 'JSON'", category=Warning)
                existing_columns_info = inspector.get_columns(table_name, schema=db_schema)

            existing_columns = set(col["name"] for col in existing_columns_info)

        except Exception:
            # If column inspection fails (e.g., unrecognized JSON type), assume table is valid
            return True

        # Check if all expected columns exist
        missing_columns = expected_columns - existing_columns
        if missing_columns:
            log_warning(f"Missing columns {missing_columns} in table {table_ref}")
            return False

        return True

    except Exception as e:
        table_ref = f"{db_schema}.{table_name}" if db_schema else table_name
        log_error(f"Error validating table schema for {table_ref}: {str(e)}")
        raise


# -- Metrics util methods --
def _rewritten_metrics_delete(table: Table, metrics_records: list[dict]):
    """Build the DELETE clearing the buckets these records replace.

    Scoped to the buckets being written, so a bucket the recalculation does not produce keeps its
    row. Without a unique key to upsert against, a repeated calculation can leave several rows per
    bucket, so every row for those keys goes and the fresh set is written in its place.

    Args:
        table (Table): The metrics table.
        metrics_records (list[dict]): The freshly calculated metrics records.

    Returns:
        The DELETE statement, scoped to the buckets being written.
    """
    return table.delete().where(_rewritten_metrics_keys(table, metrics_records))


def _rewritten_metrics_keys(table: Table, metrics_records: list[dict]):
    """Match every row for the (user_id, date, aggregation_period) keys being written."""
    keys = {(record.get("user_id", ""), record["date"], record["aggregation_period"]) for record in metrics_records}

    return or_(
        *[
            and_(
                table.c.user_id == user_id,
                table.c.date == date_to_process,
                table.c.aggregation_period == aggregation_period,
            )
            for user_id, date_to_process, aggregation_period in keys
        ]
    )


def _existing_metrics_identity(session: Session, table: Table, metrics_records: list[dict]) -> Dict[tuple, tuple]:
    """Each bucket's current id and created_at, keyed by (user_id, date, period).

    The delete clears whole buckets, so without this a bucket would take a new id and created_at on
    every refresh. A bucket can hold several rows, so the earliest created_at wins and its id with it.
    """
    rows = session.execute(
        select(table.c.user_id, table.c.date, table.c.aggregation_period, table.c.id, table.c.created_at).where(
            _rewritten_metrics_keys(table, metrics_records)
        )
    ).fetchall()

    identity: Dict[tuple, tuple] = {}
    for user_id, date_value, aggregation_period, row_id, created_at in rows:
        key = (user_id, date_value, aggregation_period)
        current = identity.get(key)
        if current is None or (created_at is not None and current[1] is not None and created_at < current[1]):
            identity[key] = (row_id, created_at)
    return identity


def bulk_upsert_metrics(session: Session, table: Table, metrics_records: list[dict]) -> list[dict]:
    """Bulk upsert metrics into the database with proper duplicate handling.

    No unique key on (user_id, date, aggregation_period) to upsert against, so the buckets being
    rewritten are cleared and written fresh, each keeping the id and created_at it already had.
    SingleStore refuses one on a columnstore table carrying an ``id`` primary key: a unique key
    has to contain every column of the shard key, and a second multi-column unique index is not
    supported at all.

    This repairs a raced bucket rather than preventing one. Two concurrent calculations still
    each find nothing to delete and insert their own row, but the next calculation clears both
    and writes one. The ``on_duplicate_key_update`` below only guards a collision on the ``id``
    primary key, which raced inserts do not share.

    Args:
        table (Table): The table to upsert into.
        metrics_records (list[dict]): The metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    carried = _existing_metrics_identity(session, table, metrics_records)

    # Committed together with the writes below, so a crash can't leave a date with no metrics.
    session.execute(_rewritten_metrics_delete(table, metrics_records))

    results = []
    for record in metrics_records:
        key = (record.get("user_id", ""), record.get("date"), record.get("aggregation_period"))
        existing_identity = carried.get(key)
        if existing_identity is not None:
            record = {**record, "id": existing_identity[0], "created_at": existing_identity[1]}

        # An overlapping refresh landing between our delete and this write collides on the id PRIMARY KEY.
        stmt = mysql.insert(table).values(**record)
        stmt = stmt.on_duplicate_key_update(
            **{
                col.name: record.get(col.name)
                for col in table.columns
                if col.name not in ["id", "date", "created_at", "aggregation_period", "user_id"] and col.name in record
            }
        )
        session.execute(stmt)
        results.append(record)

    session.commit()
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
