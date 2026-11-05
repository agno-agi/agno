"""Utility functions for the MongoDB database class."""

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from agno.db.mongo.schemas import get_collection_indexes
from agno.db.utils import (
    COMPONENT_METRICS_KEY_COLUMNS,
    METRICS_COMPONENT_TYPES,
    METRICS_COST_FIELDS,
    METRICS_TOKEN_DETAILS_FIELDS,
    METRICS_TOKEN_FIELDS,
    AGGREGATE_METRICS_KEY_COLUMNS,
    build_aggregate_metrics_row,
    list_metrics_models,
    metrics_day_ranges,
    metrics_days_to_read,
)
from agno.utils.log import log_info, log_warning

try:
    from pymongo import UpdateOne
    from pymongo.collection import Collection
    from pymongo.errors import OperationFailure
except ImportError:
    raise ImportError("`pymongo` not installed. Please install it using `pip install pymongo`")

if TYPE_CHECKING:
    from agno.db.mongo.async_mongo import AsyncMongoCollectionType


LEGACY_METRICS_INDEX = "date_1_aggregation_period_1"
INDEX_NOT_FOUND = 27  # MongoDB's IndexNotFound error code

# A query document holds 16 MB at most, so $in lists are sent in chunks
METRICS_IN_LIST_LIMIT = 10000


# The keys of a stored run that hold the runs nested inside it, read whole, and only from the runs that have them
_METRICS_NESTED_RUN_KEYS = ("step_executor_runs", "member_responses", "workflow_agent_run")

# What component metrics count of a run. Of the messages only each request's duration is read, never the content
_METRICS_RUN_DATA_FIELDS = (
    "run_id",
    "metrics",
    "model",
    "model_provider",
    "messages.role",
    "messages.from_history",
    "messages.metrics.duration",
    "forked_from_message_index",
)

