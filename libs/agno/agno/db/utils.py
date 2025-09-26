"""Logic shared across different database implementations"""

import json
from datetime import date, datetime
from uuid import UUID

from agno.db.base import SessionType
from agno.models.message import Message
from agno.models.metrics import Metrics


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
    """Deserialize all JSON fields in the given Session dictionary.

    Args:
        session (dict): The dictionary to deserialize.

    Returns:
        dict: The dictionary with JSON fields deserialized.
    """
    if session.get("agent_data") is not None:
        session["agent_data"] = json.loads(session["agent_data"])
    if session.get("team_data") is not None:
        session["team_data"] = json.loads(session["team_data"])
    if session.get("workflow_data") is not None:
        session["workflow_data"] = json.loads(session["workflow_data"])
    if session.get("metadata") is not None:
        session["metadata"] = json.loads(session["metadata"])
    if session.get("chat_history") is not None:
        session["chat_history"] = json.loads(session["chat_history"])
    if session.get("summary") is not None:
        session["summary"] = json.loads(session["summary"])
    if session.get("session_data") is not None and isinstance(session["session_data"], str):
        session["session_data"] = json.loads(session["session_data"])
    if session.get("runs") is not None:
        if session["session_type"] == SessionType.AGENT.value:
            session["runs"] = json.loads(session["runs"])
        if session["session_type"] == SessionType.TEAM.value:
            session["runs"] = json.loads(session["runs"])
        if session["session_type"] == SessionType.WORKFLOW.value:
            session["runs"] = json.loads(session["runs"])

    return session
