import json
import time
from datetime import date, datetime, timezone
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, RecordID

from agno.db.base import SessionType
from agno.db.surrealdb import utils
from agno.db.surrealdb.models import desurrealize_session, surrealize_dates
from agno.db.surrealdb.queries import WhereClause
from agno.db.utils import (
    OS_METRICS_FIXED_KEYS,
    OS_METRICS_STATE_ID,
    build_os_metrics_state,
    metrics_starting_date_from_days,
)
from agno.utils.log import log_error
from agno.utils.string import generate_id


def get_all_sessions_for_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: Optional[datetime] = None,
    end_timestamp: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Get all sessions of all types (agent, team, workflow) as raw dictionaries.

    Args:
        start_timestamp (Optional[int]): The start timestamp to filter by. Defaults to None.
        end_timestamp (Optional[int]): The end timestamp to filter by. Defaults to None.

    Returns:
        List[Dict[str, Any]]: List of session dictionaries with session_type field.

    Raises:
        Exception: If an error occurs during retrieval.
    """
    where = WhereClause()

    # starting_date
    if start_timestamp is not None:
        where = where.and_("created_at", start_timestamp, ">=")

    # ending_date
    if end_timestamp is not None:
        where = where.and_("created_at", end_timestamp, "<=")

    where_clause, where_vars = where.build()

    # Query
    query = dedent(f"""
        SELECT *
        FROM {table}
        {where_clause}
    """)

    results = utils.query(client, query, where_vars, dict)
    return [desurrealize_session(x) for x in results]


def _stored_day(value: Any) -> Optional[date]:
    """The day a stored metrics row covers, as a plain date.

    SurrealDB hands back a tz-aware datetime for the date column, but the shared decision
    compares days, so anything that is not already one is normalised here rather than trusted.
    """
    # datetime is a subclass of date, so it has to be narrowed first or a stamp passes through whole
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def get_metrics_calculation_starting_date(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], table: str, get_sessions: Callable
) -> Optional[date]:
    """Get the first date for which metrics calculation is needed:

    1. If there are metrics records, return the date of the first day without a complete metrics record.
    2. If there are no metrics records, return the date of the first recorded session.
    3. If there are no metrics records and no sessions records, return None.

    Args:
        table (Table): The table to get the starting date for.

    Returns:
        Optional[date]: The starting date for which metrics calculation is needed.
    """
    # 1. resume at the earliest incomplete day after the latest completed one, otherwise the
    # day after that one: the date column is a datetime stamped at midnight, so the strict
    # comparison below excludes the completed day itself
    completed_record = utils.query_one(
        client,
        dedent(f"""
            SELECT * FROM ONLY {table}
            WHERE completed = true
            ORDER BY date DESC
            LIMIT 1
        """),
        {},
        dict,
    )
    stored_completed_day = completed_record["date"] if completed_record else None

    incomplete_where = (
        "WHERE completed = false" if stored_completed_day is None else "WHERE completed = false AND date > $last"
    )
    incomplete_vars: Dict[str, Any] = {} if stored_completed_day is None else {"last": stored_completed_day}
    incomplete_record = utils.query_one(
        client,
        dedent(f"""
            SELECT * FROM ONLY {table}
            {incomplete_where}
            ORDER BY date ASC
            LIMIT 1
        """),
        incomplete_vars,
        dict,
    )

    latest_completed = _stored_day(stored_completed_day)
    earliest_incomplete = _stored_day(incomplete_record["date"]) if incomplete_record else None

    starting_date = metrics_starting_date_from_days(latest_completed, earliest_incomplete)
    if starting_date is not None:
        return starting_date

    # 2. No metrics records. Return the date of the first recorded session
    first_session, _ = get_sessions(
        session_type=SessionType.AGENT,  # this is ignored because of component_id=None and deserialize=False
        sort_by="created_at",
        sort_order="asc",
        limit=1,
        component_id=None,
        deserialize=False,
    )
    assert isinstance(first_session, list)

    first_session_date = first_session[0]["created_at"] if first_session else None

    # 3. No metrics records and no sessions records. Return None
    if first_session_date is None:
        return None

    # Handle different types for created_at
    if isinstance(first_session_date, datetime):
        return first_session_date.date()
    elif isinstance(first_session_date, int):
        # Assume it's a Unix timestamp
        return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()
    elif isinstance(first_session_date, str):
        # Try parsing as ISO format
        return datetime.fromisoformat(first_session_date.replace("Z", "+00:00")).date()
    else:
        # If it's already a date object
        if isinstance(first_session_date, date):
            return first_session_date
        raise ValueError(f"Unexpected type for created_at: {type(first_session_date)}")


def desurrealize_metric(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stored metric record in the plain shape every other adapter returns.

    SurrealDB hands back a RecordID and its own datetimes, which the response model rejects,
    so both the read and the recalculation pass their rows through here.
    """
    row = dict(record)

    if hasattr(row.get("id"), "id"):
        row["id"] = row["id"].id
    elif isinstance(row.get("id"), RecordID):
        row["id"] = str(row["id"].id)

    for field in ("created_at", "updated_at", "date"):
        if isinstance(row.get(field), datetime):
            row[field] = int(row[field].timestamp())

    # Unowned rows are stored with an empty-string user_id
    if row.get("user_id") == "":
        row["user_id"] = None

    return row


