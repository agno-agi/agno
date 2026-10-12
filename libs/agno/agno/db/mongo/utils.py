"""Utility functions for the MongoDB database class."""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from agno.db.mongo.schemas import get_collection_indexes
from agno.db.utils import (
    OS_METRICS_DAY_PERIODS,
    OS_METRICS_FIXED_KEYS,
    OS_METRICS_STATE_ID,
    build_os_metrics_state,
    os_metrics_day_ranges,
)
from agno.utils.log import log_error, log_info, log_warning

try:
    from pymongo import ReturnDocument, UpdateOne
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


# -- OS metrics util methods --

# Keeps a query far below the 16MB a document can hold
OS_METRICS_IN_LIST_LIMIT = 10000

_OS_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses")

# A run nested deeper than this is read whole
_OS_METRICS_NESTED_RUNS_DEPTH = 6

_OS_METRICS_RUN_DATA_FIELDS = (
    "metrics",
    "model",
    "model_provider",
    "messages.role",
    "messages.from_history",
    "messages.metrics.duration",
)


def _os_metrics_runs_projection() -> Dict[str, int]:
    """The fields of a stored run that OS metrics count, of the run and of the runs nested inside it."""
    projection = {"_id": 0}
    for field in ["run_id", "run_type", "agent_id", "team_id", "workflow_id", "user_id", "parent_run_id", "status"]:
        projection[field] = 1
    for field in _OS_METRICS_RUN_DATA_FIELDS:
        projection[f"run_data.{field}"] = 1
    paths = ["run_data"]
    for _ in range(_OS_METRICS_NESTED_RUNS_DEPTH):
        paths = [f"{path}.{key}" for path in paths for key in _OS_METRICS_NESTED_RUN_KEYS]
        for path in paths:
            for field in ["run_id", "agent_id", "team_id", *_OS_METRICS_RUN_DATA_FIELDS]:
                projection[f"{path}.{field}"] = 1
    for path in paths:
        for key in _OS_METRICS_NESTED_RUN_KEYS:
            projection[f"{path}.{key}"] = 1
    return projection


_OS_METRICS_RUNS_PROJECTION = _os_metrics_runs_projection()

_OS_METRICS_SESSIONS_PROJECTION = {
    "_id": 0,
    "session_type": 1,
    "user_id": 1,
    "agent_id": 1,
    "team_id": 1,
    "workflow_id": 1,
}

# The fields of a record its unique index is on
_OS_METRICS_KEY_FIELDS = ("user_id", "date", "aggregation_period", "agent_id", "team_id", "workflow_id", "parent_id")


def _build_os_metrics_upserts(os_metrics_records: List[Dict[str, Any]]) -> List[UpdateOne]:
    """Build the upsert of each of the given OS metrics records, the total record of a day last."""
    upserts = []
    for record in sorted(os_metrics_records, key=lambda record: record["aggregation_period"] != "daily"):
        # The filter matches every field of the unique index, so the server retries an upsert that races another
        key_filter = {
            field: record[field].isoformat() if field == "date" else record[field] for field in _OS_METRICS_KEY_FIELDS
        }
        # id and created_at belong to the first write, so only $set the fields that change
        fields = {
            key: value for key, value in record.items() if key not in ["id", "created_at", *_OS_METRICS_KEY_FIELDS]
        }
        identity = {"id": record["id"], "created_at": record["created_at"]}
        upserts.append(UpdateOne(key_filter, {"$set": fields, "$setOnInsert": identity}, upsert=True))
    return upserts


def bulk_upsert_os_metrics(collection: Collection, os_metrics_records: List[Dict[str, Any]]) -> None:
    """Bulk upsert OS metrics into the database.

    Args:
        collection (Collection): The collection to upsert the OS metrics into.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    collection.bulk_write(_build_os_metrics_upserts(os_metrics_records))


async def abulk_upsert_os_metrics(
    collection: "AsyncMongoCollectionType", os_metrics_records: List[Dict[str, Any]]
) -> None:
    """Async bulk upsert OS metrics into the database.

    Args:
        collection (AsyncMongoCollectionType): The async collection to upsert the OS metrics into.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    await collection.bulk_write(_build_os_metrics_upserts(os_metrics_records))


