"""Logic shared across different database implementations"""

import json
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from agno.metrics import ModelMetrics, RunMetrics, SessionMetrics
from agno.models.message import Message
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb, SessionType
    from agno.session import Session


def detect_session_type(record: Dict[str, Any]) -> str:
    """Detect session type from a raw session dict, inferring from component IDs if needed.

    Priority: component IDs (agent_id > team_id > workflow_id) > stored session_type > fallback "agent".

    Args:
        record: Raw session dictionary.

    Returns:
        Session type string ("agent", "team", or "workflow").
    """
    if record.get("agent_id"):
        return "agent"
    if record.get("team_id"):
        return "team"
    if record.get("workflow_id"):
        return "workflow"
    st = record.get("session_type")
    if st:
        return st.value if hasattr(st, "value") else st
    return "agent"


def deserialize_session_by_type(record: Dict[str, Any]) -> "Session":
    """Deserialize a raw session dict into the correct Session subclass based on detected type.

    Args:
        record: Raw session dictionary.

    Returns:
        Session subclass instance (AgentSession, TeamSession, or WorkflowSession).
    """
    from agno.session import AgentSession, TeamSession, WorkflowSession

    st = detect_session_type(record)
    if st == "agent":
        return AgentSession.from_dict(record)  # type: ignore
    elif st == "team":
        return TeamSession.from_dict(record)  # type: ignore
    elif st == "workflow":
        return WorkflowSession.from_dict(record)  # type: ignore
    return AgentSession.from_dict(record)  # type: ignore


def deserialize_session(session_type: Optional["SessionType"], record: Dict[str, Any]) -> "Session":
    """Deserialize a raw session dict into the correct Session subclass.

    Args:
        session_type: The type to deserialize as. If None, auto-detects from the record's component IDs.
        record: Raw session dictionary.

    Returns:
        Session subclass instance (AgentSession, TeamSession, or WorkflowSession).

    Raises:
        ValueError: If session_type is not a valid SessionType.
    """
    from agno.db.base import SessionType
    from agno.session import AgentSession, TeamSession, WorkflowSession

    if session_type is None:
        return deserialize_session_by_type(record)
    if session_type == SessionType.AGENT:
        return AgentSession.from_dict(record)  # type: ignore
    elif session_type == SessionType.TEAM:
        return TeamSession.from_dict(record)  # type: ignore
    elif session_type == SessionType.WORKFLOW:
        return WorkflowSession.from_dict(record)  # type: ignore
    raise ValueError(f"Invalid session type: {session_type}")


def deserialize_sessions(session_type: Optional["SessionType"], records: List[Dict[str, Any]]) -> List["Session"]:
    """Deserialize a list of raw session dicts into the correct Session subclasses.

    Args:
        session_type: The type to deserialize as. If None, auto-detects each record individually.
        records: List of raw session dictionaries.

    Returns:
        List of Session subclass instances.
    """
    return [deserialize_session(session_type, record) for record in records]


async def resolve_session_type(
    db: Union["BaseDb", "AsyncBaseDb"],
    session_id: str,
    session_type: Optional["SessionType"],
    user_id: Optional[str] = None,
) -> Tuple[Optional["SessionType"], Optional[Any]]:
    """Resolve session type by auto-detecting from DB if not provided.

    Args:
        db: Database adapter instance (sync or async).
        session_id: The session ID to look up.
        session_type: The session type if already known. If None, auto-detects from DB.
        user_id: Optional user ID filter.

    Returns:
        Tuple of (resolved_type, raw_session):
        - If session_type is already set: (session_type, None) — no DB fetch needed.
        - If session_type is None and session found: (detected_type, raw_dict).
        - If session_type is None and session not found: (None, None).
    """
    if session_type is not None:
        return session_type, None

    from agno.db.base import AsyncBaseDb, SessionType

    if isinstance(db, AsyncBaseDb):
        raw = await db.get_session(session_id=session_id, user_id=user_id, deserialize=False)
    else:
        raw = db.get_session(session_id=session_id, user_id=user_id, deserialize=False)

    if not raw:
        return None, None

    detected = detect_session_type(raw if isinstance(raw, dict) else {})
    resolved = SessionType(detected)
    return resolved, raw


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
        elif isinstance(obj, (RunMetrics, SessionMetrics, ModelMetrics)):
            return obj.to_dict()
        elif isinstance(obj, type):
            return str(obj)

        return super().default(obj)