# What a legacy run keeps of its own beside run_data: the fields the runs collection keeps a column of
_METRICS_LEGACY_RUN_FIELDS = (
    "agent_id",
    "team_id",
    "workflow_id",
    "parent_run_id",
    "status",
    "created_at",
    "called_from_run_id",
    "forked_from_session_id",
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


# -- Component metrics util methods --
def build_component_metrics_runs_projection() -> Dict[str, int]:
    """Build the projection of a stored run with only what component metrics count, and the runs nested inside it."""
    return {
        "_id": 0,
        "run_id": 1,
        "session_id": 1,
        "run_type": 1,
        "agent_id": 1,
        "team_id": 1,
        "workflow_id": 1,
        "user_id": 1,
        "parent_run_id": 1,
        "status": 1,
        "created_at": 1,
        "run_data.called_from_run_id": 1,
        **{f"run_data.{field}": 1 for field in _METRICS_RUN_DATA_FIELDS},
        **{f"run_data.{key}": 1 for key in _METRICS_NESTED_RUN_KEYS},
    }


def build_component_metrics_legacy_runs_projection() -> Dict[str, int]:
    """Build the projection of a session with only what component metrics count of the runs of its legacy runs
    field, and the runs nested inside them."""
    return {
        "_id": 0,
        "session_id": 1,
        "user_id": 1,
        "created_at": 1,
        **{f"runs.{field}": 1 for field in _METRICS_LEGACY_RUN_FIELDS},
        **{f"runs.{field}": 1 for field in _METRICS_RUN_DATA_FIELDS},
        **{f"runs.{key}": 1 for key in _METRICS_NESTED_RUN_KEYS},
    }


def serialize_metrics_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a metrics row to the document stored for it: its date as text, and its models as the list
    agno_metrics keeps, so no model id becomes a field name."""
    document = {**row, "date": row["date"].isoformat()}
    if "model_metrics" in document:
        document["model_metrics"] = list_metrics_models(document["model_metrics"])
    return document


def deserialize_metrics_row(document: Dict[str, Any]) -> Dict[str, Any]:
    """Deserialize a stored metrics document to the row shape the metrics helpers compare and total."""
    row = {**document, "date": datetime.strptime(document["date"], "%Y-%m-%d").date()}
    if "model_metrics" in row:
        model_metrics: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for model in row["model_metrics"] or []:
            model_totals: Dict[str, Any] = {"count": model["count"]}
            if model.get("cost") is not None:
                model_totals["cost"] = model["cost"]
            model_metrics.setdefault(model["model_provider"], {})[model["model_id"]] = model_totals
        row["model_metrics"] = model_metrics
    return row


def _component_metrics_upserts(component_metrics_records: List[Dict[str, Any]]) -> List[UpdateOne]:
    """Build the upsert of each component metrics record, matched on its key."""
    upserts = []
    for record in component_metrics_records:
        document = serialize_metrics_row(record)
        # The key and created_at are never overwritten
        fields = {
            key: value for key, value in document.items() if key not in [*COMPONENT_METRICS_KEY_COLUMNS, "created_at"]
        }
        upserts.append(
            UpdateOne(
                {column: document[column] for column in COMPONENT_METRICS_KEY_COLUMNS},
                {"$set": fields, "$setOnInsert": {"created_at": document["created_at"]}},
                upsert=True,
            )
        )
    return upserts


def bulk_upsert_component_metrics(collection: Collection, component_metrics_records: List[Dict[str, Any]]) -> None:
    """Bulk upsert component metrics into the database, in one request.

    Args:
        collection (Collection): The component metrics collection.
        component_metrics_records (List[Dict[str, Any]]): The component metrics records to upsert.
    """
    if not component_metrics_records:
        return

    collection.bulk_write(_component_metrics_upserts(component_metrics_records))


async def abulk_upsert_component_metrics(
    collection: "AsyncMongoCollectionType", component_metrics_records: List[Dict[str, Any]]
) -> None:
    """Bulk upsert component metrics into the database, in one request.

    Args:
        collection (AsyncMongoCollectionType): The component metrics collection.
        component_metrics_records (List[Dict[str, Any]]): The component metrics records to upsert.
    """
    if not component_metrics_records:
        return

    await collection.bulk_write(_component_metrics_upserts(component_metrics_records))


def _aggregate_metrics_upsert(
    aggregate_metrics_row: Dict[str, Any], read_version: Optional[int]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Build the filter and the update of the upsert of an aggregate metrics row.

    A new row starts at version 1, and every write of a stored one moves its version by one in the same update, so
    two writers never give it the same version.

    Args:
        aggregate_metrics_row (Dict[str, Any]): The row, from build_aggregate_metrics_row.
        read_version (Optional[int]): The version of the stored row read before its rows were rebuilt. None when
            there was no stored row.

    Returns:
        Tuple[Dict[str, Any], List[Dict[str, Any]]]: The filter and the update pipeline.
    """
    document = serialize_metrics_row(aggregate_metrics_row)
    # The key and created_at are never overwritten. Each value is a literal, so a string starting with $ is never
    # read as a field
    fields: Dict[str, Any] = {
        key: {"$literal": value}
        for key, value in document.items()
        if key not in [*AGGREGATE_METRICS_KEY_COLUMNS, "created_at", "version", "completed"]
    }
    fields["created_at"] = {"$ifNull": ["$created_at", {"$literal": document["created_at"]}]}
    fields["version"] = {"$add": [{"$ifNull": ["$version", 0]}, 1]}
    # Compared in the update, so a reopen written since the version was read keeps the period open
    fields["completed"] = {
        "$cond": [
            {"$eq": [{"$type": "$version"}, "missing"]},
            document["completed"],
            {"$and": [document["completed"], {"$eq": ["$version", {"$literal": read_version}]}]},
        ]
    }
    key_filter = {column: document[column] for column in AGGREGATE_METRICS_KEY_COLUMNS}
    return key_filter, [{"$set": fields}]


def upsert_aggregate_metrics_row(
    collection: Collection, aggregate_metrics_row: Dict[str, Any], read_version: Optional[int]
) -> None:
    """Upsert an aggregate metrics row into the database.

    Args:
        collection (Collection): The aggregate metrics collection.
        aggregate_metrics_row (Dict[str, Any]): The row, from build_aggregate_metrics_row.
        read_version (Optional[int]): The version of the stored row read before its rows were rebuilt.
    """
    key_filter, update = _aggregate_metrics_upsert(aggregate_metrics_row, read_version)
    collection.update_one(key_filter, update, upsert=True)


async def aupsert_aggregate_metrics_row(
    collection: "AsyncMongoCollectionType", aggregate_metrics_row: Dict[str, Any], read_version: Optional[int]
) -> None:
    """Upsert an aggregate metrics row into the database.

    Args:
        collection (AsyncMongoCollectionType): The aggregate metrics collection.
        aggregate_metrics_row (Dict[str, Any]): The row, from build_aggregate_metrics_row.
        read_version (Optional[int]): The version of the stored row read before its rows were rebuilt.
    """
    key_filter, update = _aggregate_metrics_upsert(aggregate_metrics_row, read_version)
    await collection.update_one(key_filter, update, upsert=True)


def _aggregate_metrics_rows_upserts(aggregate_metrics_rows: List[Dict[str, Any]]) -> List[UpdateOne]:
    """Build the upsert of each user row of the aggregate metrics collection. A user row is written with its period's
    everyone row, so its completed and version are never compared."""
    upserts = []
    for aggregate_metrics_row in aggregate_metrics_rows:
        document = serialize_metrics_row(aggregate_metrics_row)
        # The key and created_at are never overwritten
        fields = {
            key: value
            for key, value in document.items()
            if key not in [*AGGREGATE_METRICS_KEY_COLUMNS, "created_at", "version"]
        }
        upserts.append(
            UpdateOne(
                {column: document[column] for column in AGGREGATE_METRICS_KEY_COLUMNS},
                {"$set": fields, "$setOnInsert": {"created_at": document["created_at"]}, "$inc": {"version": 1}},
                upsert=True,
            )
        )
    return upserts


def bulk_upsert_aggregate_metrics_rows(collection: Collection, aggregate_metrics_rows: List[Dict[str, Any]]) -> None:
    """Bulk upsert the user rows of a period into the aggregate metrics collection, in one request.

    Args:
        collection (Collection): The aggregate metrics collection.
        aggregate_metrics_rows (List[Dict[str, Any]]): The user rows, from build_aggregate_metrics_rows.
    """
    if not aggregate_metrics_rows:
        return
    collection.bulk_write(_aggregate_metrics_rows_upserts(aggregate_metrics_rows))


async def abulk_upsert_aggregate_metrics_rows(
    collection: "AsyncMongoCollectionType", aggregate_metrics_rows: List[Dict[str, Any]]
) -> None:
    """Bulk upsert the user rows of a period into the aggregate metrics collection, in one request.

    Args:
        collection (AsyncMongoCollectionType): The aggregate metrics collection.
        aggregate_metrics_rows (List[Dict[str, Any]]): The user rows, from build_aggregate_metrics_rows.
    """
    if not aggregate_metrics_rows:
        return
    await collection.bulk_write(_aggregate_metrics_rows_upserts(aggregate_metrics_rows))


def _reopen_metrics_row(row_date: date, aggregation_period: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build the filter and the update that reopen a day's or a month's everyone row of the aggregate metrics collection,
    inserting an empty open row when it has none."""
    empty_row = serialize_metrics_row(build_aggregate_metrics_row([], aggregation_period, row_date, completed=False))
    key_filter = {column: empty_row[column] for column in AGGREGATE_METRICS_KEY_COLUMNS}
    update = {
        "$set": {"completed": False},
        "$inc": {"version": 1},
        "$setOnInsert": {
            key: value for key, value in empty_row.items() if key not in [*AGGREGATE_METRICS_KEY_COLUMNS, "completed"]
        },
    }
    return key_filter, update


def reopen_metrics_day(collection: Collection, day: date) -> None:
    """Reopen a day's aggregate metrics row, so the next refresh rebuilds the day.

    Args:
        collection (Collection): The aggregate metrics collection.
        day (date): The day, from metrics_day_to_reopen.
    """
    collection.update_one(*_reopen_metrics_row(day, "daily"), upsert=True)


async def areopen_metrics_day(collection: "AsyncMongoCollectionType", day: date) -> None:
    """Reopen a day's aggregate metrics row, so the next refresh rebuilds the day.

    Args:
        collection (AsyncMongoCollectionType): The aggregate metrics collection.
        day (date): The day, from metrics_day_to_reopen.
    """
    await collection.update_one(*_reopen_metrics_row(day, "daily"), upsert=True)


def _reopen_metrics_days_from(starting_date: date) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build the filter and the update that reopen every day's everyone row of the aggregate metrics collection from the
    given date on."""
    return (
        {"aggregation_period": "daily", "user_id": "", "date": {"$gte": starting_date.isoformat()}},
        {"$set": {"completed": False}, "$inc": {"version": 1}},
    )


def reopen_metrics_days_from(collection: Collection, starting_date: date) -> None:
    """Reopen every day's aggregate metrics row from the given date on, as a write reopens a day, so the next refresh
    rebuilds them.

    Args:
        collection (Collection): The aggregate metrics collection.
        starting_date (date): The first day to reopen.
    """
    collection.update_many(*_reopen_metrics_days_from(starting_date))


async def areopen_metrics_days_from(collection: "AsyncMongoCollectionType", starting_date: date) -> None:
    """Reopen every day's aggregate metrics row from the given date on, as a write reopens a day, so the next refresh
    rebuilds them.

    Args:
        collection (AsyncMongoCollectionType): The aggregate metrics collection.
        starting_date (date): The first day to reopen.
    """
    await collection.update_many(*_reopen_metrics_days_from(starting_date))


def reopen_metrics_month(collection: Collection, month_start: date) -> None:
    """Reopen a month's aggregate metrics row, so the next refresh rebuilds the month.

    Args:
        collection (Collection): The aggregate metrics collection.
        month_start (date): The first day of the month.
    """
    collection.update_one(*_reopen_metrics_row(month_start, "monthly"), upsert=True)


async def areopen_metrics_month(collection: "AsyncMongoCollectionType", month_start: date) -> None:
    """Reopen a month's aggregate metrics row, so the next refresh rebuilds the month.

    Args:
        collection (AsyncMongoCollectionType): The aggregate metrics collection.
        month_start (date): The first day of the month.
    """
    await collection.update_one(*_reopen_metrics_row(month_start, "monthly"), upsert=True)


def build_metrics_fingerprint_pipeline(start_timestamp: int) -> List[Dict[str, Any]]:
    """Build the pipeline that counts the sessions or runs created from the given time on, and adds up and finds the
    latest of their update times."""
    return [
        {"$match": {"created_at": {"$gte": start_timestamp}}},
        {
            "$group": {
                "_id": None,
                "count": {"$sum": 1},
                "total_updated_at": {"$sum": "$updated_at"},
                "latest_updated_at": {"$max": "$updated_at"},
            }
        },
    ]


def build_metrics_days_pipeline() -> List[Dict[str, Any]]:
    """Build the pipeline that finds every day a session or run was created on, as days since 1970-01-01. Read from
    the created_at index alone."""
    return [
        {"$match": {"created_at": {"$ne": None}}},
        {"$project": {"_id": 0, "created_at": 1}},
        {"$group": {"_id": {"$floor": {"$divide": ["$created_at", 86400]}}}},
    ]


def build_metrics_rows_filter(
    starting_date: date,
    ending_date: date,
    user_id: str,
    month_starts: Sequence[date] = (),
) -> Optional[Dict[str, Any]]:
    """Build the filter of one user's metrics rows of each day in the given date range.

    Args:
        starting_date (date): The first day to read.
        ending_date (date): The last day to read.
        user_id (str): The user whose rows are read. "" for the everyone rows of the aggregate metrics collection, or the
            rows with no user of the component metrics collection.
        month_starts (Sequence[date]): The first day of every month inside the date range to read the month row of
            instead of its days.

    Returns:
        Optional[Dict[str, Any]]: The filter. None when there is no day to read.
    """
    # Days that follow one another are looked up as one range
    filters: List[Dict[str, Any]] = [
        {"aggregation_period": "daily", "date": {"$gte": first_day.isoformat(), "$lte": last_day.isoformat()}}
        for first_day, last_day in metrics_day_ranges(metrics_days_to_read(starting_date, ending_date, month_starts))
    ]
    if month_starts:
        filters.append(
            {
                "aggregation_period": "monthly",
                "date": {"$in": [month_start.isoformat() for month_start in month_starts]},
            }
        )
    if not filters:
        return None
    return {"user_id": user_id, "$or": filters}


def build_metrics_rows_projection(fields: Sequence[str]) -> Dict[str, int]:
    """Build the projection of a stored metrics row with only what totalling the given fields reads."""
    projection = {"_id": 0, "aggregation_period": 1, "date": 1, "updated_at": 1, **{field: 1 for field in fields}}
    if any(field in [*METRICS_TOKEN_DETAILS_FIELDS, "audio_total_tokens", *METRICS_COST_FIELDS] for field in fields):
        projection["token_details"] = 1
    # The aggregate metrics collection keeps the sessions of each type, and the component metrics collection the runs of
    # each component, with the run that started them
    if "sessions_count" in fields:
        projection.update({f"{component_type}_sessions_count": 1 for component_type in METRICS_COMPONENT_TYPES})
    if "root_runs_count" in fields:
        projection.update({"runs_count": 1, "parent_component_id": 1})
    return projection


def build_metrics_by_owner_projection() -> Dict[str, int]:
    """Build the projection of a stored component metrics row with only what get_metrics reads of it."""
    return {
        "_id": 0,
        "date": 1,
        "user_id": 1,
        "component_type": 1,
        "sessions_count": 1,
        "runs_count": 1,
        **{
            field: 1
            for field in METRICS_TOKEN_FIELDS
            if field not in [*METRICS_TOKEN_DETAILS_FIELDS, "audio_total_tokens"]
        },
        "token_details": 1,
        "model_metrics": 1,
        "created_at": 1,
        "updated_at": 1,
    }