def bulk_upsert_metrics(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    metrics_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Bulk upsert metrics into the database.

    Args:
        table (Table): The table to upsert into.
        metrics_records (List[Dict[str, Any]]): The list of metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    metrics_records = [surrealize_dates(x) for x in metrics_records]

    results = []
    from agno.utils.log import log_debug

    for metric in metrics_records:
        log_debug(f"Upserting metric: {metric}")
        # Per-record: a mid-run failure must not discard the records that already landed
        try:
            result = utils.query_one(
                client,
                "UPSERT $record CONTENT $content",
                {"record": RecordID(table, metric["id"]), "content": metric},
                dict,
            )
        except Exception as e:
            log_error(f"Error upserting metrics record: {str(e)}")
            continue

        if result:
            results.append(result)

    return results


def fetch_all_sessions_data(
    sessions: List[Dict[str, Any]], dates_to_process: list[date], start_timestamp: int
) -> Optional[dict]:
    """Return all session data for the given dates, for all session types.

    Args:
        sessions (List[Dict[str, Any]]): The sessions to process.
        dates_to_process (list[date]): The dates to fetch session data for.
        start_timestamp (int): The start timestamp (fallback if created_at is missing).

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
        created_at = session.get("created_at", start_timestamp)

        # Handle different types for created_at
        if isinstance(created_at, datetime):
            session_date = created_at.date().isoformat()
        elif isinstance(created_at, int):
            session_date = datetime.fromtimestamp(created_at, tz=timezone.utc).date().isoformat()
        elif isinstance(created_at, date):
            session_date = created_at.isoformat()
        else:
            # Fallback to start_timestamp if type is unexpected
            session_date = datetime.fromtimestamp(start_timestamp, tz=timezone.utc).date().isoformat()

        if session_date in all_sessions_data:
            session_type = session.get("session_type", "agent")  # Default to agent if missing
            all_sessions_data[session_date][session_type].append(session)

    return all_sessions_data


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[dict]:
    """Calculate metrics for the given single date, bucketed per user_id.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data to calculate metrics for.

    Returns:
        List[dict]: One metrics record per user. Sessions with no user_id bucket under "".
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
        sessions = sessions_data.get(session_type, [])

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

    current_time = datetime.now(timezone.utc)
    completed = date_to_process < current_time.date()
    # Stamp the day being aggregated, not today, so backfilled days stay in get_metrics range queries
    date_at_midnight = datetime.combine(date_to_process, datetime.min.time(), tzinfo=timezone.utc)

    records: List[dict] = []
    for user_id, bucket in per_user.items():
        model_metrics = []
        for model, count in bucket["model_counts"].items():
            model_id, model_provider = model.rsplit(":", 1)
            model_metrics.append({"model_id": model_id, "model_provider": model_provider, "count": count})

        users_count = 0 if user_id == "" else 1
        # Deterministic per-(date, user) ID, so re-calculating the same window upserts the same record
        record_id = f"{date_to_process.isoformat()}|{user_id}"

        records.append(
            {
                "id": record_id,
                "date": date_at_midnight,
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


# --- OS Metrics ---

_OS_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses")

# A run nested deeper than this is read whole
_OS_METRICS_NESTED_RUNS_DEPTH = 6


def _os_metrics_nested_runs_fields(depth: int = _OS_METRICS_NESTED_RUNS_DEPTH) -> str:
    """The fields of the runs nested inside a stored run that OS metrics count, down to the given depth."""
    if depth == 0:
        return ", ".join(_OS_METRICS_NESTED_RUN_KEYS)
    fields = "run_id, agent_id, team_id, metrics, model, model_provider, messages.{role, from_history, metrics}"
    nested_fields = _os_metrics_nested_runs_fields(depth - 1)
    return ", ".join(f"{key}.{{{fields}, {nested_fields}}}" for key in _OS_METRICS_NESTED_RUN_KEYS)


def os_metrics_record_id(record: Dict[str, Any]) -> str:
    """The id an OS metrics record is stored under: one per day, period, owner, component and parent.

    The record id is what keeps two rebuilds that write the same record from storing it twice. Seeded with
    the key as JSON, which no two keys share.
    """
    day = record["date"]
    return generate_id(
        json.dumps(
            [
                day.isoformat() if isinstance(day, date) else day,
                record["aggregation_period"],
                record.get("user_id") or "",
                record.get("agent_id") or "",
                record.get("team_id") or "",
                record.get("workflow_id") or "",
                record.get("parent_id") or "",
            ]
        )
    )


def _build_os_metrics_run_data(run_data: Dict[str, Any]) -> Dict[str, Any]:
    """The run_data of a stored run, or of a run nested inside it, with only what OS metrics count."""
    metrics = run_data.get("metrics") or {}
    trimmed_metrics = {
        key: metrics[key]
        for key in (*OS_METRICS_FIXED_KEYS["token_metrics"], "duration", "time_to_first_token")
        if metrics.get(key) is not None
    }
    # Only whether the model call reported details is counted
    if metrics.get("details"):
        trimmed_metrics["details"] = True
    trimmed: Dict[str, Any] = {
        "metrics": trimmed_metrics,
        "model": run_data.get("model"),
        "model_provider": run_data.get("model_provider"),
        # Only each request's duration, skipping messages carried over from an earlier run
        "messages": [
            {"role": "assistant", "metrics": {"duration": message["metrics"]["duration"]}}
            for message in run_data.get("messages") or []
            if isinstance(message, dict)
            and message.get("role") == "assistant"
            and not message.get("from_history")
            and (message.get("metrics") or {}).get("duration") is not None
        ],
    }
    for key in _OS_METRICS_NESTED_RUN_KEYS:
        nested_runs = [nested_run for nested_run in run_data.get(key) or [] if isinstance(nested_run, dict)]
        if nested_runs:
            trimmed[key] = [
                {
                    "run_id": nested_run.get("run_id"),
                    "agent_id": nested_run.get("agent_id"),
                    "team_id": nested_run.get("team_id"),
                    **_build_os_metrics_run_data(nested_run),
                }
                for nested_run in nested_runs
            ]
    return trimmed


def build_os_metrics_run(record: Dict[str, Any]) -> Dict[str, Any]:
    """Build a run with only what OS metrics count from a record of the runs table.

    Args:
        record (Dict[str, Any]): A record of the runs table, as get_all_runs_for_os_metrics_calculation reads it.

    Returns:
        Dict[str, Any]: The run, with the run_data calculate_date_os_metrics reads.
    """
    run_data = record.get("run_data")
    return {
        "run_id": record.get("run_id"),
        "run_type": record.get("run_type"),
        "agent_id": record.get("agent_id"),
        "team_id": record.get("team_id"),
        "workflow_id": record.get("workflow_id"),
        "user_id": record.get("user_id"),
        "parent_run_id": record.get("parent_run_id"),
        "status": record.get("status"),
        "run_data": _build_os_metrics_run_data(
            {**(run_data if isinstance(run_data, dict) else {}), "messages": record.get("messages")}
        ),
    }


def _day_start(day: date) -> datetime:
    """The datetime a day is stored as, and the start of the runs and sessions created on it."""
    return datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)


def desurrealize_os_metric(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stored OS metrics record in the shape calculate_date_os_metrics writes, to compare and total it.

    Unlike desurrealize_metric, the empty-string user_id and the day are kept as they are built.
    """
    row = dict(record)

    if isinstance(row.get("id"), RecordID):
        row["id"] = str(row["id"].id)

    for field in ("created_at", "updated_at"):
        if isinstance(row.get(field), datetime):
            row[field] = int(row[field].timestamp())

    if "date" in row:
        row["date"] = _stored_day(row["date"])

    # A metadata of None is stored as NONE, which is not handed back
    row.setdefault("metadata", None)

    return row


def get_os_metrics_records(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    aggregation_period: str,
    starting_date: Optional[date] = None,
    ending_date: Optional[date] = None,
    user_id: Optional[str] = None,
    fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Get the OS metrics records of one period in the given date range.

    Args:
        table (str): The OS metrics table.
        aggregation_period (str): The period to read: "daily" or "daily_total".
        starting_date (Optional[date]): The first day to read. ``None`` reads from the first one stored.
        ending_date (Optional[date]): The last day to read. ``None`` reads to the last one stored.
        user_id (Optional[str]): Only this owner's records. ``None`` reads every owner's.
        fields (Optional[List[str]]): The fields to read. ``None`` reads the whole record.

    Returns:
        List[Dict[str, Any]]: The records, in the shape calculate_date_os_metrics writes.
    """
    if starting_date is not None and ending_date is not None and starting_date > ending_date:
        return []

    where = WhereClause()
    where = where.and_("aggregation_period", aggregation_period)
    if starting_date is not None:
        where = where.and_("date", _day_start(starting_date), ">=")
    if ending_date is not None:
        where = where.and_("date", _day_start(ending_date), "<=")
    if user_id is not None:
        where = where.and_("user_id", user_id)
    where_clause, where_vars = where.build()

    # The index of the day is bounded at both ends of the range, the index of the period at the first day only
    index_clause = "WITH INDEX idx_date" if aggregation_period == "daily" and user_id is None else ""

    query = dedent(f"""
        SELECT {", ".join(fields) if fields is not None else "*"}
        FROM {table} {index_clause}
        {where_clause}
    """)
    return [desurrealize_os_metric(record) for record in utils.query(client, query, where_vars, dict)]


def get_os_metrics_calculation_starting_date(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], table: str, get_sessions: Callable
) -> Optional[date]:
    """Get the first date for which OS metrics calculation is needed:

    1. If there are OS metrics records, return the first day after the latest completed one.
    2. If there are no OS metrics records, return the date of the first recorded session.
    3. If there are no OS metrics records and no sessions records, return None.

    Args:
        table (str): The OS metrics table.

    Returns:
        Optional[date]: The starting date for which OS metrics calculation is needed.
    """
    # 1. A completed day has a total record, so the latest one is read off the index of the period
    completed_days = utils.query(
        client,
        dedent(f"""
            SELECT date FROM {table}
            WHERE aggregation_period = "daily_total"
            ORDER BY date DESC
            LIMIT 1
        """),
        {},
        dict,
    )
    stored_completed_day = completed_days[0]["date"] if completed_days else None

    incomplete_where = (
        'WHERE aggregation_period = "daily"'
        if stored_completed_day is None
        else 'WHERE aggregation_period = "daily" AND date > $last'
    )
    incomplete_vars: Dict[str, Any] = {} if stored_completed_day is None else {"last": stored_completed_day}
    incomplete_days = utils.query(
        client,
        dedent(f"""
            SELECT date FROM {table}
            {incomplete_where}
            ORDER BY date ASC
            LIMIT 1
        """),
        incomplete_vars,
        dict,
    )

    latest_completed = _stored_day(stored_completed_day)
    earliest_incomplete = _stored_day(incomplete_days[0]["date"]) if incomplete_days else None

    starting_date = metrics_starting_date_from_days(latest_completed, earliest_incomplete)
    if starting_date is not None:
        return starting_date

    # 2. No OS metrics records. Return the date of the first recorded session, of any type
    first_session, _ = get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)

    # 3. No OS metrics records and no sessions records. Return None
    if not first_session:
        return None

    return datetime.fromtimestamp(first_session[0]["created_at"], tz=timezone.utc).date()


def get_run_days_for_os_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: datetime,
    end_timestamp: datetime,
) -> List[date]:
    """Get the days of the given time range that have runs.

    Args:
        table (str): The runs table.
        start_timestamp (datetime): The start of the range, included.
        end_timestamp (datetime): The end of the range, not included.

    Returns:
        List[date]: Each UTC day that has runs.
    """
    query = dedent(f"""
        SELECT time::floor(created_at, 1d) AS day
        FROM {table}
        WHERE created_at >= $start AND created_at < $end
        GROUP BY day
    """)
    rows = utils.query(client, query, {"start": start_timestamp, "end": end_timestamp}, dict)
    return [row["day"].date() for row in rows]


