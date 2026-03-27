"""Utility functions for the SingleStore database class."""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import Engine

from agno.db.schemas.culture import CulturalKnowledge
from agno.db.singlestore.schemas import get_table_schema_definition
from agno.utils.log import log_debug, log_error, log_warning

try:
    from sqlalchemy import Table, func
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


# -- DB util methods --
def apply_sorting(stmt, table: Table, sort_by: Optional[str] = None, sort_order: Optional[str] = None):
    """Apply sorting to the given SQLAlchemy statement.

    Args:
        stmt: The SQLAlchemy statement to modify
        table: The table being queried
        sort_by: The field to sort by
        sort_order: The sort order ('asc' or 'desc')

    Returns:
        The modified statement with sorting applied

    Note:
        For 'updated_at' sorting, uses COALESCE(updated_at, created_at) to fall back
        to created_at when updated_at is NULL. This ensures pre-2.0 records (which may
        have NULL updated_at) are sorted correctly by their creation time.
    """
    if sort_by is None:
        return stmt

    if not hasattr(table.c, sort_by):
        log_debug(f"Invalid sort field: '{sort_by}'. Will not apply any sorting.")
        return stmt

    # For updated_at, use COALESCE to fall back to created_at if updated_at is NULL
    # This handles pre-2.0 records that may have NULL updated_at values
    if sort_by == "updated_at" and hasattr(table.c, "created_at"):
        sort_column = func.coalesce(table.c.updated_at, table.c.created_at)
    else:
        sort_column = getattr(table.c, sort_by)

    if sort_order and sort_order == "asc":
        return stmt.order_by(sort_column.asc())
    else:
        return stmt.order_by(sort_column.desc())


def create_schema(session: Session, db_schema: str) -> None:
    """Create the database schema if it doesn't exist.

    Args:
        session: The SQLAlchemy session to use
        db_schema (str): The definition of the database schema to create

    Raises:
        Exception: If the schema creation fails.
    """
    try:
        log_debug(f"Creating schema if not exists: {db_schema}")
        session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {db_schema};"))
    except Exception as e:
        log_warning(f"Could not create schema {db_schema}: {e}")


