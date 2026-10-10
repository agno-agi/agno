"""Utility functions for the Redis database class."""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from agno.db.utils import OS_METRICS_FIXED_KEYS, get_sort_value
from agno.utils.log import log_warning
from agno.utils.string import generate_id

try:
    from redis import Redis, RedisCluster
except ImportError:
    raise ImportError("`redis` not installed. Please install it using `pip install redis`")


# -- Serialization and deserialization --


class CustomEncoder(json.JSONEncoder):
    """Custom encoder to handle non JSON serializable types."""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, (date, datetime)):
            return obj.isoformat()

        return super().default(obj)


def serialize_data(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, cls=CustomEncoder)


def deserialize_data(data: str) -> dict:
    return json.loads(data)


# -- Redis utils --


def generate_redis_key(prefix: str, table_type: str, key_id: str) -> str:
    """Generate Redis key with proper namespacing."""
    return f"{prefix}:{table_type}:{key_id}"


def generate_index_key(prefix: str, table_type: str, index_field: str, index_value: str) -> str:
    """Generate Redis key for index entries."""
    return f"{prefix}:{table_type}:index:{index_field}:{index_value}"


def get_all_keys_for_table(redis_client: Union[Redis, RedisCluster], prefix: str, table_type: str) -> List[str]:
    """Get all relevant keys for the given table type.

    Args:
        redis_client (Redis): The Redis client.
        prefix (str): The prefix for the keys.
        table_type (str): The table type.

    Returns:
        List[str]: A list of all relevant keys for the given table type.
    """
    pattern = f"{prefix}:{table_type}:*"
    all_keys = redis_client.scan_iter(match=pattern, count=1000)
    relevant_keys = []

    # Helper namespaces, matched by prefix so a record id that merely contains one
    # of these markers is not dropped from the results
    index_prefix = f"{prefix}:{table_type}:index:"
    runs_by_session_prefix = f"{prefix}:runs:by_session:"

    for key in all_keys:
        # Coerce bytes -> str for substring checks (decode_responses may not be set)
        key_str = key.decode() if isinstance(key, (bytes, bytearray)) else key
        if key_str.startswith(index_prefix):  # Skip index keys
            continue
        # Skip helper indexes maintained by the v3+ runs collection
        # (e.g. `<prefix>:runs:by_session:<session_id>` sorted-set indexes)
        if key_str.startswith(runs_by_session_prefix):
            continue
        relevant_keys.append(key)

    return relevant_keys


# -- DB util methods --