def get_stored_os_metrics_state(collection: Collection) -> Dict[str, Any]:
    """Get the state of the OS metrics, from the state record.

    Args:
        collection (Collection): The OS metrics collection.

    Returns:
        Dict[str, Any]: The state, as build_os_metrics_state builds it. Empty for a collection no rebuild has
            written to.
    """
    return collection.find_one({"id": OS_METRICS_STATE_ID}, {"_id": 0}) or {}


def mark_os_metrics_state(collection: Collection, rebuild_id: str) -> None:
    """Mark the state record before a rebuild writes or deletes records of a day.

    A day saved without its state leaves the mark, so the state is not taken as the state of its records.

    Args:
        collection (Collection): The OS metrics collection.
        rebuild_id (str): The id the rebuild marks the state with. Its state write takes the mark off.
    """
    collection.update_one(
        {"id": OS_METRICS_STATE_ID},
        {"$set": {"aggregation_period": OS_METRICS_STATE_ID}, "$addToSet": {"rebuilding": rebuild_id}},
        upsert=True,
    )


def update_os_metrics_state(
    collection: Collection,
    changed_rows: Sequence[Dict[str, Any]],
    stale_ids: Sequence[str],
    day: Optional[date] = None,
    rebuild_ids: Optional[List[str]] = None,
) -> None:
    """Write the state record after a rebuild wrote or deleted records of a day.

    Args:
        collection (Collection): The OS metrics collection.
        changed_rows (Sequence[Dict[str, Any]]): The records the rebuild wrote.
        stale_ids (Sequence[str]): The ids of the records the rebuild deleted.
        day (Optional[date]): The day the records are of. ``None`` when they may not all be saved.
        rebuild_ids (Optional[List[str]]): The marks to take off the state.
    """
    previous_state = get_stored_os_metrics_state(collection)
    state = build_os_metrics_state(previous_state, int(time.time()), changed_rows, stale_ids, day)
    update: Dict[str, Any] = {"$set": {"aggregation_period": OS_METRICS_STATE_ID, **state}}
    if rebuild_ids:
        update["$pullAll"] = {"rebuilding": rebuild_ids}
    collection.update_one({"id": OS_METRICS_STATE_ID}, update, upsert=True)


async def aget_stored_os_metrics_state(collection: "AsyncMongoCollectionType") -> Dict[str, Any]:
    """Get the state of the OS metrics, from the state record.

    Args:
        collection (AsyncMongoCollectionType): The OS metrics collection.

    Returns:
        Dict[str, Any]: The state, as build_os_metrics_state builds it. Empty for a collection no rebuild has
            written to.
    """
    return (await collection.find_one({"id": OS_METRICS_STATE_ID}, {"_id": 0})) or {}


async def amark_os_metrics_state(collection: "AsyncMongoCollectionType", rebuild_id: str) -> None:
    """Mark the state record before a rebuild writes or deletes records of a day.

    A day saved without its state leaves the mark, so the state is not taken as the state of its records.

    Args:
        collection (AsyncMongoCollectionType): The OS metrics collection.
        rebuild_id (str): The id the rebuild marks the state with. Its state write takes the mark off.
    """
    await collection.update_one(
        {"id": OS_METRICS_STATE_ID},
        {"$set": {"aggregation_period": OS_METRICS_STATE_ID}, "$addToSet": {"rebuilding": rebuild_id}},
        upsert=True,
    )


async def aupdate_os_metrics_state(
    collection: "AsyncMongoCollectionType",
    changed_rows: Sequence[Dict[str, Any]],
    stale_ids: Sequence[str],
    day: Optional[date] = None,
    rebuild_ids: Optional[List[str]] = None,
) -> None:
    """Write the state record after a rebuild wrote or deleted records of a day.

    Args:
        collection (AsyncMongoCollectionType): The OS metrics collection.
        changed_rows (Sequence[Dict[str, Any]]): The records the rebuild wrote.
        stale_ids (Sequence[str]): The ids of the records the rebuild deleted.
        day (Optional[date]): The day the records are of. ``None`` when they may not all be saved.
        rebuild_ids (Optional[List[str]]): The marks to take off the state.
    """
    previous_state = await aget_stored_os_metrics_state(collection)
    state = build_os_metrics_state(previous_state, int(time.time()), changed_rows, stale_ids, day)
    update: Dict[str, Any] = {"$set": {"aggregation_period": OS_METRICS_STATE_ID, **state}}
    if rebuild_ids:
        update["$pullAll"] = {"rebuilding": rebuild_ids}
    await collection.update_one({"id": OS_METRICS_STATE_ID}, update, upsert=True)