def get_session_days_for_os_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: datetime,
    end_timestamp: datetime,
) -> List[date]:
    """Get the days of the given time range that have sessions.

    Args:
        table (str): The sessions table.
        start_timestamp (datetime): The start of the range, included.
        end_timestamp (datetime): The end of the range, not included.

    Returns:
        List[date]: Each UTC day that has sessions.
    """
    query = dedent(f"""
        SELECT time::floor(created_at, 1d) AS day
        FROM {table}
        WHERE created_at >= $start AND created_at < $end
        GROUP BY day
    """)
    rows = utils.query(client, query, {"start": start_timestamp, "end": end_timestamp}, dict)
    return [row["day"].date() for row in rows]


def get_all_sessions_for_os_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: datetime,
    end_timestamp: datetime,
) -> List[Dict[str, Any]]:
    """Get the sessions created in the given time range, with only what OS metrics count.

    Args:
        table (str): The sessions table.
        start_timestamp (datetime): The start of the range, included.
        end_timestamp (datetime): The end of the range, not included.

    Returns:
        List[Dict[str, Any]]: The sessions: their type, their owner and their agent, team or workflow.
    """
    query = dedent(f"""
        SELECT user_id, agent, team, workflow
        FROM {table}
        WHERE created_at >= $start AND created_at < $end
    """)
    results = utils.query(client, query, {"start": start_timestamp, "end": end_timestamp}, dict)
    return [desurrealize_session(x) for x in results]


