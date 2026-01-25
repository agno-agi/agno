"""Logic shared across different database implementations"""

import json
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, Optional, Union
from uuid import UUID

from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from agno.db.base import BaseDb


def get_sort_value(record: Dict[str, Any], sort_by: str) -> Any:
    """Get the sort value for a record, with fallback to created_at for updated_at.

    When sorting by 'updated_at', this function falls back to 'created_at' if
    'updated_at' is None. This ensures pre-2.0 records (which may have NULL
    updated_at values) are sorted correctly by their creation time.

    Args:
        record: The record dictionary to get the sort value from
        sort_by: The field to sort by

    Returns:
        The value to use for sorting
    """
    value = record.get(sort_by)
    # For updated_at, fall back to created_at if updated_at is None
    if value is None and sort_by == "updated_at":
        value = record.get("created_at")
    return value


class CustomJSONEncoder(json.JSONEncoder):
    """Custom encoder to handle non JSON serializable types."""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, (date, datetime)):
            return obj.isoformat()
        elif isinstance(obj, Message):
            return obj.to_dict()
        elif isinstance(obj, Metrics):
            return obj.to_dict()
        elif isinstance(obj, type):
            return str(obj)

        return super().default(obj)


def serialize_session_json_fields(session: dict) -> dict:
    """Serialize all JSON fields in the given Session dictionary.

    Args:
        data (dict): The dictionary to serialize JSON fields in.

    Returns:
        dict: The dictionary with JSON fields serialized.
    """
    if session.get("session_data") is not None:
        session["session_data"] = json.dumps(session["session_data"])
    if session.get("agent_data") is not None:
        session["agent_data"] = json.dumps(session["agent_data"])
    if session.get("team_data") is not None:
        session["team_data"] = json.dumps(session["team_data"])
    if session.get("workflow_data") is not None:
        session["workflow_data"] = json.dumps(session["workflow_data"])
    if session.get("metadata") is not None:
        session["metadata"] = json.dumps(session["metadata"])
    if session.get("chat_history") is not None:
        session["chat_history"] = json.dumps(session["chat_history"])
    if session.get("summary") is not None:
        session["summary"] = json.dumps(session["summary"], cls=CustomJSONEncoder)
    if session.get("runs") is not None:
        session["runs"] = json.dumps(session["runs"], cls=CustomJSONEncoder)

    return session


def deserialize_session_json_fields(session: dict) -> dict:
    """Deserialize JSON fields in the given Session dictionary.

    Args:
        session (dict): The dictionary to deserialize.

    Returns:
        dict: The dictionary with JSON string fields deserialized to objects.
    """
    from agno.utils.log import log_warning

    if session.get("agent_data") is not None and isinstance(session["agent_data"], str):
        try:
            session["agent_data"] = json.loads(session["agent_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse agent_data as JSON, keeping as string: {e}")

    if session.get("team_data") is not None and isinstance(session["team_data"], str):
        try:
            session["team_data"] = json.loads(session["team_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse team_data as JSON, keeping as string: {e}")

    if session.get("workflow_data") is not None and isinstance(session["workflow_data"], str):
        try:
            session["workflow_data"] = json.loads(session["workflow_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse workflow_data as JSON, keeping as string: {e}")

    if session.get("metadata") is not None and isinstance(session["metadata"], str):
        try:
            session["metadata"] = json.loads(session["metadata"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse metadata as JSON, keeping as string: {e}")

    if session.get("chat_history") is not None and isinstance(session["chat_history"], str):
        try:
            session["chat_history"] = json.loads(session["chat_history"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse chat_history as JSON, keeping as string: {e}")

    if session.get("summary") is not None and isinstance(session["summary"], str):
        try:
            session["summary"] = json.loads(session["summary"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse summary as JSON, keeping as string: {e}")

    if session.get("session_data") is not None and isinstance(session["session_data"], str):
        try:
            session["session_data"] = json.loads(session["session_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse session_data as JSON, keeping as string: {e}")

    # Handle runs field with session type checking
    if session.get("runs") is not None and isinstance(session["runs"], str):
        try:
            session["runs"] = json.loads(session["runs"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse runs as JSON, keeping as string: {e}")

    return session


def db_from_dict(db_data: Dict[str, Any]) -> Optional[Union["BaseDb"]]:
    """
    Create a database instance from a dictionary.

    Args:
        db_data: Dictionary containing database configuration

    Returns:
        Database instance or None if creation fails
    """
    db_type = db_data.get("type")
    if db_type == "postgres":
        try:
            from agno.db.postgres import PostgresDb

            return PostgresDb.from_dict(db_data)
        except Exception as e:
            log_error(f"Error reconstructing PostgresDb from dictionary: {e}")
            return None
    elif db_type == "sqlite":
        try:
            from agno.db.sqlite import SqliteDb

            return SqliteDb.from_dict(db_data)
        except Exception as e:
            log_error(f"Error reconstructing SqliteDb from dictionary: {e}")
            return None
    else:
        log_warning(f"Unknown database type: {db_type}")
        return None