def build_os_metrics_runs_pipeline(start_timestamp: int, end_timestamp: int) -> List[Dict[str, Any]]:
    """Build the pipeline that reads the runs created in the given time range, with only what OS metrics count."""
    return [
        {"$match": {"created_at": {"$gte": start_timestamp, "$lt": end_timestamp}}},
        {"$project": _OS_METRICS_RUNS_PROJECTION},
    ]


def build_os_metrics_sessions_pipeline(start_timestamp: int, end_timestamp: int) -> List[Dict[str, Any]]:
    """Build the pipeline that reads the sessions created in the given time range, with only what OS metrics count."""
    return [
        {"$match": {"created_at": {"$gte": start_timestamp, "$lt": end_timestamp}}},
        {"$project": _OS_METRICS_SESSIONS_PROJECTION},
    ]


def build_os_metrics_stored_rows_filter(date_to_process: date) -> Dict[str, Any]:
    """Build the filter that reads the records stored for a day."""
    return {"date": date_to_process.isoformat(), "aggregation_period": {"$in": list(OS_METRICS_DAY_PERIODS)}}


def build_os_metrics_total_dates_filter(
    starting_date: Optional[date] = None, ending_date: Optional[date] = None
) -> Dict[str, Any]:
    """Build the filter that reads the total record of every completed day in the given date range."""
    # A total record that is not completed belongs to a day whose write failed part way
    total_dates_filter: Dict[str, Any] = {"user_id": "", "aggregation_period": "daily_total", "completed": True}
    if starting_date is not None:
        total_dates_filter.setdefault("date", {})["$gte"] = starting_date.isoformat()
    if ending_date is not None:
        total_dates_filter.setdefault("date", {})["$lte"] = ending_date.isoformat()
    return total_dates_filter


