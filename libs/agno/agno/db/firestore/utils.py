"""Utility functions for the Firestore database class."""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.db.firestore.schemas import get_collection_indexes
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.utils import get_sort_value
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from google.cloud.firestore import Client  # type: ignore[import-untyped]
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
        log_warning(f"Error processing indexes for {collection_type} collection: {e}")


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
                    log_error(f"Error creating composite index: {e}")

    except Exception as e:
        log_warning(f"Error initializing Firestore Admin client for composite indexes: {e}")
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
    """Apply pagination to Firestore query."""
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
        log_warning(f"Error sorting Firestore records: {e}")
        return records


def apply_pagination_to_records(
    records: List[Dict[str, Any]], limit: Optional[int] = None, page: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Apply pagination to in-memory records (for cases where Firestore query pagination isn't possible)."""
    if limit is None:
        return records

    if page is not None and page > 0:
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        return records[start_idx:end_idx]
    else:
        return records[:limit]


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
        sessions = sessions_data.get(session_type, []) or []
        metrics[sessions_count_key] = len(sessions)

        for session in sessions:
            if session.get("user_id"):
                all_user_ids.add(session["user_id"])
            runs = session.get("runs", []) or []

            if runs:
                if isinstance(runs, str):
                    runs = json.loads(runs)

                metrics[runs_count_key] += len(runs)

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
        model_id, model_provider = model.rsplit(":", 1)
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

    for i, record in enumerate(metrics_records):
        record["date"] = record["date"].isoformat() if isinstance(record["date"], date) else record["date"]
        try:
            # Create a unique document ID based on date and aggregation period
            doc_id = f"{record['date']}_{record['aggregation_period']}"
            doc_ref = collection_ref.document(doc_id)
            batch.set(doc_ref, record, merge=True)
            results.append(record)

            # Firestore batch limit is 500 operations
            if (i + 1) % 500 == 0:
                batch.commit()
                batch = collection_ref._client.batch()

        except Exception as e:
            log_error(f"Error preparing metrics record for batch: {e}")
            continue

    # Commit remaining operations
    if len(metrics_records) % 500 != 0:
        try:
            batch.commit()
        except Exception as e:
            log_error(f"Error committing metrics batch: {e}")

    return results


# -- Cultural Knowledge util methods --


def serialize_cultural_knowledge_for_db(cultural_knowledge: CulturalKnowledge) -> Dict[str, Any]:
    """Serialize a CulturalKnowledge object for database storage.

    Converts the model's separate content, categories, and notes fields
    into a single dict for the database content field.

    Args:
        cultural_knowledge (CulturalKnowledge): The cultural knowledge object to serialize.

    Returns:
        Dict[str, Any]: A dictionary with content, categories, and notes.
    """
    content_dict: Dict[str, Any] = {}
    if cultural_knowledge.content is not None:
        content_dict["content"] = cultural_knowledge.content
    if cultural_knowledge.categories is not None:
        content_dict["categories"] = cultural_knowledge.categories
    if cultural_knowledge.notes is not None:
        content_dict["notes"] = cultural_knowledge.notes

    return content_dict if content_dict else {}


def deserialize_cultural_knowledge_from_db(db_row: Dict[str, Any]) -> CulturalKnowledge:
    """Deserialize a database row to a CulturalKnowledge object.

    The database stores content as a dict containing content, categories, and notes.
    This method extracts those fields and converts them back to the model format.

    Args:
        db_row (Dict[str, Any]): The database row as a dictionary.

    Returns:
        CulturalKnowledge: The cultural knowledge object.
    """
    # Extract content, categories, and notes from the content field
    content_json = db_row.get("content", {}) or {}

    return CulturalKnowledge.from_dict(
        {
            "id": db_row.get("id"),
            "name": db_row.get("name"),
            "summary": db_row.get("summary"),
            "content": content_json.get("content"),
            "categories": content_json.get("categories"),
            "notes": content_json.get("notes"),
            "metadata": db_row.get("metadata"),
            "input": db_row.get("input"),
            "created_at": db_row.get("created_at"),
            "updated_at": db_row.get("updated_at"),
            "agent_id": db_row.get("agent_id"),
            "team_id": db_row.get("team_id"),
        }
    )
