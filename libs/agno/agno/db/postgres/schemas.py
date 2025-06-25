"""Table schemas and related utils used by the Postgres Db class"""

from typing import Any

try:
    from sqlalchemy.types import JSON, BigInteger, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

AGENT_SESSION_TABLE_SCHEMA = {
    "session_id": {"type": String, "primary_key": True, "nullable": False},
    "agent_id": {"type": String, "nullable": False},
    "user_id": {"type": String, "nullable": True},
    "team_session_id": {"type": String, "nullable": True},
    "session_data": {"type": JSON, "nullable": True},
    "extra_data": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": True},
    "agent_data": {"type": JSON, "nullable": True},
    "chat_history": {"type": JSON, "nullable": True},
    "runs": {"type": JSON, "nullable": True},
    "summary": {"type": JSON, "nullable": True},
}

TEAM_SESSION_TABLE_SCHEMA = {
    "session_id": {"type": String, "primary_key": True, "nullable": False},
    "team_id": {"type": String, "nullable": False},
    "user_id": {"type": String, "nullable": True},
    "team_session_id": {"type": String, "nullable": True},
    "team_data": {"type": JSON, "nullable": True},
    "session_data": {"type": JSON, "nullable": True},
    "extra_data": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": True},
    "chat_history": {"type": JSON, "nullable": True},
    "runs": {"type": JSON, "nullable": True},
    "summary": {"type": JSON, "nullable": True},
}

WORKFLOW_SESSION_TABLE_SCHEMA = {
    "session_id": {"type": String, "primary_key": True, "nullable": False},
    "workflow_id": {"type": String, "nullable": False},
    "user_id": {"type": String, "nullable": True},
    "workflow_data": {"type": JSON, "nullable": True},
    "session_data": {"type": JSON, "nullable": True},
    "extra_data": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": True},
    "chat_history": {"type": JSON, "nullable": True},
    "runs": {"type": JSON, "nullable": True},
    "summary": {"type": JSON, "nullable": True},
}

USER_MEMORY_TABLE_SCHEMA = {
    "memory_id": {"type": String, "primary_key": True, "nullable": False},
    "memory": {"type": JSON, "nullable": False},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
    "workflow_id": {"type": String, "nullable": True},
    "user_id": {"type": String, "nullable": True},
    "topics": {"type": JSON, "nullable": True},
    "feedback": {"type": String, "nullable": True},
    "last_updated": {"type": BigInteger, "nullable": True},
}

EVAL_TABLE_SCHEMA = {
    "run_id": {"type": String, "primary_key": True, "nullable": False},
    "eval_type": {"type": String, "nullable": False},
    "eval_data": {"type": JSON, "nullable": False},
    "name": {"type": String, "nullable": True},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
    "workflow_id": {"type": String, "nullable": True},
    "model_id": {"type": String, "nullable": True},
    "model_provider": {"type": String, "nullable": True},
    "evaluated_component_name": {"type": String, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False},
}

KNOWLEDGE_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "name": {"type": String, "nullable": False},
    "description": {"type": String, "nullable": False},
    "metadata": {"type": JSON, "nullable": True},
    "type": {"type": String, "nullable": True},
    "size": {"type": BigInteger, "nullable": True},
    "linked_to": {"type": String, "nullable": True},
    "access_count": {"type": BigInteger, "nullable": True},
}

LEARNING_TABLE_SCHEMA = {}


def get_table_schema_definition(table_type: str) -> dict[str, Any]:
    """
    Get the expected schema definition for the given table.

    Args:
        table_type (str): The type of table to get the schema for.

    Returns:
        Dict[str, Any]: Dictionary containing column definitions for the table
    """
    schemas = {
        "agent_sessions": AGENT_SESSION_TABLE_SCHEMA,
        "team_sessions": TEAM_SESSION_TABLE_SCHEMA,
        "workflow_sessions": WORKFLOW_SESSION_TABLE_SCHEMA,
        "user_memories": USER_MEMORY_TABLE_SCHEMA,
        "evals": EVAL_TABLE_SCHEMA,
        "knowledge_documents": KNOWLEDGE_TABLE_SCHEMA,
        "learnings": {},
    }

    schema = schemas.get(table_type, {})
    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema
