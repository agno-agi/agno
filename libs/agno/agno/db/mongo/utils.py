"""Utility functions for the MongoDB database class."""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from uuid import uuid4

from agno.db.mongo.schemas import get_collection_indexes
from agno.utils.log import log_error, log_info, log_warning

try:
    from pymongo import ReturnDocument
    from pymongo.collection import Collection
    from pymongo.errors import OperationFailure
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it using `pip install pymongo`")

if TYPE_CHECKING:
    from agno.db.mongo.async_mongo import AsyncMongoCollectionType


LEGACY_METRICS_INDEX = "date_1_aggregation_period_1"
INDEX_NOT_FOUND = 27  # MongoDB's IndexNotFound error code


# -- DB util methods --
def create_collection_indexes(collection: Collection, collection_type: str) -> None:
    """Create all required indexes for a collection.

    Each index is attempted independently: one conflicting index (e.g. a legacy
    collection whose index exists with different options) must not prevent the
    remaining indexes from being created.
    """
    try:
        # Before the creation loop, so an index that fails to build does not leave the
        # obsolete key in place as well
        if collection_type == "metrics" and LEGACY_METRICS_INDEX in collection.index_information():
            try:
                collection.drop_index(LEGACY_METRICS_INDEX)
                log_info(
                    f"Dropped obsolete metrics index {LEGACY_METRICS_INDEX}, superseded by the per-user unique key"
                )
            except OperationFailure as e:
                if e.code != INDEX_NOT_FOUND:
                    log_warning(f"Could not drop obsolete metrics index {LEGACY_METRICS_INDEX}: {str(e)}")

        indexes = get_collection_indexes(collection_type)
    except Exception as e:
        log_warning(f"Error creating indexes for {collection_type} collection: {str(e)}")
        return
    for index_spec in indexes:
        key = index_spec["key"]
        unique = index_spec.get("unique", False)
        extra = {"name": index_spec["name"]} if "name" in index_spec else {}

        try:
            if isinstance(key, list):
                collection.create_index(key, unique=unique, **extra)
            else:
                collection.create_index([(key, 1)], unique=unique, **extra)
        except OperationFailure as e:
            # e.g. IndexOptionsConflict on a legacy collection, or a DuplicateKey when a
            # unique index cannot be built over pre-existing duplicates: skip it, try the rest
            log_warning(f"Error creating index {key!r} for {collection_type} collection: {str(e)}")
        except Exception as e:
            # Connection-level failure: the remaining creates would all fail too
            # (each waiting out the server-selection timeout), so stop here
            log_warning(f"Error creating indexes for {collection_type} collection: {str(e)}")
            return


async def create_collection_indexes_async(collection: Any, collection_type: str) -> None:
    """Create all required indexes for a collection (async version for Motor).

    Each index is attempted independently: one conflicting index (e.g. a legacy
    collection whose index exists with different options) must not prevent the
    remaining indexes from being created.
    """
    try:
        # See create_collection_indexes: the drop goes before the creation loop
        if collection_type == "metrics" and LEGACY_METRICS_INDEX in await collection.index_information():
            try:
                await collection.drop_index(LEGACY_METRICS_INDEX)
                log_info(
                    f"Dropped obsolete metrics index {LEGACY_METRICS_INDEX}, superseded by the per-user unique key"
                )
            except OperationFailure as e:
                if e.code != INDEX_NOT_FOUND:
                    log_warning(f"Could not drop obsolete metrics index {LEGACY_METRICS_INDEX}: {str(e)}")

        indexes = get_collection_indexes(collection_type)
    except Exception as e:
        log_warning(f"Error creating indexes for {collection_type} collection: {str(e)}")
        return
    for index_spec in indexes:
        key = index_spec["key"]
        unique = index_spec.get("unique", False)
        extra = {"name": index_spec["name"]} if "name" in index_spec else {}

        try:
            if isinstance(key, list):
                await collection.create_index(key, unique=unique, **extra)
            else:
                await collection.create_index([(key, 1)], unique=unique, **extra)
        except OperationFailure as e:
            # e.g. IndexOptionsConflict on a legacy collection, or a DuplicateKey when a
            # unique index cannot be built over pre-existing duplicates: skip it, try the rest
            log_warning(f"Error creating index {key!r} for {collection_type} collection: {str(e)}")
        except Exception as e:
            # Connection-level failure: the remaining creates would all fail too
            # (each waiting out the server-selection timeout), so stop here
            log_warning(f"Error creating indexes for {collection_type} collection: {str(e)}")
            return


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