def deserialize_os_metrics_record(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Deserialize a stored document to an OS metrics record, in the shape calculate_date_os_metrics writes."""
    return {**doc, "date": datetime.strptime(doc["date"], "%Y-%m-%d").date()}


def build_os_metrics_totals_pipelines(
    starting_date: date,
    ending_date: date,
    user_id: Optional[str],
    fields: Sequence[str],
    total_days: Optional[Sequence[date]] = None,
    row_days: Optional[Sequence[date]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build the pipelines that total the OS metrics records of each day in the given date range."""
    match_stage: Dict[str, Any] = {"aggregation_period": "daily"}
    if row_days is None:
        match_stage["date"] = {"$gte": starting_date.isoformat(), "$lte": ending_date.isoformat()}
    elif row_days:
        # Days that follow one another are looked up as one range
        match_stage["$or"] = [
            {"date": {"$gte": first_day.isoformat(), "$lte": last_day.isoformat()}}
            for first_day, last_day in os_metrics_day_ranges(row_days)
        ]
    else:
        match_stage["date"] = {"$in": []}
    if user_id is not None:
        match_stage["user_id"] = user_id
    if total_days:
        match_stage = {
            "$or": [
                match_stage,
                {
                    "user_id": "",
                    "aggregation_period": "daily_total",
                    "date": {"$in": [day.isoformat() for day in total_days]},
                },
            ]
        }

    group_stage: Dict[str, Any] = {"_id": "$date", "updated_at": {"$max": "$updated_at"}}
    for field in fields:
        if field in ["sessions_count", "runs_count"]:
            group_stage[field] = {"$sum": f"${field}"}
        elif field in OS_METRICS_FIXED_KEYS:
            # $sum gives 0 for a key no record reported, so how many reported it is counted too
            for key in OS_METRICS_FIXED_KEYS[field]:
                is_max = key in ["max_duration_ms", "max_time_to_first_token_ms", "max_model_call_ms"]
                group_stage[f"{field}__{key}"] = {"$max" if is_max else "$sum": f"${field}.{key}"}
                group_stage[f"{field}__{key}__records"] = {
                    "$sum": {"$cond": [{"$gt": [f"${field}.{key}", None]}, 1, 0]}
                }
    pipelines: Dict[str, List[Dict[str, Any]]] = {"totals": [{"$match": match_stage}, {"$group": group_stage}]}

    if "duration_buckets" in fields:
        pipelines["duration_buckets"] = [
            {"$match": match_stage},
            {
                "$project": {
                    "date": 1,
                    "buckets": {
                        "$concatArrays": [
                            {
                                "$map": {
                                    "input": {"$objectToArray": {"$ifNull": [f"$duration_metrics.{bucket_field}", {}]}},
                                    "in": {"bucket_field": bucket_field, "bucket": "$$this.k", "count": "$$this.v"},
                                }
                            }
                            for bucket_field in [
                                "duration_ms_buckets",
                                "time_to_first_token_ms_buckets",
                                "model_call_ms_buckets",
                            ]
                        ]
                    },
                }
            },
            {"$unwind": "$buckets"},
            {
                "$group": {
                    "_id": {"date": "$date", "bucket_field": "$buckets.bucket_field", "bucket": "$buckets.bucket"},
                    "count": {"$sum": "$buckets.count"},
                }
            },
        ]

    if "model_metrics" in fields:
        pipelines["model_metrics"] = [
            {"$match": match_stage},
            {"$unwind": "$model_metrics"},
            {
                "$group": {
                    "_id": {
                        "date": "$date",
                        "model_id": {"$ifNull": ["$model_metrics.model_id", ""]},
                        "model_provider": {"$ifNull": ["$model_metrics.model_provider", ""]},
                        "agent_id": {"$ifNull": ["$model_metrics.agent_id", ""]},
                        "team_id": {"$ifNull": ["$model_metrics.team_id", ""]},
                        "workflow_id": {"$ifNull": ["$model_metrics.workflow_id", ""]},
                    },
                    "count": {"$sum": "$model_metrics.count"},
                }
            },
        ]

    return pipelines


def build_os_metrics_totals(
    fields: Sequence[str],
    results_by_pipeline: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Build the OS metrics totals of each day from the results of the totals pipelines."""
    totals_by_date: Dict[date, Dict[str, Any]] = {}
    latest_updated_at: Optional[int] = None
    for result in results_by_pipeline["totals"]:
        day = datetime.strptime(result["_id"], "%Y-%m-%d").date()
        day_totals: Dict[str, Any] = {"date": day}
        for field in fields:
            if field in ["sessions_count", "runs_count"]:
                day_totals[field] = int(result.get(field) or 0)
            elif field in OS_METRICS_FIXED_KEYS:
                # A key no record reported stays out, as it would in a stored record
                day_totals[field] = {
                    key: int(result[f"{field}__{key}"] or 0)
                    for key in OS_METRICS_FIXED_KEYS[field]
                    if result[f"{field}__{key}__records"]
                }
            elif field == "model_metrics":
                day_totals[field] = []
            else:
                day_totals[field] = {}
        totals_by_date[day] = day_totals
        updated_at = result.get("updated_at")
        if updated_at is not None and (latest_updated_at is None or updated_at > latest_updated_at):
            latest_updated_at = updated_at

    for result in results_by_pipeline.get("duration_buckets", []):
        bucket_totals = totals_by_date.get(datetime.strptime(result["_id"]["date"], "%Y-%m-%d").date())
        if bucket_totals is not None:
            bucket_totals["duration_buckets"].setdefault(result["_id"]["bucket_field"], {})[result["_id"]["bucket"]] = (
                int(result["count"])
            )

    for result in results_by_pipeline.get("model_metrics", []):
        model_totals = totals_by_date.get(datetime.strptime(result["_id"]["date"], "%Y-%m-%d").date())
        if model_totals is None:
            continue
        model: Dict[str, Any] = {
            "model_id": result["_id"]["model_id"],
            "model_provider": result["_id"]["model_provider"],
        }
        if result["_id"]["agent_id"]:
            model["agent_id"] = result["_id"]["agent_id"]
        if result["_id"]["team_id"]:
            model["team_id"] = result["_id"]["team_id"]
        if result["_id"]["workflow_id"]:
            model["workflow_id"] = result["_id"]["workflow_id"]
        model["count"] = int(result["count"] or 0)
        model_totals["model_metrics"].append(model)

    return [totals_by_date[day] for day in sorted(totals_by_date)], latest_updated_at
