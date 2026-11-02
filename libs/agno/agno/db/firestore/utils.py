"""Utility functions for the Firestore database class."""

import hashlib
import json
from datetime import date
from typing import Any, Dict, List, Optional

from agno.db.firestore.schemas import get_collection_indexes
from agno.db.utils import build_user_metrics_row, get_sort_value, list_metrics_models, metric_record_day
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from google.api_core.exceptions import AlreadyExists, NotFound  # type: ignore[import-untyped]
    from google.cloud.firestore import Client, FieldFilter, Increment  # type: ignore[import-untyped]
    from google.cloud.firestore_admin_v1 import FirestoreAdminClient, Index  # type: ignore[import-untyped]
except ImportError:
    raise ImportError(
        "`google-cloud-firestore` not installed. Please install it using `pip install google-cloud-firestore`"
    )

# Firestore takes 30 values at most in one `in` filter
METRICS_IN_LIST_LIMIT = 30


# -- DB util methods --


def create_collection_indexes(client: Client, collection_name: str, collection_type: str) -> None:
    """Create all required indexes for a collection including composite indexes.

    This function automatically creates both single-field and composite indexes.
    """
    try:
        indexes = get_collection_indexes(collection_type)
        composite_indexes = []

        # Get all composite indexes
        for idx in indexes:
            if isinstance(idx["key"], list):
                composite_indexes.append(idx)

        # Create composite indexes programmatically
        if composite_indexes:
            _create_composite_indexes(client, collection_name, composite_indexes)
            log_debug(f"Collection '{collection_name}' initialized")

    except Exception as e:
        log_warning(f"Error processing indexes for {collection_type} collection: {str(e)}")


def _create_composite_indexes(client: Client, collection_name: str, composite_indexes: List[Dict[str, Any]]) -> None:
    """Create composite indexes using Firestore Admin API."""
    try:
        project_id = client.project
        if not project_id:
            log_warning("Cannot create composite indexes: project_id not available from client")
            return

        admin_client = FirestoreAdminClient()

        created_count = 0
        for idx_spec in composite_indexes:
            try:
                # Build index fields
                fields = []
                for field_name, direction in idx_spec["key"]:
                    field_direction = (
                        Index.IndexField.Order.ASCENDING
                        if direction == "ASCENDING"
                        else Index.IndexField.Order.DESCENDING
                    )
                    fields.append(Index.IndexField(field_path=field_name, order=field_direction))

                # Create index definition
                index = Index(
                    query_scope=Index.QueryScope.COLLECTION
                    if not idx_spec.get("collection_group", True)
                    else Index.QueryScope.COLLECTION_GROUP,
                    fields=fields,
                )

                # Note: Firestore doesn't support unique constraints on composite indexes
                if idx_spec.get("unique", False):
                    log_debug(
                        f"Unique constraint on composite index ignored for {collection_name} - not supported by Firestore"
                    )

                # Create the index
                parent_path = f"projects/{project_id}/databases/(default)/collectionGroups/{collection_name}"
                admin_client.create_index(parent=parent_path, index=index)
                created_count += 1

            except Exception as e:
                if "already exists" in str(e).lower():
                    continue
                else:
                    log_error(f"Error creating composite index: {str(e)}")

    except Exception as e:
        log_warning(f"Error initializing Firestore Admin client for composite indexes: {str(e)}")
        log_info("Fallback: You can create composite indexes manually via Firebase Console or gcloud CLI")


def apply_sorting(query, sort_by: Optional[str] = None, sort_order: Optional[str] = None):
    """Apply sorting to Firestore query."""
    if sort_by is None:
        return query

    from google.cloud.firestore import Query

    if sort_order == "asc":
        return query.order_by(sort_by, direction=Query.ASCENDING)
    else:
        return query.order_by(sort_by, direction=Query.DESCENDING)


def apply_pagination(query, limit: Optional[int] = None, page: Optional[int] = None):
    """Apply pagination to Firestore query.

    Raises ``ValueError`` when ``page`` is provided without ``limit`` — see
    ``agno.db.utils.validate_pagination``.
    """
    from agno.db.utils import validate_pagination

    validate_pagination(limit, page)
    if limit is not None:
        query = query.limit(limit)
        if page is not None and page > 1:
            # Note: Firestore pagination typically uses cursor-based pagination
            # For offset-based pagination, we'd need to skip documents
            offset = (page - 1) * limit
            query = query.offset(offset)
    return query


