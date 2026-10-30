"""Utility functions for the MongoDB database class."""

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from agno.db.mongo.schemas import get_collection_indexes
from agno.db.utils import (
    OS_METRICS_COUNT_MAP_COLUMNS,
    OS_METRICS_MAX_COLUMNS,
    OS_METRICS_SUM_COLUMNS,
    empty_os_metrics_totals,
    os_metrics_day_ranges,
    os_metrics_days_to_read,
)
from agno.utils.log import log_error, log_info, log_warning

try:
    from pymongo import ReturnDocument, UpdateOne
    from pymongo.collection import Collection
    from pymongo.errors import DuplicateKeyError, OperationFailure
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it using `pip install pymongo`")

if TYPE_CHECKING:
    from agno.db.mongo.async_mongo import AsyncMongoCollectionType


LEGACY_METRICS_INDEX = "date_1_aggregation_period_1"
INDEX_NOT_FOUND = 27  # MongoDB's IndexNotFound error code

# Keeps an $in list far below the 16MB a query document can hold
OS_METRICS_IN_LIST_LIMIT = 10000

# Rows a rebuild reads at a time, so a day or a month of many rows is never held or decoded in one step
OS_METRICS_BATCH_SIZE = 1000

# The document of the OS metrics collection a rebuild holds while it writes. A rebuild that stopped
# without releasing it is taken over once it is OS_METRICS_LOCK_SECONDS old
OS_METRICS_LOCK_ID = "os_metrics_lock"
OS_METRICS_LOCK_SECONDS = 60

# How long a rebuild that waits for the lock sleeps before it tries again
OS_METRICS_LOCK_RETRY_SECONDS = 0.1

# The keys of a stored run that hold the runs nested inside it
_OS_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses", "workflow_agent_run")

# A run nested this many levels deep is read whole
_OS_METRICS_NESTED_RUNS_DEPTH = 6

# What OS metrics count of a run and of every run nested inside it. Of the messages only each
# request's duration is read, never the content
_OS_METRICS_RUN_DATA_FIELDS = (
    "run_id",
    "metrics",
    "model",
    "model_provider",
    "messages.role",
    "messages.from_history",
    "messages.metrics.duration",
    "forked_from_message_index",
)


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
def build_os_metrics_runs_projection() -> Dict[str, int]:
    """Build the projection of a stored run with only what OS metrics count, at any depth of nested runs."""
    projection = {
        "run_id": 1,
        "run_type": 1,
        "agent_id": 1,
        "team_id": 1,
        "workflow_id": 1,
        "user_id": 1,
        "parent_run_id": 1,
        "status": 1,
        "run_data.forked_from_session_id": 1,
    }
    paths = ["run_data"]
    for _ in range(_OS_METRICS_NESTED_RUNS_DEPTH):
        for path in paths:
            for field in _OS_METRICS_RUN_DATA_FIELDS:
                projection[f"{path}.{field}"] = 1
        nested_paths = []
        for path in paths:
            for key in _OS_METRICS_NESTED_RUN_KEYS:
                nested_paths.append(f"{path}.{key}")
        paths = nested_paths
    for path in paths:
        projection[path] = 1
    return projection


def deserialize_os_metrics_row(document: Dict[str, Any]) -> Dict[str, Any]:
    """Deserialize a stored OS metrics document to the row shape the OS metrics helpers compare and total."""
    return {**document, "date": datetime.strptime(document["date"], "%Y-%m-%d").date()}