def apply_sorting(
    records: List[Dict[str, Any]], sort_by: Optional[str] = None, sort_order: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Apply sorting to the given records list.

    Args:
        records: The list of dictionaries to sort
        sort_by: The field to sort by
        sort_order: The sort order ('asc' or 'desc')

    Returns:
        The sorted list

    Note:
        If sorting by "updated_at", will fallback to "created_at" in case of None.
    """
    if sort_by is None or not records:
        return records

    try:
        is_descending = sort_order == "desc"

        # Sort using the helper function that handles updated_at -> created_at fallback
        sorted_records = sorted(
            records,
            key=lambda x: (get_sort_value(x, sort_by) is None, get_sort_value(x, sort_by)),
            reverse=is_descending,
        )

        return sorted_records

    except Exception as e:
        log_warning(f"Error sorting Redis records: {str(e)}")
        return records


def apply_pagination(
    records: List[Dict[str, Any]], limit: Optional[int] = None, page: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Apply pagination.

    Raises ``ValueError`` when ``page`` is provided without ``limit`` — see
    ``agno.db.utils.validate_pagination``.
    """
    from agno.db.utils import validate_pagination

    validate_pagination(limit, page)
    if limit is None:
        return records

    if page is not None and page > 0:
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        return records[start_idx:end_idx]

    return records[:limit]


def apply_filters(records: List[Dict[str, Any]], conditions: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not conditions:
        return records

    filtered_records = []
    for record in records:
        match = True
        for key, value in conditions.items():
            if key not in record or record[key] != value:
                match = False
                break
        if match:
            filtered_records.append(record)

    return filtered_records


def create_index_entries(
    redis_client: Union[Redis, RedisCluster],
    prefix: str,
    table_type: str,
    record_id: str,
    record_data: Dict[str, Any],
    index_fields: List[str],
) -> None:
    for field in index_fields:
        if field in record_data and record_data[field] is not None:
            index_key = generate_index_key(prefix, table_type, field, str(record_data[field]))
            redis_client.sadd(index_key, record_id)


def remove_index_entries(
    redis_client: Union[Redis, RedisCluster],
    prefix: str,
    table_type: str,
    record_id: str,
    record_data: Dict[str, Any],
    index_fields: List[str],
) -> None:
    for field in index_fields:
        if field in record_data and record_data[field] is not None:
            index_key = generate_index_key(prefix, table_type, field, str(record_data[field]))
            redis_client.srem(index_key, record_id)


# -- Metrics utils --


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[dict]:
    """Calculate metrics for the given date, bucketed per ``user_id``.

    Sessions without a ``user_id`` aggregate under the sentinel empty-string bucket.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data.

    Returns:
        List[dict]: A list of per-user metrics records.
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
        # Create a deterministic ID based on date and user. This simplifies avoiding duplicates
        metric_id = f"{date_to_process.isoformat()}_{user_id}_daily"

        records.append(
            {
                "id": metric_id,
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
        sessions (List[Dict[str, Any]]): The sessions data.
        dates_to_process (list[date]): The dates to process.
        start_timestamp (int): The start timestamp.

    Returns:
        Optional[dict]: A dictionary with the session data for the given dates, for all session types.
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
        starting_date (date): The starting date.

    Returns:
        list[date]: The list of dates to calculate metrics for.
    """
    today = datetime.now(timezone.utc).date()
    days_diff = (today - starting_date).days + 1
    if days_diff <= 0:
        return []
    return [starting_date + timedelta(days=x) for x in range(days_diff)]


# -- OS metrics utils --

OS_METRICS_LOCK_SECONDS = 300

OS_METRICS_BATCH_SIZE = 1000

_OS_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses")


def os_metrics_record_id(
    day: date,
    aggregation_period: str,
    user_id: str = "",
    agent_id: str = "",
    team_id: str = "",
    workflow_id: str = "",
    parent_id: str = "",
) -> str:
    """Generate the deterministic ID of an OS metrics record. This simplifies avoiding duplicates.

    The ID starts with the day, so the day of a record is read off an index entry without reading the record.

    Args:
        day (date): The day of the record.
        aggregation_period (str): The period of the record.
        user_id (str): The owner of the record. Empty for a total record.
        agent_id (str): The agent of the record.
        team_id (str): The team of the record.
        workflow_id (str): The workflow of the record.
        parent_id (str): The parent of the record.

    Returns:
        str: The ID of the record.
    """
    component_id = generate_id(
        json.dumps([user_id or "", agent_id or "", team_id or "", workflow_id or "", parent_id or ""])
    )
    return f"{day.isoformat()}_{aggregation_period}_{component_id}"


def os_metrics_record_day(record_id: Any) -> Optional[date]:
    """Read the day off the ID of an OS metrics record, or ``None`` if it does not start with one."""
    # Coerce bytes -> str (decode_responses may not be set)
    record_id = record_id.decode() if isinstance(record_id, (bytes, bytearray)) else str(record_id)
    try:
        return date.fromisoformat(record_id[:10])
    except ValueError:
        return None


def get_os_metrics_index_fields(record: Dict[str, Any]) -> List[str]:
    """Return the fields an OS metrics record is indexed by.

    Only total records are indexed by period, and they are not indexed by owner.
    """
    if record["aggregation_period"] == "daily":
        return ["date", "user_id"]
    return ["date", "aggregation_period"]


def deserialize_os_metrics_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stored OS metrics record in the shape calculate_date_os_metrics writes.

    Args:
        record (Dict[str, Any]): The stored record.

    Returns:
        Dict[str, Any]: The record, with its day, stored as an ISO string, as a date.
    """
    return {**record, "date": date.fromisoformat(record["date"])}


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
        "run_id": run_data.get("run_id"),
        "agent_id": run_data.get("agent_id"),
        "team_id": run_data.get("team_id"),
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
        nested_runs = [
            _build_os_metrics_run_data(nested_run)
            for nested_run in run_data.get(key) or []
            if isinstance(nested_run, dict)
        ]
        if nested_runs:
            trimmed[key] = nested_runs
    return trimmed


def build_os_metrics_run(run: Dict[str, Any]) -> Dict[str, Any]:
    """Build a run with only what OS metrics count from a record of the runs table.

    Args:
        run (Dict[str, Any]): The run, as stored.

    Returns:
        Dict[str, Any]: The run with the run_data calculate_date_os_metrics reads: no message content, and of
            the metrics only the token counts, the timings and whether the model call reported details.
    """
    return {
        "run_id": run.get("run_id"),
        "run_type": run.get("run_type"),
        "agent_id": run.get("agent_id"),
        "team_id": run.get("team_id"),
        "workflow_id": run.get("workflow_id"),
        "user_id": run.get("user_id"),
        "parent_run_id": run.get("parent_run_id"),
        "status": run.get("status"),
        "run_data": _build_os_metrics_run_data(run.get("run_data") or {}),
    }


def build_os_metrics_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """Build a session with only what OS metrics count from a record of the sessions table.

    Args:
        session (Dict[str, Any]): The session, as stored.

    Returns:
        Dict[str, Any]: The session with its type, its owner and its agent, team or workflow.
    """
    return {
        "session_type": session.get("session_type"),
        "user_id": session.get("user_id"),
        "agent_id": session.get("agent_id"),
        "team_id": session.get("team_id"),
        "workflow_id": session.get("workflow_id"),
    }
