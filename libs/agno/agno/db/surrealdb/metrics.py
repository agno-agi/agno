from datetime import date, datetime, timedelta, timezone
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, RecordID

from agno.db.base import SessionType
from agno.db.surrealdb import utils
from agno.db.surrealdb.models import desurrealize_session, surrealize_dates
from agno.db.surrealdb.queries import WhereClause
from agno.utils.log import log_error


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
    query = dedent(f"""
        SELECT * FROM ONLY {table}
        ORDER BY date DESC
        LIMIT 1
    """)
    result = utils.query_one(client, query, {}, dict)
    if result:
        # 1. Return the date of the first day without a complete metrics record
        result_date = result["date"]
        assert isinstance(result_date, datetime)
        result_date = result_date.date()

        if result.get("completed"):
            return result_date + timedelta(days=1)
        else:
            return result_date

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

    try:
        results = []
        from agno.utils.log import log_debug

        for metric in metrics_records:
            log_debug(f"Upserting metric: {metric}")  # Add this
            result = utils.query_one(
                client,
                "UPSERT $record CONTENT $content",
                {"record": RecordID(table, metric["id"]), "content": metric},
                dict,
            )
            if result:
                results.append(result)
        return results

    except Exception as e:
        log_error(f"Error upserting metrics: {str(e)}")

    return []


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


def calculate_date_metrics(date_to_process: date, sessions_data: dict, user_isolation: bool = False) -> List[dict]:
    """Calculate metrics for the given single date, bucketed per ``user_id``.

    Each session is attributed to its owning user. Sessions without a
    ``user_id`` aggregate under the sentinel empty-string bucket.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data to calculate metrics for.
        user_isolation: If ``True``, bucket metrics per ``user_id``; otherwise one row per date (default).

    Returns:
        A list of per-user metrics records. SurrealDB uses a deterministic
        record ID of ``"{date}|{user_id}"`` so re-running the calculation
        for the same (date, user) updates the same record.
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
            "user_ids": set(),
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
            session_user_id = session.get("user_id") or ""
            bucket_key = session_user_id if user_isolation else ""
            bucket = per_user.setdefault(bucket_key, _empty_metric_record())
            if session_user_id:
                bucket["user_ids"].add(session_user_id)
            bucket[sessions_count_key] += 1

            runs = session.get("runs", []) or []
            bucket[runs_count_key] += len(runs)
            for run in runs:
                if model_id := run.get("model"):
                    model_provider = run.get("model_provider", "")
                    key = f"{model_id}:{model_provider}"
                    bucket["model_counts"][key] = bucket["model_counts"].get(key, 0) + 1

            session_metrics = session.get("session_data", {}).get("session_metrics", {}) or {}
            for field in bucket["token_metrics"]:
                bucket["token_metrics"][field] += session_metrics.get(field, 0)

    current_time = datetime.now(timezone.utc)
    completed = date_to_process < datetime.now(timezone.utc).date()
    date_at_midnight = current_time.replace(hour=0, minute=0, second=0, microsecond=0)

    records: List[dict] = []
    for user_id, bucket in per_user.items():
        model_metrics = []
        for model, count in bucket["model_counts"].items():
            model_id, model_provider = model.rsplit(":", 1)
            model_metrics.append({"model_id": model_id, "model_provider": model_provider, "count": count})

        users_count = len(bucket["user_ids"])
        # Deterministic per-(date, user) ID so re-running calculation for the
        # same window updates the same record. The empty-string bucket gets
        # ``{date}|`` — the trailing pipe makes the unowned bucket distinct
        # from any conceivable real user_id.
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