def get_all_runs_for_os_metrics_calculation(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    start_timestamp: datetime,
    end_timestamp: datetime,
) -> List[Dict[str, Any]]:
    """Get the runs created in the given time range, with only what OS metrics count.

    Args:
        table (str): The runs table.
        start_timestamp (datetime): The start of the range, included.
        end_timestamp (datetime): The end of the range, not included.

    Returns:
        List[Dict[str, Any]]: The runs, with the run_data calculate_date_os_metrics reads.
    """
    query = dedent(f"""
        SELECT
            run_id, run_type, agent_id, team_id, workflow_id, user_id, parent_run_id, status,
            run_data.{{metrics, model, model_provider, {_os_metrics_nested_runs_fields()}}} AS run_data,
            run_data.messages.{{role, from_history, metrics}} AS messages
        FROM {table}
        WHERE created_at >= $start AND created_at < $end
    """)
    return [
        build_os_metrics_run(record)
        for record in utils.query(client, query, {"start": start_timestamp, "end": end_timestamp}, dict)
    ]


def get_stored_os_metrics_state(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection], table: str
) -> Dict[str, Any]:
    """Get the state of the OS metrics, from the state record.

    Args:
        table (str): The OS metrics table.

    Returns:
        Dict[str, Any]: The state, as build_os_metrics_state builds it. Empty for a table no rebuild has written to.
    """
    state = utils.query_one(client, "SELECT * FROM ONLY $state", {"state": RecordID(table, OS_METRICS_STATE_ID)}, dict)
    return state or {}


