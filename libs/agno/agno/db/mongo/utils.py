"""Utility functions for the MongoDB database class."""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.db.mongo.schemas import get_collection_indexes
from agno.utils.log import log_error, log_warning

try:
    from pymongo.collection import Collection
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it using `pip install pymongo`")


# -- DB util methods --


def create_collection_indexes(collection: Collection, collection_type: str) -> None:
    """Create all required indexes for a collection"""
    try:
        indexes = get_collection_indexes(collection_type)
        for index_spec in indexes:
            key = index_spec["key"]
            unique = index_spec.get("unique", False)

            if isinstance(key, list):
                collection.create_index(key, unique=unique)
            else:
                collection.create_index([(key, 1)], unique=unique)

    except Exception as e:
        log_warning(f"Error creating indexes for {collection_type} collection: {e}")


def apply_sorting(
    query_args: Dict[str, Any], sort_by: Optional[str] = None, sort_order: Optional[str] = None
) -> List[tuple]:
    """Apply sorting to MongoDB query."""
    if sort_by is None:
        return []

    sort_direction = 1 if sort_order == "asc" else -1
    return [(sort_by, sort_direction)]


def apply_pagination(
    query_args: Dict[str, Any], limit: Optional[int] = None, page: Optional[int] = None
) -> Dict[str, Any]:
    """Apply pagination to MongoDB query."""
    if limit is not None:
        query_args["limit"] = limit
        if page is not None:
            query_args["skip"] = (page - 1) * limit
    return query_args


# -- Metrics util methods --


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> dict:
    """Calculate metrics for the given single date."""
    metrics = {
        "users_count": 0,
        "agent_sessions_count": 0,
        "team_sessions_count": 0,
        "workflow_sessions_count": 0,
        "agent_runs_count": 0,
        "team_runs_count": 0,
        "workflow_runs_count": 0,
    }
    token_metrics = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "audio_total_tokens": 0,
        "audio_input_tokens": 0,
        "audio_output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    model_counts: Dict[str, int] = {}

    session_types = [
        ("agent", "agent_sessions_count", "agent_runs_count"),
        ("team", "team_sessions_count", "team_runs_count"),
        ("workflow", "workflow_sessions_count", "workflow_runs_count"),
    ]
    all_user_ids = set()

    for session_type, sessions_count_key, runs_count_key in session_types:
        sessions = sessions_data.get(session_type, [])
        metrics[sessions_count_key] = len(sessions)

        for session in sessions:
            if session.get("user_id"):
                all_user_ids.add(session["user_id"])
            runs = session.get("runs", []) or []
            metrics[runs_count_key] += len(sessions)

            if runs := session.get("runs", []):
                if isinstance(runs, str):
                    runs = json.loads(runs)
                for run in runs:
                    if model_id := run.get("model"):
                        model_provider = run.get("model_provider", "")
                        model_counts[f"{model_id}:{model_provider}"] = (
                            model_counts.get(f"{model_id}:{model_provider}", 0) + 1
                        )

            session_data = session.get("session_data", {})
            if isinstance(session_data, str):
                session_data = json.loads(session_data)
            session_metrics = session_data.get("session_metrics", {})
            for field in token_metrics:
                token_metrics[field] += session_metrics.get(field, 0)

    model_metrics = []
    for model, count in model_counts.items():
        model_id, model_provider = model.split(":")
        model_metrics.append({"model_id": model_id, "model_provider": model_provider, "count": count})

    metrics["users_count"] = len(all_user_ids)
    current_time = int(time.time())

    return {
        "id": str(uuid4()),
        "date": date_to_process,
        "completed": date_to_process < datetime.now(timezone.utc).date(),
        "token_metrics": token_metrics,
        "model_metrics": model_metrics,
        "created_at": current_time,
        "updated_at": current_time,
        "aggregation_period": "daily",
        **metrics,
    }


def fetch_all_sessions_data(
    sessions: List[Dict[str, Any]], dates_to_process: list[date], start_timestamp: int
) -> Optional[dict]:
    """Return all session data for the given dates, for all session types."""
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
    """Return the list of dates to calculate metrics for."""
    today = datetime.now(timezone.utc).date()
    days_diff = (today - starting_date).days + 1
    if days_diff <= 0:
        return []
    return [starting_date + timedelta(days=x) for x in range(days_diff)]


def bulk_upsert_metrics(collection: Collection, metrics_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bulk upsert metrics into the database.

    Args:
        collection (Collection): The collection to upsert the metrics into.
        metrics_records (List[Dict[str, Any]]): The list of metrics records to upsert.

    Returns:
        The list of upserted metrics records.
    """
    if not metrics_records:
        return []

    results = []
    for record in metrics_records:
        record["date"] = record["date"].isoformat() if isinstance(record["date"], date) else record["date"]
        try:
            collection.replace_one(
                {
                    "date": record["date"],
                    "aggregation_period": record["aggregation_period"],
                },
                record,
                upsert=True,
            )

            results.append(record)

        except Exception as e:
            log_error(f"Error upserting metrics record: {e}")
            continue

    return results