def is_table_available(session: Session, table_name: str, db_schema: Optional[str]) -> bool:
    """
    Check if a table with the given name exists in the given schema.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        if db_schema is not None:
            exists_query = text(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table"
            )
            exists = session.execute(exists_query, {"schema": db_schema, "table": table_name}).scalar() is not None
            table_ref = f"{db_schema}.{table_name}"
        else:
            # Check in current database/schema
            exists_query = text(
                "SELECT 1 FROM information_schema.tables WHERE table_name = :table AND table_schema = DATABASE()"
            )
            exists = session.execute(exists_query, {"table": table_name}).scalar() is not None
            table_ref = table_name

        if not exists:
            log_debug(f"Table {table_ref} {'exists' if exists else 'does not exist'}")

        return exists

    except Exception as e:
        log_error(f"Error checking if table exists: {e}")
        return False


def is_valid_table(db_engine: Engine, table_name: str, table_type: str, db_schema: Optional[str]) -> bool:
    """
    Check if the existing table has the expected column names.

    Args:
        table_name (str): Name of the table to validate
        schema (str): Database schema name

    Returns:
        bool: True if table has all expected columns, False otherwise
    """
    try:
        expected_table_schema = get_table_schema_definition(table_type)
        expected_columns = {col_name for col_name in expected_table_schema.keys() if not col_name.startswith("_")}
        table_ref = f"{db_schema}.{table_name}" if db_schema else table_name

        inspector = inspect(db_engine)
        try:
            import warnings

            # Suppressing SQLAlchemy warnings about unrecognized SingleStore JSON types, which are expected
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Did not recognize type 'JSON'", category=Warning)
                existing_columns_info = inspector.get_columns(table_name, schema=db_schema)

            existing_columns = set(col["name"] for col in existing_columns_info)

        except Exception:
            # If column inspection fails (e.g., unrecognized JSON type), assume table is valid
            return True

        # Check if all expected columns exist
        missing_columns = expected_columns - existing_columns
        if missing_columns:
            log_warning(f"Missing columns {missing_columns} in table {table_ref}")
            return False

        return True

    except Exception as e:
        table_ref = f"{db_schema}.{table_name}" if db_schema else table_name
        log_error(f"Error validating table schema for {table_ref}: {e}")
        return False


# -- Metrics util methods --
def bulk_upsert_metrics(session: Session, table: Table, metrics_records: list[dict]) -> list[dict]:
    """Bulk upsert metrics into the database with proper duplicate handling.

    Args:
        table (Table): The table to upsert into.
        metrics_records (list[dict]): The metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    results = []

    for record in metrics_records:
        date_val = record.get("date")
        period_val = record.get("aggregation_period")

        # Check if record already exists based on date + aggregation_period
        existing_record = (
            session.query(table).filter(table.c.date == date_val, table.c.aggregation_period == period_val).first()
        )

        if existing_record:
            # Update existing record
            update_data = {
                k: v for k, v in record.items() if k not in ["id", "date", "aggregation_period", "created_at"]
            }
            update_data["updated_at"] = record.get("updated_at")

            session.query(table).filter(table.c.date == date_val, table.c.aggregation_period == period_val).update(
                update_data
            )

            # Get the updated record for return
            updated_record = (
                session.query(table).filter(table.c.date == date_val, table.c.aggregation_period == period_val).first()
            )
            if updated_record:
                results.append(dict(updated_record._mapping))
        else:
            # Insert new record
            stmt = table.insert().values(**record)
            session.execute(stmt)
            results.append(record)

    session.commit()
    return results


def calculate_date_metrics(date_to_process: date, sessions_data: dict) -> dict:
    """Calculate metrics for the given single date.

    Args:
        date_to_process (date): The date to calculate metrics for.
        sessions_data (dict): The sessions data to calculate metrics for.

    Returns:
        dict: The calculated metrics.
    """
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
            metrics[runs_count_key] += len(session.get("runs", []))
            if runs := session.get("runs", []):
                for run in runs:
                    if model_id := run.get("model"):
                        model_provider = run.get("model_provider", "")
                        model_counts[f"{model_id}:{model_provider}"] = (
                            model_counts.get(f"{model_id}:{model_provider}", 0) + 1
                        )

            session_metrics = session.get("session_data", {}).get("session_metrics", {})
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
    """Return all session data for the given dates, for all session types.

    Args:
        dates_to_process (list[date]): The dates to fetch session data for.

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
        starting_date (date): The starting date to calculate metrics for.

    Returns:
        list[date]: The list of dates to calculate metrics for.
    """
    today = datetime.now(timezone.utc).date()
    days_diff = (today - starting_date).days + 1
    if days_diff <= 0:
        return []
    return [starting_date + timedelta(days=x) for x in range(days_diff)]


# -- Cultural Knowledge util methods --
def serialize_cultural_knowledge_for_db(cultural_knowledge: CulturalKnowledge) -> Dict[str, Any]:
    """Serialize a CulturalKnowledge object for database storage.

    Converts the model's separate content, categories, and notes fields
    into a single JSON dict for the database content column.

    Args:
        cultural_knowledge (CulturalKnowledge): The cultural knowledge object to serialize.

    Returns:
        Dict[str, Any]: A dictionary with the content field as JSON containing content, categories, and notes.
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

    The database stores content as a JSON dict containing content, categories, and notes.
    This method extracts those fields and converts them back to the model format.

    Args:
        db_row (Dict[str, Any]): The database row as a dictionary.

    Returns:
        CulturalKnowledge: The cultural knowledge object.
    """
    # Extract content, categories, and notes from the JSON content field
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
