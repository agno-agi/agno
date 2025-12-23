import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agno.db.schemas.culture import CulturalKnowledge
from agno.db.sqlite.schemas import get_table_schema_definition
from agno.utils.log import log_debug, log_error, log_warning

try:
    from sqlalchemy import Table, func
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.engine import Engine
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


def is_table_available(session: Session, table_name: str, db_schema: Optional[str] = None) -> bool:
    """
    Check if a table with the given name exists.
    Note: db_schema parameter is ignored in SQLite but kept for API compatibility.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        # SQLite uses sqlite_master instead of information_schema
        exists_query = text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table")
        exists = session.execute(exists_query, {"table": table_name}).scalar() is not None
        if not exists:
            log_debug(f"Table {table_name} {'exists' if exists else 'does not exist'}")
        return exists
    except Exception as e:
        log_error(f"Error checking if table exists: {e}")
        return False


async def ais_table_available(session: AsyncSession, table_name: str, db_schema: Optional[str] = None) -> bool:
    """
    Check if a table with the given name exists.
    Note: db_schema parameter is ignored in SQLite but kept for API compatibility.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        exists_query = text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table")
        exists = (await session.execute(exists_query, {"table": table_name})).scalar() is not None
        if not exists:
            log_debug(f"Table {table_name} {'exists' if exists else 'does not exist'}")
        return exists
    except Exception as e:
        log_error(f"Error checking if table exists: {e}")
        return False


def is_valid_table(db_engine: Engine, table_name: str, table_type: str) -> bool:
    """
    Check if the existing table has the expected column names.

    Args:
        db_engine (Engine): Database engine
        table_name (str): Name of the table to validate
        table_type (str): Type of table to get expected schema

    Returns:
        bool: True if table has all expected columns, False otherwise
    """
    try:
        expected_table_schema = get_table_schema_definition(table_type)
        expected_columns = {col_name for col_name in expected_table_schema.keys() if not col_name.startswith("_")}

        # Get existing columns (no schema parameter for SQLite)
        inspector = inspect(db_engine)
        existing_columns_info = inspector.get_columns(table_name)  # No schema parameter
        existing_columns = set(col["name"] for col in existing_columns_info)

        # Check if all expected columns exist
        missing_columns = expected_columns - existing_columns
        if missing_columns:
            log_warning(f"Missing columns {missing_columns} in table {table_name}")
            return False

        return True
    except Exception as e:
        log_error(f"Error validating table schema for {table_name}: {e}")
        return False


async def ais_valid_table(db_engine: AsyncEngine, table_name: str, table_type: str) -> bool:
    """
    Check if the existing table has the expected column names.

    Args:
        db_engine (Engine): Database engine
        table_name (str): Name of the table to validate
        table_type (str): Type of table to get expected schema

    Returns:
        bool: True if table has all expected columns, False otherwise
    """
    try:
        expected_table_schema = get_table_schema_definition(table_type)
        expected_columns = {col_name for col_name in expected_table_schema.keys() if not col_name.startswith("_")}

        # Get existing columns from the async engine
        async with db_engine.connect() as conn:
            existing_columns = await conn.run_sync(_get_table_columns, table_name)

        missing_columns = expected_columns - existing_columns
        if missing_columns:
            log_warning(f"Missing columns {missing_columns} in table {table_name}")
            return False

        return True

    except Exception as e:
        log_error(f"Error validating table schema for {table_name}: {e}")
        return False


def _get_table_columns(conn, table_name: str) -> set[str]:
    """Helper function to get table columns using sync inspector."""
    inspector = inspect(conn)
    columns_info = inspector.get_columns(table_name)
    return {col["name"] for col in columns_info}


# -- Metrics util methods --


def bulk_upsert_metrics(session: Session, table: Table, metrics_records: list[dict]) -> list[dict]:
    """Bulk upsert metrics into the database.

    Args:
        table (Table): The table to upsert into.
        metrics_records (list[dict]): The metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    results = []
    stmt = sqlite.insert(table)

    # Columns to update in case of conflict
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in ["id", "date", "created_at", "aggregation_period"]
    }

    stmt = stmt.on_conflict_do_update(index_elements=["date", "aggregation_period"], set_=update_columns).returning(  # type: ignore
        table
    )
    result = session.execute(stmt, metrics_records)
    results = [row._mapping for row in result.fetchall()]
    session.commit()

    return results  # type: ignore


async def abulk_upsert_metrics(session: AsyncSession, table: Table, metrics_records: list[dict]) -> list[dict]:
    """Bulk upsert metrics into the database.

    Args:
        table (Table): The table to upsert into.
        metrics_records (list[dict]): The metrics records to upsert.

    Returns:
        list[dict]: The upserted metrics records.
    """
    if not metrics_records:
        return []

    results = []
    stmt = sqlite.insert(table)

    # Columns to update in case of conflict
    update_columns = {
        col.name: stmt.excluded[col.name]
        for col in table.columns
        if col.name not in ["id", "date", "created_at", "aggregation_period"]
    }

    stmt = stmt.on_conflict_do_update(index_elements=["date", "aggregation_period"], set_=update_columns).returning(  # type: ignore
        table
    )
    result = await session.execute(stmt, metrics_records)
    results = [dict(row._mapping) for row in result.fetchall()]
    await session.commit()

    return results  # type: ignore


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

            # Parse runs from JSON string
            if runs := session.get("runs", []):
                runs = json.loads(runs) if isinstance(runs, str) else runs
                metrics[runs_count_key] += len(runs)
                for run in runs:
                    if model_id := run.get("model"):
                        model_provider = run.get("model_provider", "")
                        model_counts[f"{model_id}:{model_provider}"] = (
                            model_counts.get(f"{model_id}:{model_provider}", 0) + 1
                        )

            # Parse session_data from JSON string
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
def serialize_cultural_knowledge_for_db(cultural_knowledge: CulturalKnowledge) -> str:
    """Serialize a CulturalKnowledge object for database storage.

    Converts the model's separate content, categories, and notes fields
    into a single JSON string for the database content column.
    SQLite requires JSON to be stored as strings.

    Args:
        cultural_knowledge (CulturalKnowledge): The cultural knowledge object to serialize.

    Returns:
        str: A JSON string containing content, categories, and notes.
    """
    content_dict: Dict[str, Any] = {}
    if cultural_knowledge.content is not None:
        content_dict["content"] = cultural_knowledge.content
    if cultural_knowledge.categories is not None:
        content_dict["categories"] = cultural_knowledge.categories
    if cultural_knowledge.notes is not None:
        content_dict["notes"] = cultural_knowledge.notes

    return json.dumps(content_dict) if content_dict else None  # type: ignore


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

    if isinstance(content_json, str):
        content_json = json.loads(content_json) if content_json else {}

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
