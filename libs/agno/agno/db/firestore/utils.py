"""Utility functions for the Firestore database class."""

import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from agno.db.firestore.schemas import get_collection_indexes
from agno.db.utils import get_sort_value, metric_record_day
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from google.cloud.firestore import Client, Increment  # type: ignore[import-untyped]
    from google.cloud.firestore_admin_v1 import FirestoreAdminClient, Index  # type: ignore[import-untyped]
except ImportError:
    raise ImportError(
        "`google-cloud-firestore` not installed. Please install it using `pip install google-cloud-firestore`"
    )


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


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> List[dict]:
    """Calculate metrics for the given single date, bucketed per ``user_id``.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data to calculate metrics for.

    Returns:
        The list of per-user metrics records. Sessions without a ``user_id`` bucket under "".
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
        # Firestore document ids reject ``/``, ``.``, ``..`` and ``__..__``, so hash the owner
        # segment: an IdP subject like ``google-oauth2/abc`` fails the write, which the upsert swallows.
        user_segment = "shared" if user_id == "" else hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        metric_id = f"{date_to_process.isoformat()}_{user_segment}_daily"

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


def bulk_upsert_metrics(collection_ref, metrics_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bulk upsert metrics into the database.

    Args:
        collection_ref: The Firestore collection reference to upsert the metrics into.
        metrics_records (List[Dict[str, Any]]): The list of metrics records to upsert.

    Returns:
        The list of upserted metrics records.
    """
    if not metrics_records:
        return []

    results = []
    batch = collection_ref._client.batch()

    batch_count = 0

    for record in metrics_records:
        record["date"] = record["date"].isoformat() if isinstance(record["date"], date) else record["date"]
        try:
            # ``record["id"]`` is deterministic per (date, user_id), so re-runs update the same doc.
            doc_id = record["id"]
            doc_ref = collection_ref.document(doc_id)
            batch.set(doc_ref, record, merge=True)
            results.append(record)
            batch_count += 1

        except Exception as e:
            log_error(f"Error preparing metrics record for batch: {str(e)}")
            continue

        # Firestore batch limit is 500 operations
        if batch_count % 500 == 0:
            batch.commit()
            batch = collection_ref._client.batch()

    # Commit remaining operations
    if batch_count % 500 != 0:
        batch.commit()

    return results


# -- OS metrics util methods --

# The document of the OS metrics totals collection held by the one rebuild running
OS_METRICS_LOCK_ID = "os_metrics_lock"

# How long a rebuild holds the lock document at most, so a process stopped mid-rebuild never holds it for good
OS_METRICS_LOCK_SECONDS = 60

# How long a rebuild that waits for the lock sleeps before it tries again
OS_METRICS_LOCK_RETRY_SECONDS = 0.1

# Firestore takes 30 values at most in one `in` filter
OS_METRICS_IN_LIST_LIMIT = 30

# Rows a rebuild reads at a time, so a day or a month of many rows is never held or decoded in one step
OS_METRICS_BATCH_SIZE = 1000


def os_metrics_record_id(record: Dict[str, Any]) -> str:
    """The id of the document an OS metrics row is stored under, one per period, day, owner, component and parent."""
    # Firestore document ids reject ``/``, ``.``, ``..`` and ``__..__``, so hash the owner, component and parent
    key = json.dumps(
        [record["user_id"], record["component_type"], record["component_id"], record["parent_component_id"]]
    )
    key_segment = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{record['date'].isoformat()}_{key_segment}_{record['aggregation_period']}"


def os_metrics_totals_record_id(aggregation_period: str, row_date: date) -> str:
    """The id of the document an OS metrics totals row is stored under, one per period and day."""
    return f"{row_date.isoformat()}_{aggregation_period}"


def deserialize_os_metrics_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stored OS metrics row with its day, stored as an ISO string, as a date."""
    return {**record, "date": metric_record_day(record)}


def bulk_upsert_os_metrics(
    collection_ref,
    os_metrics_records: List[Dict[str, Any]],
    stale_doc_ids: Sequence[str] = (),
    totals_collection_ref=None,
    totals_row: Optional[Dict[str, Any]] = None,
    totals_row_stored: bool = False,
) -> None:
    """Bulk upsert OS metrics into the database, delete the stale ones and write the totals row last.

    A new totals row starts at version 1, and every write of a stored one moves its version by one in the same
    write, so two writers never give it the same version.

    Args:
        collection_ref: The OS metrics collection.
        os_metrics_records (List[Dict[str, Any]]): The OS metrics records to upsert.
        stale_doc_ids (Sequence[str]): The ids of the OS metrics records to delete.
        totals_collection_ref: The OS metrics totals collection.
        totals_row (Optional[Dict[str, Any]]): The totals row, from build_os_metrics_totals_row.
        totals_row_stored (bool): Whether the totals row is already stored.
    """
    batch = collection_ref._client.batch()

    batch_count = 0

    # Firestore commits 500 writes at most at once, so a stored totals row whose rows need more commits moves its
    # version in the first one: a later commit that fails never leaves rows changed under the version read before
    if (
        totals_collection_ref is not None
        and totals_row is not None
        and totals_row_stored
        and len(stale_doc_ids) + len(os_metrics_records) >= 500
    ):
        doc_ref = totals_collection_ref.document(
            os_metrics_totals_record_id(totals_row["aggregation_period"], totals_row["date"])
        )
        batch.update(doc_ref, {"version": Increment(1)})
        batch_count += 1

    for doc_id in stale_doc_ids:
        batch.delete(collection_ref.document(doc_id))
        batch_count += 1

        # Firestore batch limit is 500 operations
        if batch_count % 500 == 0:
            batch.commit()
            batch = collection_ref._client.batch()

    for record in os_metrics_records:
        doc_ref = collection_ref.document(os_metrics_record_id(record))
        batch.set(doc_ref, {**record, "date": record["date"].isoformat()})
        batch_count += 1

        # Firestore batch limit is 500 operations
        if batch_count % 500 == 0:
            batch.commit()
            batch = collection_ref._client.batch()

    if totals_collection_ref is not None and totals_row is not None:
        doc_ref = totals_collection_ref.document(
            os_metrics_totals_record_id(totals_row["aggregation_period"], totals_row["date"])
        )
        batch.set(
            doc_ref,
            {**totals_row, "date": totals_row["date"].isoformat(), "version": Increment(1)},
            merge=list(totals_row) + ["version"],
        )
        batch_count += 1

        # Firestore batch limit is 500 operations
        if batch_count % 500 == 0:
            batch.commit()
            batch = collection_ref._client.batch()

    # Commit remaining operations
    if batch_count % 500 != 0:
        batch.commit()