def apply_sorting_to_records(
    records: List[Dict[str, Any]], sort_by: Optional[str] = None, sort_order: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Apply sorting to in-memory records (for cases where Firestore query sorting isn't possible).

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
        log_warning(f"Error sorting Firestore records: {str(e)}")
        return records


def apply_pagination_to_records(
    records: List[Dict[str, Any]], limit: Optional[int] = None, page: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Apply pagination to in-memory records (for cases where Firestore query pagination isn't possible).

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
    else:
        return records[:limit]


# -- Metrics util methods --


def component_metrics_record_id(record: Dict[str, Any]) -> str:
    """The id of the document a row of the component metrics collection is stored under, one per day, owner,
    component, parent and root."""
    # Firestore document ids reject ``/``, ``.``, ``..`` and ``__..__``, so hash the owner, component, parent and root
    key = json.dumps(
        [
            record["user_id"],
            record["component_type"],
            record["component_id"],
            record["parent_component_id"],
            record["root_component_id"],
        ]
    )
    key_segment = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{record['date'].isoformat()}_{key_segment}_{record['aggregation_period']}"


def user_metrics_record_id(aggregation_period: str, row_date: date, user_id: str) -> str:
    """The id of the document a row of the user metrics collection is stored under, one per period, day and user."""
    user_segment = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return f"{row_date.isoformat()}_{user_segment}_{aggregation_period}"


def serialize_metrics_row(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a metrics row with its day as an ISO string and its models as the list agno_metrics keeps, the way
    Firestore stores it, so no model provider becomes a field name."""
    document = {**record, "date": record["date"].isoformat()}
    if "model_metrics" in document:
        document["model_metrics"] = list_metrics_models(document["model_metrics"])
    return document


def deserialize_metrics_row(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stored metrics row with its day, stored as an ISO string, as a date."""
    row = {**record, "date": metric_record_day(record)}
    if "model_metrics" in row:
        model_metrics: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for model in row["model_metrics"] or []:
            model_totals: Dict[str, Any] = {"count": model["count"]}
            if model.get("cost") is not None:
                model_totals["cost"] = model["cost"]
            model_metrics.setdefault(model["model_provider"], {})[model["model_id"]] = model_totals
        row["model_metrics"] = model_metrics
    return row


def deserialize_metrics_refresh_row(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return the stored document of the metrics refreshes collection as its row, the columns it keeps no field for
    None."""
    columns = ["id", "locked_by", "locked_at", "started_at", "finished_at", "status", "error", "fingerprint"]
    return {column: record.get(column) for column in columns}


def _reopen_metrics_row(user_metrics_collection_ref, row_date: date, aggregation_period: str) -> None:
    """Reopen a day's or a month's everyone row of the user metrics collection, creating an empty open row when it
    has none."""
    doc_ref = user_metrics_collection_ref.document(user_metrics_record_id(aggregation_period, row_date, ""))
    try:
        # Moved in the write, so two writers reopening the same row never give it the same version
        doc_ref.update({"completed": False, "version": Increment(1)})
    except NotFound:
        try:
            doc_ref.create(
                serialize_metrics_row(
                    {**build_user_metrics_row([], aggregation_period, row_date, completed=False), "version": 1}
                )
            )
        except AlreadyExists:
            doc_ref.update({"completed": False, "version": Increment(1)})


def reopen_metrics_day(user_metrics_collection_ref, day: date) -> None:
    """Reopen a day's everyone row of the user metrics collection, so the next refresh rebuilds the day.

    Args:
        user_metrics_collection_ref: The user metrics collection.
        day (date): The day, from metrics_day_to_reopen.
    """
    _reopen_metrics_row(user_metrics_collection_ref, day, "daily")


def reopen_metrics_month(user_metrics_collection_ref, month_start: date) -> None:
    """Reopen a month's everyone row of the user metrics collection, so the next refresh rebuilds the month.

    Args:
        user_metrics_collection_ref: The user metrics collection.
        month_start (date): The first day of the month.
    """
    _reopen_metrics_row(user_metrics_collection_ref, month_start, "monthly")


def reopen_metrics_days_from(client: Client, user_metrics_collection_ref, starting_date: date) -> None:
    """Reopen every day's everyone row of the user metrics collection from the given date on, as a write reopens a
    day, so the next calculation rebuilds them.

    Args:
        client (Client): The Firestore client.
        user_metrics_collection_ref: The user metrics collection.
        starting_date (date): The first day to reopen.
    """
    docs = (
        user_metrics_collection_ref.where(filter=FieldFilter("aggregation_period", "==", "daily"))
        .where(filter=FieldFilter("user_id", "==", ""))
        .where(filter=FieldFilter("date", ">=", starting_date.isoformat()))
        .select(["date"])
        .stream()
    )
    batch = client.batch()
    batch_count = 0
    for doc in docs:
        batch.update(doc.reference, {"completed": False, "version": Increment(1)})
        batch_count += 1
        # Firestore batch has a limit of 500 operations
        if batch_count >= 500:
            batch.commit()
            batch = client.batch()
            batch_count = 0
    # Commit remaining operations
    if batch_count > 0:
        batch.commit()