def _os_metrics_upserts(os_metrics_records: List[Dict[str, Any]]) -> List[UpdateOne]:
    """Build the upsert of each OS metrics record, matched on its key."""
    upserts = []
    for record in os_metrics_records:
        document = {**record, "date": record["date"].isoformat()}
        key_filter = {
            "aggregation_period": document["aggregation_period"],
            "date": document["date"],
            "user_id": document["user_id"],
            "component_type": document["component_type"],
            "component_id": document["component_id"],
            "parent_component_id": document["parent_component_id"],
        }
        # The key and created_at are never overwritten
        fields = {
            key: value
            for key, value in document.items()
            if key
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
        upserts.append(
            UpdateOne(key_filter, {"$set": fields, "$setOnInsert": {"created_at": document["created_at"]}}, upsert=True)
        )
    return upserts


def bulk_upsert_os_metrics(collection: Collection, os_metrics_records: List[Dict[str, Any]]) -> None:
    """Bulk upsert OS metrics into the database, in the order given.

    Args:
        collection (Collection): The collection to upsert the OS metrics into.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    collection.bulk_write(_os_metrics_upserts(os_metrics_records))


async def abulk_upsert_os_metrics(
    collection: "AsyncMongoCollectionType", os_metrics_records: List[Dict[str, Any]]
) -> None:
    """Async bulk upsert OS metrics into the database, in the order given.

    Args:
        collection (AsyncMongoCollectionType): The async collection to upsert the OS metrics into.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
    """
    if not os_metrics_records:
        return

    await collection.bulk_write(_os_metrics_upserts(os_metrics_records))


def _os_metrics_totals_upsert(totals_row: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build the filter and the update of the upsert of an OS metrics totals row.

    A new row starts at version 1, which $inc sets on a document without one, and every write of a stored
    one moves its version by one in the same update, so two writers never give it the same version.

    Args:
        totals_row (Dict[str, Any]): The row, from build_os_metrics_totals_row.

    Returns:
        Tuple[Dict[str, Any], Dict[str, Any]]: The filter and the update.
    """
    document = {**totals_row, "date": totals_row["date"].isoformat()}
    key_filter = {"aggregation_period": document["aggregation_period"], "date": document["date"]}
    # The key and created_at are never overwritten
    fields = {
        key: value
        for key, value in document.items()
        if key not in ["aggregation_period", "date", "created_at", "version"]
    }
    update = {
        "$set": fields,
        "$setOnInsert": {"created_at": document["created_at"]},
        "$inc": {"version": 1},
        "$unset": {"rows_pending": ""},
    }
    return key_filter, update


def upsert_os_metrics_totals_row(collection: Collection, totals_row: Dict[str, Any]) -> None:
    """Upsert an OS metrics totals row into the database.

    Args:
        collection (Collection): The OS metrics totals collection.
        totals_row (Dict[str, Any]): The row, from build_os_metrics_totals_row.
    """
    key_filter, update = _os_metrics_totals_upsert(totals_row)
    collection.update_one(key_filter, update, upsert=True)


async def aupsert_os_metrics_totals_row(collection: "AsyncMongoCollectionType", totals_row: Dict[str, Any]) -> None:
    """Async upsert an OS metrics totals row into the database.

    Args:
        collection (AsyncMongoCollectionType): The OS metrics totals collection.
        totals_row (Dict[str, Any]): The row, from build_os_metrics_totals_row.
    """
    key_filter, update = _os_metrics_totals_upsert(totals_row)
    await collection.update_one(key_filter, update, upsert=True)


def _os_metrics_lock_claim(rebuild_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build the filter and the update that take the OS metrics lock when no rebuild holds it.

    A held lock fails the filter, so the upsert inserts a second document with the lock's _id and is refused
    with a duplicate key error.
    """
    now = int(time.time())
    lock_filter = {
        "_id": OS_METRICS_LOCK_ID,
        "$or": [
            {"locked_by": None},
            {"locked_at": {"$lte": now - OS_METRICS_LOCK_SECONDS}},
        ],
    }
    return lock_filter, {"$set": {"locked_by": rebuild_id, "locked_at": now}}


def lock_os_metrics(collection: Collection, rebuild_id: str, wait_for_rebuild: bool) -> bool:
    """Take the lock that lets one rebuild at a time write OS metrics.

    Args:
        collection (Collection): The OS metrics collection, which holds the lock document.
        rebuild_id (str): The id of the rebuild taking the lock.
        wait_for_rebuild (bool): Wait for a rebuild another process is running. When False, give up instead.

    Returns:
        bool: Whether the lock was taken.
    """
    while True:
        lock_filter, update = _os_metrics_lock_claim(rebuild_id)
        try:
            collection.update_one(lock_filter, update, upsert=True)
            return True
        except DuplicateKeyError:
            if not wait_for_rebuild:
                return False
        time.sleep(OS_METRICS_LOCK_RETRY_SECONDS)


async def alock_os_metrics(collection: "AsyncMongoCollectionType", rebuild_id: str, wait_for_rebuild: bool) -> bool:
    """Take the lock that lets one rebuild at a time write OS metrics.

    Args:
        collection (AsyncMongoCollectionType): The OS metrics collection, which holds the lock document.
        rebuild_id (str): The id of the rebuild taking the lock.
        wait_for_rebuild (bool): Wait for a rebuild another process is running. When False, give up instead.

    Returns:
        bool: Whether the lock was taken.
    """
    while True:
        lock_filter, update = _os_metrics_lock_claim(rebuild_id)
        try:
            await collection.update_one(lock_filter, update, upsert=True)
            return True
        except DuplicateKeyError:
            if not wait_for_rebuild:
                return False
        await asyncio.sleep(OS_METRICS_LOCK_RETRY_SECONDS)


def extend_os_metrics_lock(collection: Collection, rebuild_id: str) -> bool:
    """Hold the OS metrics lock for OS_METRICS_LOCK_SECONDS more, when the given rebuild still holds it.

    Args:
        collection (Collection): The OS metrics collection, which holds the lock document.
        rebuild_id (str): The id of the rebuild that took the lock.

    Returns:
        bool: Whether the rebuild still holds the lock.
    """
    result = collection.update_one(
        {"_id": OS_METRICS_LOCK_ID, "locked_by": rebuild_id}, {"$set": {"locked_at": int(time.time())}}
    )
    return result.matched_count == 1


async def aextend_os_metrics_lock(collection: "AsyncMongoCollectionType", rebuild_id: str) -> bool:
    """Hold the OS metrics lock for OS_METRICS_LOCK_SECONDS more, when the given rebuild still holds it.

    Args:
        collection (AsyncMongoCollectionType): The OS metrics collection, which holds the lock document.
        rebuild_id (str): The id of the rebuild that took the lock.

    Returns:
        bool: Whether the rebuild still holds the lock.
    """
    result = await collection.update_one(
        {"_id": OS_METRICS_LOCK_ID, "locked_by": rebuild_id}, {"$set": {"locked_at": int(time.time())}}
    )
    return result.matched_count == 1


def unlock_os_metrics(collection: Collection, rebuild_id: str) -> None:
    """Release the OS metrics lock, when the given rebuild still holds it.

    Args:
        collection (Collection): The OS metrics collection, which holds the lock document.
        rebuild_id (str): The id of the rebuild that took the lock.
    """
    collection.update_one(
        {"_id": OS_METRICS_LOCK_ID, "locked_by": rebuild_id}, {"$set": {"locked_by": None, "locked_at": None}}
    )


async def aunlock_os_metrics(collection: "AsyncMongoCollectionType", rebuild_id: str) -> None:
    """Release the OS metrics lock, when the given rebuild still holds it.

    Args:
        collection (AsyncMongoCollectionType): The OS metrics collection, which holds the lock document.
        rebuild_id (str): The id of the rebuild that took the lock.
    """
    await collection.update_one(
        {"_id": OS_METRICS_LOCK_ID, "locked_by": rebuild_id}, {"$set": {"locked_by": None, "locked_at": None}}
    )


def build_os_metrics_totals_pipeline(
    starting_date: date,
    ending_date: date,
    user_id: Optional[str],
    fields: Sequence[str],
    month_starts: Sequence[date] = (),
) -> List[Dict[str, Any]]:
    """Build the pipeline that totals the OS metrics of each day in the given date range.

    Every total comes from one aggregate, so each document read adds its counts, maps and models as one
    version of it.

    Args:
        starting_date (date): The first day to total.
        ending_date (date): The last day to total.
        user_id (Optional[str]): The user whose OS metrics documents are totalled. ``None`` for the totals
            collection.
        fields (Sequence[str]): The fields to total.
        month_starts (Sequence[date]): The first day of every month inside the date range to total from its month
            documents instead of its days.

    Returns:
        List[Dict[str, Any]]: The pipeline, one result per date, field and key. Empty when there is no day to
            total.
    """
    # Days that follow one another are looked up as one range
    filters: List[Dict[str, Any]] = [
        {"aggregation_period": "daily", "date": {"$gte": first_day.isoformat(), "$lte": last_day.isoformat()}}
        for first_day, last_day in os_metrics_day_ranges(
            os_metrics_days_to_read(starting_date, ending_date, month_starts)
        )
    ]
    if month_starts:
        filters.append(
            {
                "aggregation_period": "monthly",
                "date": {"$in": [month_start.isoformat() for month_start in month_starts]},
            }
        )
    if not filters:
        return []
    if user_id is not None:
        # In every branch, so each is read through the index on user_id, aggregation_period and date
        filters = [{"user_id": user_id, **date_filter} for date_filter in filters]

    # Each document becomes one entry per value it adds to a total
    totals = [{"field": "updated_at", "key": None, "value": "$updated_at"}]
    for field in fields:
        if field in OS_METRICS_SUM_COLUMNS or field in OS_METRICS_MAX_COLUMNS:
            totals.append({"field": field, "key": None, "value": f"${field}"})
    entries: List[Any] = [totals]
    # Each key of a map of counts totalled on its own
    for field in fields:
        if field in OS_METRICS_COUNT_MAP_COLUMNS:
            entries.append(
                {
                    "$map": {
                        "input": {"$objectToArray": {"$ifNull": [f"${field}", {}]}},
                        "in": {"field": field, "key": "$$this.k", "value": "$$this.v"},
                    }
                }
            )
    # Only the numbers of additional_metrics are totalled; the rest keeps no meaning across documents
    if "additional_metrics" in fields:
        entries.append(
            {
                "$map": {
                    "input": {
                        "$filter": {
                            "input": {"$objectToArray": {"$ifNull": ["$additional_metrics", {}]}},
                            "cond": {"$isNumber": "$$this.v"},
                        }
                    },
                    "in": {"field": "additional_metrics", "key": "$$this.k", "value": "$$this.v"},
                }
            }
        )
    if "model_metrics" in fields:
        entries.append(
            {
                "$map": {
                    "input": {"$ifNull": ["$model_metrics", []]},
                    "in": {
                        "field": "model_metrics",
                        "key": {"model_id": "$$this.model_id", "model_provider": "$$this.model_provider"},
                        "value": "$$this.count",
                    },
                }
            }
        )

    return [
        {"$match": {"$or": filters}},
        {"$project": {"_id": 0, "date": 1, "entries": {"$concatArrays": entries}}},
        {"$unwind": "$entries"},
        {
            "$group": {
                "_id": {"date": "$date", "field": "$entries.field", "key": "$entries.key"},
                "sum": {"$sum": "$entries.value"},
                "max": {"$max": "$entries.value"},
            }
        },
    ]


def build_os_metrics_totals(
    fields: Sequence[str],
    results: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Build the OS metrics totals of each date from the results of the totals pipeline.

    Args:
        fields (Sequence[str]): The fields that were totalled.
        results (Sequence[Dict[str, Any]]): The results of build_os_metrics_totals_pipeline.

    Returns:
        Tuple[List[Dict[str, Any]], Optional[int]]: One dict per date, oldest first, and when the documents were
            last updated. A month totalled from its month documents is one dict, dated its first day.
    """
    totals_by_date: Dict[date, Dict[str, Any]] = {}
    latest_updated_at: Optional[int] = None
    for result in results:
        day = datetime.strptime(result["_id"]["date"], "%Y-%m-%d").date()
        day_totals = totals_by_date.setdefault(day, {"date": day, **empty_os_metrics_totals(fields)})
        field = result["_id"]["field"]
        key = result["_id"].get("key")
        if field == "updated_at":
            if result["max"] is not None and (latest_updated_at is None or result["max"] > latest_updated_at):
                latest_updated_at = result["max"]
        elif field in OS_METRICS_SUM_COLUMNS:
            day_totals[field] = int(result["sum"])
        elif field in OS_METRICS_MAX_COLUMNS:
            if result["max"] is not None:
                day_totals[field] = int(result["max"])
        elif field in OS_METRICS_COUNT_MAP_COLUMNS:
            day_totals[field][key] = int(result["sum"])
        elif field == "additional_metrics":
            # A whole number comes back a whole number
            value = result["sum"]
            day_totals[field][key] = int(value) if value == int(value) else float(value)
        elif field == "model_metrics":
            day_totals[field].append(
                {
                    "model_id": key.get("model_id"),
                    "model_provider": key.get("model_provider"),
                    "count": int(result["sum"]),
                }
            )

    for day_totals in totals_by_date.values():
        if "model_metrics" in day_totals:
            day_totals["model_metrics"].sort(key=lambda x: (x["model_id"], x["model_provider"]))

    return [totals_by_date[day] for day in sorted(totals_by_date)], latest_updated_at