def json_serializer(obj: Any) -> str:
    """Custom JSON serializer for SQLAlchemy engine.

    This function is used as the json_serializer parameter when creating
    SQLAlchemy engines for PostgreSQL. It handles non-JSON-serializable
    types like datetime, date, UUID, etc.

    Args:
        obj: The object to serialize to JSON.

    Returns:
        JSON string representation of the object.
    """
    return json.dumps(obj, cls=CustomJSONEncoder)


def serialize_session_json_fields(session: dict) -> dict:
    """Serialize all JSON fields in the given Session dictionary.

    Uses CustomJSONEncoder to handle non-JSON-serializable types like
    datetime, date, UUID, Message, Metrics, etc.

    Args:
        session (dict): The session dictionary to serialize JSON fields in.

    Returns:
        dict: The dictionary with JSON fields serialized.
    """
    if session.get("session_data") is not None:
        session["session_data"] = json.dumps(session["session_data"], cls=CustomJSONEncoder)
    if session.get("agent_data") is not None:
        session["agent_data"] = json.dumps(session["agent_data"], cls=CustomJSONEncoder)
    if session.get("team_data") is not None:
        session["team_data"] = json.dumps(session["team_data"], cls=CustomJSONEncoder)
    if session.get("workflow_data") is not None:
        session["workflow_data"] = json.dumps(session["workflow_data"], cls=CustomJSONEncoder)
    if session.get("metadata") is not None:
        session["metadata"] = json.dumps(session["metadata"], cls=CustomJSONEncoder)
    if session.get("chat_history") is not None:
        session["chat_history"] = json.dumps(session["chat_history"], cls=CustomJSONEncoder)
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
            log_warning(f"Warning: Could not parse agent_data as JSON, keeping as string: {str(e)}")

    if session.get("team_data") is not None and isinstance(session["team_data"], str):
        try:
            session["team_data"] = json.loads(session["team_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse team_data as JSON, keeping as string: {str(e)}")

    if session.get("workflow_data") is not None and isinstance(session["workflow_data"], str):
        try:
            session["workflow_data"] = json.loads(session["workflow_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse workflow_data as JSON, keeping as string: {str(e)}")

    if session.get("metadata") is not None and isinstance(session["metadata"], str):
        try:
            session["metadata"] = json.loads(session["metadata"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse metadata as JSON, keeping as string: {str(e)}")

    if session.get("chat_history") is not None and isinstance(session["chat_history"], str):
        try:
            session["chat_history"] = json.loads(session["chat_history"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse chat_history as JSON, keeping as string: {str(e)}")

    if session.get("summary") is not None and isinstance(session["summary"], str):
        try:
            session["summary"] = json.loads(session["summary"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse summary as JSON, keeping as string: {str(e)}")

    if session.get("session_data") is not None and isinstance(session["session_data"], str):
        try:
            session["session_data"] = json.loads(session["session_data"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse session_data as JSON, keeping as string: {str(e)}")

    # Handle runs field with session type checking
    if session.get("runs") is not None and isinstance(session["runs"], str):
        try:
            session["runs"] = json.loads(session["runs"])
        except (json.JSONDecodeError, TypeError) as e:
            log_warning(f"Warning: Could not parse runs as JSON, keeping as string: {str(e)}")

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
            log_error(f"Error reconstructing PostgresDb from dictionary: {str(e)}")
            return None
    elif db_type == "sqlite":
        try:
            from agno.db.sqlite import SqliteDb

            return SqliteDb.from_dict(db_data)
        except Exception as e:
            log_error(f"Error reconstructing SqliteDb from dictionary: {str(e)}")
            return None
    else:
        log_warning(f"Unknown database type: {db_type}")
        return None
