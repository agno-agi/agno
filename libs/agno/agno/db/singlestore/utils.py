"""Utility functions for the SingleStore database class."""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import uuid4

from sqlalchemy import Engine

from agno.db.singlestore.schemas import get_table_schema_definition
from agno.db.utils import (
    OS_METRICS_BUCKETS_VERSION,
    OS_METRICS_TOKEN_FIELDS,
    add_os_metrics_totals,
    empty_os_metrics_totals,
    os_metrics_day_ranges,
    os_metrics_days_to_read,
    os_metrics_nested_run_ids,
)
from agno.utils.log import log_debug, log_error, log_warning

try:
    from sqlalchemy import JSON, Table, and_, case, func, or_, select, true, type_coerce, update
    from sqlalchemy.dialects import mysql
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


# SingleStore caps a statement at max_allowed_packet, so IN lists are sent in chunks
OS_METRICS_IN_LIST_LIMIT = 10000

# SingleStore runs out of thread stack on a long OR of stale keys, so stale rows are deleted in smaller chunks
OS_METRICS_STALE_KEYS_LIMIT = 100

# Rows a rebuild reads at a time, so a day or a month of many rows is never held or decoded in one step
OS_METRICS_BATCH_SIZE = 1000

# The values of a stored details object that a model call that served nothing reports, as text
_OS_METRICS_EMPTY_DETAILS = ("{}", "[]", '""', "0", "false", "null")

# SingleStore has no GET_LOCK and cannot try a row lock without waiting, so one rebuild at a time holds a lock row
_OS_METRICS_LOCK_ROW_KEY = {"aggregation_period": "lock", "date": date(1970, 1, 1)}

# A 300 s lease by the server's clock, so a process that stopped while holding the lock row never holds it longer
OS_METRICS_LOCK_SECONDS = 300


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


# -- OS metrics util methods --
def lock_os_metrics(session: Session, table: Table) -> Optional[int]:
    """Take the lock row of the OS metrics totals table, unless another process holds it.

    Args:
        session (Session): The session to take it with. The lock is held once its transaction commits.
        table (Table): The OS metrics totals table.

    Returns:
        Optional[int]: The time it is held until by the server's clock, which releases it too. None when another
            process holds it.
    """
    current_time = session.execute(select(func.UNIX_TIMESTAMP())).scalar_one()
    held_until = current_time + OS_METRICS_LOCK_SECONDS
    stmt = mysql.insert(table).values(
        {
            **_OS_METRICS_LOCK_ROW_KEY,
            **empty_os_metrics_totals(),
            "buckets_version": OS_METRICS_BUCKETS_VERSION,
            "created_at": current_time,
            "updated_at": 0,
            "completed": False,
            "version": 1,
        }
    )
    stmt = stmt.on_duplicate_key_update(aggregation_period=stmt.inserted.aggregation_period)
    session.execute(stmt)

    result = session.execute(
        update(table)
        .where(*[table.c[column] == value for column, value in _OS_METRICS_LOCK_ROW_KEY.items()])
        .where(table.c.updated_at < current_time)
        .values(updated_at=held_until)
    )
    return held_until if result.rowcount == 1 else None  # type: ignore


def unlock_os_metrics(session: Session, table: Table, held_until: int) -> None:
    """Release the lock row of the OS metrics totals table, unless it expired and another process holds it.

    Args:
        session (Session): The session to release it with.
        table (Table): The OS metrics totals table.
        held_until (int): The time it was taken until.
    """
    session.execute(
        update(table)
        .where(*[table.c[column] == value for column, value in _OS_METRICS_LOCK_ROW_KEY.items()])
        .where(table.c.updated_at == held_until)
        .values(updated_at=0)
    )


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

    # Columns to update in case of conflict. The primary key and created_at are never overwritten.
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


def upsert_os_metrics_totals_row(session: Session, table: Table, totals_row: Dict[str, Any]) -> None:
    """Upsert an OS metrics totals row into the database, in the session's transaction.

    A new row starts at version 1, and every write of a stored one moves its version by one in the same
    statement, so two writers never give it the same version.

    Args:
        session (Session): The session to upsert with.
        table (Table): The table to upsert into.
        totals_row (Dict[str, Any]): The row, from build_os_metrics_totals_row.
    """
    stmt = mysql.insert(table).values({**totals_row, "version": 1})

    # Columns to update in case of conflict. The primary key and created_at are never overwritten.
    update_columns: Dict[str, Any] = {
        col.name: stmt.inserted[col.name]
        for col in table.columns
        if col.name not in ["aggregation_period", "date", "created_at", "version"]
    }
    update_columns["version"] = table.c.version + 1

    stmt = stmt.on_duplicate_key_update(**update_columns)
    session.execute(stmt)


def _os_metrics_run_metrics(run_data: Any, keys: Sequence[str] = ()) -> Any:
    """Build the metrics of a stored run with only token counts, the given keys and whether details were reported."""
    pairs: List[Any] = []
    for key in list(OS_METRICS_TOKEN_FIELDS) + list(keys):
        pairs.extend([key, func.JSON_EXTRACT_JSON(run_data, "metrics", key)])
    details = func.JSON_EXTRACT_JSON(run_data, "metrics", "details")
    pairs.extend(["details", details.notin_(_OS_METRICS_EMPTY_DETAILS)])
    return func.JSON_BUILD_OBJECT(*pairs)