# -- Run util methods --
def build_runs_query(
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    team_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    status: Any = None,
    before_run_index: Optional[int] = None,
    after_run_index: Optional[int] = None,
    created_after: Optional[int] = None,
    created_before: Optional[int] = None,
    parent_run_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """The runs-collection filter for the ``get_runs`` filters, except ``top_level_only``."""
    from agno.db.utils import run_status_values

    query: Dict[str, Any] = {}
    for field, value in (
        ("session_id", session_id),
        ("user_id", user_id),
        ("agent_id", agent_id),
        ("team_id", team_id),
        ("workflow_id", workflow_id),
    ):
        if value is not None:
            query[field] = value
    statuses = run_status_values(status)
    if statuses is not None:
        query["status"] = {"$in": statuses}
    # Range operators never match a null or missing run_index / created_at
    run_index_range: Dict[str, int] = {}
    if before_run_index is not None:
        run_index_range["$lt"] = before_run_index
    if after_run_index is not None:
        run_index_range["$gt"] = after_run_index
    if run_index_range:
        query["run_index"] = run_index_range
    created_range: Dict[str, int] = {}
    if created_after is not None:
        created_range["$gte"] = created_after
    if created_before is not None:
        created_range["$lte"] = created_before
    if created_range:
        query["created_at"] = created_range
    if parent_run_ids is not None:
        query["parent_run_id"] = {"$in": list(parent_run_ids)}
    return query


def runs_sort_spec(sort_by: Optional[str] = None, sort_order: Optional[str] = None) -> List[Tuple[str, int]]:
    """Sort keys for ``get_runs``; a single run_index key stays servable by the (session_id, run_index) index."""
    if sort_by is None:
        return [("run_index", 1), ("created_at", 1)]
    return [(sort_by, 1 if sort_order == "asc" else -1)]


def top_level_run_stages(runs_collection_name: str) -> List[Dict[str, Any]]:
    """Aggregation stages keeping runs whose parent_run_id names no other run in the same session."""
    return [
        {
            "$lookup": {
                "from": runs_collection_name,
                "let": {"parent_run_id": "$parent_run_id", "run_id": "$run_id", "session_id": "$session_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$run_id", "$$parent_run_id"]},
                                    {"$ne": ["$run_id", "$$run_id"]},
                                    {"$eq": ["$session_id", "$$session_id"]},
                                ]
                            }
                        }
                    },
                    {"$limit": 1},
                    {"$project": {"_id": 1}},
                ],
                "as": "_parent_run",
            }
        },
        {"$match": {"_parent_run": {"$size": 0}}},
        {"$project": {"_parent_run": 0}},
    ]


def runs_page_pipeline(
    query: Dict[str, Any],
    sort: List[Tuple[str, int]],
    runs_collection_name: str,
    limit: Optional[int] = None,
    page: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(page pipeline, count pipeline) for a ``top_level_only`` ``get_runs``.

    The page pipeline sorts before the parent lookup so an indexed sort streams and the limit
    stops the lookups after one page.
    """
    top_level = top_level_run_stages(runs_collection_name)
    count_pipeline: List[Dict[str, Any]] = [{"$match": query}, *top_level, {"$count": "count"}]
    page_pipeline: List[Dict[str, Any]] = [{"$match": query}, {"$sort": dict(sort)}, *top_level]
    query_args = apply_pagination({}, limit, page)
    if query_args.get("skip"):
        page_pipeline.append({"$skip": query_args["skip"]})
    if query_args.get("limit"):
        page_pipeline.append({"$limit": query_args["limit"]})
    return page_pipeline, count_pipeline


def legacy_runs_query(session_id: str) -> Dict[str, Any]:
    """Filter matching the session document when it still embeds non-empty legacy runs."""
    return {
        "session_id": session_id,
        "$or": [{"runs.0": {"$exists": True}}, {"runs": {"$type": "string", "$nin": ["", "[]", "null"]}}],
    }


# -- Metrics util methods --
def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[dict]:
    """Calculate metrics for the given single date, one record per user.

    Sessions with no ``user_id`` are bucketed under the empty-string sentinel.
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
            if isinstance(runs, str):
                runs = json.loads(runs)
            bucket[runs_count_key] += len(runs)
            for run in runs:
                if model_id := run.get("model"):
                    model_provider = run.get("model_provider", "")
                    key = f"{model_id}:{model_provider}"
                    bucket["model_counts"][key] = bucket["model_counts"].get(key, 0) + 1

            session_data = session.get("session_data", {}) or {}
            if isinstance(session_data, str):
                session_data = json.loads(session_data)
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
            # Legacy records have no ``user_id``, so default to the empty-string sentinel bucket
            key_filter = {
                "user_id": record.get("user_id", ""),
                "date": record["date"],
                "aggregation_period": record["aggregation_period"],
            }

            # id and created_at belong to the first write, so only $set the fields that change
            identity = {"id": record.pop("id"), "created_at": record.pop("created_at")}
            stored = collection.find_one_and_update(
                key_filter,
                {"$set": record, "$setOnInsert": identity},
                upsert=True,
                return_document=ReturnDocument.AFTER,
                projection={"_id": False},
            )
            # Upserting and returning AFTER always yields the document; a miss would put a
            # None where every caller expects a record
            if stored is not None:
                results.append(stored)

        except Exception as e:
            log_error(f"Error upserting metrics record: {str(e)}")
            continue

    return results


async def abulk_upsert_metrics(
    collection: "AsyncMongoCollectionType", metrics_records: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Async bulk upsert metrics into the database.

    Args:
        collection (AsyncMongoCollectionType): The async collection to upsert the metrics into.
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
            # Legacy records have no ``user_id``, so default to the empty-string sentinel bucket
            key_filter = {
                "user_id": record.get("user_id", ""),
                "date": record["date"],
                "aggregation_period": record["aggregation_period"],
            }

            # id and created_at belong to the first write, so only $set the fields that change
            identity = {"id": record.pop("id"), "created_at": record.pop("created_at")}
            stored = await collection.find_one_and_update(
                key_filter,
                {"$set": record, "$setOnInsert": identity},
                upsert=True,
                return_document=ReturnDocument.AFTER,
                projection={"_id": False},
            )
            # Upserting and returning AFTER always yields the document; a miss would put a
            # None where every caller expects a record
            if stored is not None:
                results.append(stored)

        except Exception as e:
            log_error(f"Error upserting metrics record: {str(e)}")
            continue

    return results
