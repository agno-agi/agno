"""Utility functions for the GCS JSON database class."""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from agno.db.utils import (
    OS_METRICS_DAY_PERIODS,
    get_sort_value,
    metric_record_day,
)
from agno.utils.log import log_debug


def apply_sorting(
    data: List[Dict[str, Any]], sort_by: Optional[str] = None, sort_order: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Apply sorting to the given data list.

    Args:
        data: The list of dictionaries to sort
        sort_by: The field to sort by
        sort_order: The sort order ('asc' or 'desc')

    Returns:
        The sorted list

    Note:
        If sorting by "updated_at", will fallback to "created_at" in case of None.
    """
    if sort_by is None or not data:
        return data

    # Check if the sort field exists in the first item
    if sort_by not in data[0]:
        log_debug(f"Invalid sort field: '{sort_by}'. Will not apply any sorting.")
        return data

    try:
        is_descending = sort_order != "asc" if sort_order else True

        # Sort using the helper function that handles updated_at -> created_at fallback
        sorted_records = sorted(
            data,
            key=lambda x: (get_sort_value(x, sort_by) is None, get_sort_value(x, sort_by)),
            reverse=is_descending,
        )

        return sorted_records
    except Exception as e:
        log_debug(f"Error sorting data by '{sort_by}': {e}")
        return data


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[dict]:
    """Calculate metrics for the given single date, bucketed per ``user_id``.

    Sessions without a ``user_id`` aggregate under the empty string bucket.

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
    date_iso = date_to_process.isoformat()

    records: List[dict] = []
    for user_id, bucket in per_user.items():
        model_metrics = []
        for model, count in bucket["model_counts"].items():
            model_id, model_provider = model.rsplit(":", 1)
            model_metrics.append({"model_id": model_id, "model_provider": model_provider, "count": count})

        users_count = 0 if user_id == "" else 1
        metric_id = f"{date_iso}_{user_id}_daily"

        records.append(
            {
                "id": metric_id,
                "date": date_iso,
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
        sessions: List of session dictionaries
        dates_to_process (list[date]): The dates to fetch session data for.
        start_timestamp (int): The starting timestamp for filtering

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

    all_sessions_data: dict[str, dict[str, list[dict[str, Any]]]] = {
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
def deserialize_os_metrics_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the stored OS metrics records in the shape calculate_date_os_metrics writes.

    Args:
        records (List[Dict[str, Any]]): The OS metrics records as stored, their date an ISO string.

    Returns:
        List[Dict[str, Any]]: The records with their date as a date. A record whose date is not a day is left out.
    """
    os_metrics = []
    for record in records:
        day = metric_record_day(record)
        if day is not None:
            os_metrics.append({**record, "date": day})
    return os_metrics


def serialize_os_metrics_records(os_metrics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the OS metrics records as they are stored.

    Args:
        os_metrics (List[Dict[str, Any]]): The OS metrics records, their date a date.

    Returns:
        List[Dict[str, Any]]: The records with their date as an ISO string.
    """
    return [{**record, "date": record["date"].isoformat()} for record in os_metrics]


def get_os_metrics_records_by_day(
    records: List[Dict[str, Any]], start_timestamp: int, end_timestamp: int
) -> Dict[date, List[Dict[str, Any]]]:
    """Return the sessions or runs created in the given time range, by the day they were created on.

    Args:
        records (List[Dict[str, Any]]): The sessions or the runs, as stored.
        start_timestamp (int): The start of the range, included.
        end_timestamp (int): The end of the range, not included.

    Returns:
        Dict[date, List[Dict[str, Any]]]: The records of each UTC day that has any.
    """
    records_by_day: Dict[date, List[Dict[str, Any]]] = {}
    for record in records:
        created_at = record.get("created_at") or 0
        if start_timestamp <= created_at < end_timestamp:
            day = datetime.fromtimestamp(created_at, tz=timezone.utc).date()
            records_by_day.setdefault(day, []).append(record)
    return records_by_day


def get_dates_to_calculate_os_metrics_for(
    os_metrics: List[Dict[str, Any]],
    sessions_by_day: Dict[date, List[Dict[str, Any]]],
    runs_by_day: Dict[date, List[Dict[str, Any]]],
    starting_date: date,
) -> List[date]:
    """Return the list of dates to calculate OS metrics for.

    Args:
        os_metrics (List[Dict[str, Any]]): The stored OS metrics records.
        sessions_by_day (Dict[date, List[Dict[str, Any]]]): The sessions created on each day a rebuild looks at.
        runs_by_day (Dict[date, List[Dict[str, Any]]]): The runs created on each of those days.
        starting_date (date): The first day without complete OS metrics.

    Returns:
        List[date]: Today, then every day that ended and has a session, a run or an open record, oldest first.
    """
    today = datetime.now(timezone.utc).date()

    open_days = [record["date"] for record in os_metrics if not record.get("completed")]
    days_to_complete = {day for day in [*sessions_by_day, *runs_by_day, *open_days] if starting_date <= day < today}

    return [today, *sorted(days_to_complete)]


def upsert_os_metrics_records(
    os_metrics: List[Dict[str, Any]],
    date_to_process: date,
    changed_rows: List[Dict[str, Any]],
    stale_ids: List[str],
) -> List[Dict[str, Any]]:
    """Upsert a day's OS metrics records into the stored ones, and delete the records the day no longer has.

    Args:
        os_metrics (List[Dict[str, Any]]): The stored OS metrics records.
        date_to_process (date): The day.
        changed_rows (List[Dict[str, Any]]): The records of the day that are new or changed.
        stale_ids (List[str]): The ids of the stored records the day no longer has.

    Returns:
        List[Dict[str, Any]]: The OS metrics records to store. The given list is left as it is.
    """

    def _record_key(record: Dict[str, Any]) -> Tuple[str, str, str, str, str, str]:
        return (
            record["aggregation_period"],
            record.get("user_id") or "",
            record.get("agent_id") or "",
            record.get("team_id") or "",
            record.get("workflow_id") or "",
            record.get("parent_id") or "",
        )

    changed_by_key = {_record_key(row): row for row in changed_rows}
    stale = set(stale_ids)
    current_time = int(time.time())

    records = []
    for record in os_metrics:
        if record["date"] != date_to_process or record["aggregation_period"] not in OS_METRICS_DAY_PERIODS:
            records.append(record)
            continue
        if record["id"] in stale:
            continue
        changed_row = changed_by_key.pop(_record_key(record), None)
        if changed_row is not None:
            # The id and created_at of a stored record are never overwritten
            record = {**changed_row, "id": record["id"], "created_at": record.get("created_at")}
        # Stamp every record left when the day lost one, so its updated_at moves
        if stale_ids:
            record = {**record, "updated_at": current_time}
        records.append(record)

    for changed_row in changed_by_key.values():
        records.append({**changed_row, "updated_at": current_time} if stale_ids else changed_row)

    return records


def get_os_metrics_records_to_read(
    os_metrics: List[Dict[str, Any]], starting_date: date, ending_date: date, user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return the stored OS metrics records a read of the given date range totals, every day from one period.

    Args:
        os_metrics (List[Dict[str, Any]]): The stored OS metrics records.
        starting_date (date): The first day to total.
        ending_date (date): The last day to total.
        user_id (Optional[str]): Total only this owner's records. ``None`` totals every owner.

    Returns:
        List[Dict[str, Any]]: For every owner, the total record of each day that has one and the records of
            any other day. For one owner, that owner's records.
    """
    records = [record for record in os_metrics if starting_date <= record["date"] <= ending_date]
    if user_id is not None:
        return [
            record for record in records if record["aggregation_period"] == "daily" and record["user_id"] == user_id
        ]

    total_days = {record["date"] for record in records if record["aggregation_period"] == "daily_total"}
    return [
        record
        for record in records
        if record["aggregation_period"] == ("daily_total" if record["date"] in total_days else "daily")
    ]