def bulk_upsert_os_metrics(
    client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
    table: str,
    os_metrics_records: List[Dict[str, Any]],
    stale_ids: Optional[List[str]] = None,
    day: Optional[date] = None,
) -> None:
    """Bulk upsert OS metrics into the database, and delete the given records.

    The state record is written with the last batch, so it moves only once the whole day is saved.

    Args:
        table (str): The table to upsert into.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
        stale_ids (Optional[List[str]]): The ids of the records to delete.
        day (Optional[date]): The day the records are of.
    """
    if not os_metrics_records and not stale_ids:
        return

    state = build_os_metrics_state(
        get_stored_os_metrics_state(client, table), int(time.time()), os_metrics_records, stale_ids or [], day
    )
    # The total record of a day is written last, so a day whose write failed part way has none
    os_metrics_records = sorted(os_metrics_records, key=lambda record: record["aggregation_period"] != "daily")
    records = [{**surrealize_dates(record), "id": RecordID(table, record["id"])} for record in os_metrics_records]
    stale = [RecordID(table, stale_id) for stale_id in stale_ids or []]
    rows_to_write = max(len(records), len(stale))
    for start in range(0, rows_to_write, utils.OS_METRICS_BATCH_SIZE):
        chunk: Dict[str, Any] = {
            "stale": stale[start : start + utils.OS_METRICS_BATCH_SIZE],
            "records": records[start : start + utils.OS_METRICS_BATCH_SIZE],
        }
        statements = "DELETE $stale; FOR $record IN $records { UPSERT $record.id CONTENT $record; };"
        if start + utils.OS_METRICS_BATCH_SIZE >= rows_to_write:
            chunk.update(
                {
                    "state": RecordID(table, OS_METRICS_STATE_ID),
                    "state_content": {"aggregation_period": OS_METRICS_STATE_ID, **state},
                }
            )
            statements += "UPSERT $state CONTENT $state_content;"
        for _ in range(utils.OS_METRICS_WRITE_ATTEMPTS):
            try:
                client.query(f"{{ {statements} }}", chunk)
                break
            except Exception as e:
                # Another rebuild wrote the same records at the same time, so the statement that lost is sent again
                if "can be retried" not in str(e):
                    raise
        else:
            raise RuntimeError(
                f"OS metrics records were not written after {utils.OS_METRICS_WRITE_ATTEMPTS} write conflicts"
            )