def build_os_metrics_runs_query(table: Table, start_timestamp: int, end_timestamp: int) -> Any:
    """Build the query that reads the runs created in the given time range, with only what OS metrics count.

    Args:
        table (Table): The runs table.
        start_timestamp (int): The start of the range, included.
        end_timestamp (int): The end of the range, not included.

    Returns:
        Any: The query. Of a run's own messages it reads only each request's duration, and of its metrics
            only what OS metrics count. The runs nested inside a run are read as stored: SingleStore lists the
            entries of an array in no set order, and the rollup walks them in the order they are stored.
    """
    in_range = [table.c.created_at >= start_timestamp, table.c.created_at < end_timestamp]

    # SingleStore does not correlate a subquery over TABLE() with the outer row, so messages are joined and grouped
    messages = func.JSON_EXTRACT_JSON(table.c.run_data, "messages")
    # The first messages a forked run copied from the run it was forked from are skipped
    skip = func.coalesce(func.JSON_EXTRACT_BIGINT(table.c.run_data, "forked_from_message_index"), 0)
    message = func.table(
        func.JSON_TO_ARRAY(case((func.JSON_GET_TYPE(messages) == "array", func.JSON_SPLICE_JSON(messages, 0, skip))))
    ).table_valued("table_col")
    duration = func.JSON_EXTRACT_JSON(message.c.table_col, "metrics", "duration")
    call_durations = (
        select(table.c.run_id, func.JSON_AGG(duration).label("call_durations"))
        .select_from(table.join(message, true()))
        .where(
            *in_range,
            func.JSON_EXTRACT_STRING(message.c.table_col, "role") == "assistant",
            func.JSON_GET_TYPE(duration) != "null",
            func.coalesce(func.JSON_EXTRACT_JSON(message.c.table_col, "from_history"), "false").in_(["false", "null"]),
        )
        .group_by(table.c.run_id)
        .subquery()
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
            type_coerce(_os_metrics_run_metrics(table.c.run_data, ["duration", "time_to_first_token"]), JSON).label(
                "metrics"
            ),
            type_coerce(func.JSON_EXTRACT_JSON(table.c.run_data, "model"), JSON).label("model"),
            type_coerce(func.JSON_EXTRACT_JSON(table.c.run_data, "model_provider"), JSON).label("model_provider"),
            type_coerce(call_durations.c.call_durations, JSON).label("call_durations"),
            type_coerce(func.JSON_EXTRACT_JSON(table.c.run_data, "step_executor_runs"), JSON).label(
                "step_executor_runs"
            ),
            type_coerce(func.JSON_EXTRACT_JSON(table.c.run_data, "member_responses"), JSON).label("member_responses"),
            type_coerce(func.JSON_EXTRACT_JSON(table.c.run_data, "workflow_agent_run"), JSON).label(
                "workflow_agent_run"
            ),
        )
        .select_from(table.outerjoin(call_durations, call_durations.c.run_id == table.c.run_id))
        .where(*in_range)
        # A run copied into a forked session repeats a run counted in the session it was made in
        .where(func.JSON_EXTRACT_STRING(table.c.run_data, "forked_from_session_id").is_(None))
    )


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
        "workflow_agent_run": run.pop("workflow_agent_run"),
    }
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


def build_os_metrics_totals_query(
    table: Table,
    starting_date: date,
    ending_date: date,
    user_id: Optional[str],
    fields: Sequence[str],
    month_starts: Sequence[date] = (),
) -> Optional[Any]:
    """Build the query that reads the OS metrics rows to total for each day in the given date range.

    Args:
        table (Table): The OS metrics totals table to total every user, or the OS metrics table to total one.
        starting_date (date): The first day to total.
        ending_date (date): The last day to total.
        user_id (Optional[str]): The user whose OS metrics rows are totalled. ``None`` for the totals table.
        fields (Sequence[str]): The columns to total.
        month_starts (Sequence[date]): The first day of every month inside the date range to total from its month
            row instead of its days.

    Returns:
        Optional[Any]: The query. ``None`` when there is no day to total.
    """
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
        return None
    where = or_(*filters)
    if user_id is not None:
        where = and_(table.c.user_id == user_id, where)

    # Read in one statement: SingleStore reads at READ COMMITTED only
    return select(table.c.date, table.c.updated_at, *[table.c[field] for field in fields]).where(where)


def build_os_metrics_totals(
    fields: Sequence[str],
    rows: Sequence[Any],
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Build the OS metrics totals of each date from the rows of the totals query.

    Args:
        fields (Sequence[str]): The columns that were totalled.
        rows (Sequence[Any]): The rows of build_os_metrics_totals_query.

    Returns:
        Tuple[List[Dict[str, Any]], Optional[int]]: One dict per date, oldest first, and when the rows were
            last updated. A month totalled from its month row is one dict, dated its first day.
    """
    totals_by_date: Dict[date, Dict[str, Any]] = {}
    latest_updated_at: Optional[int] = None
    for row in rows:
        record = dict(row._mapping)
        if "additional_metrics" in fields:
            record["additional_metrics"] = {
                key: value
                for key, value in (record["additional_metrics"] or {}).items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
        day_totals = totals_by_date.setdefault(row.date, {"date": row.date, **empty_os_metrics_totals(fields)})
        add_os_metrics_totals(day_totals, record, fields)
        if row.updated_at is not None and (latest_updated_at is None or row.updated_at > latest_updated_at):
            latest_updated_at = row.updated_at

    if "additional_metrics" in fields:
        for day_totals in totals_by_date.values():
            day_totals["additional_metrics"] = {
                key: int(value) if value == int(value) else value
                for key, value in day_totals["additional_metrics"].items()
            }

    return [totals_by_date[day] for day in sorted(totals_by_date)], latest_updated_at
