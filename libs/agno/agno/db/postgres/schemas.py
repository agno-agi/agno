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
    "memory": {"type": JSON, "nullable": True},
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
    "memory": {"type": JSON, "nullable": True},
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
    "memory": {"type": JSON, "nullable": True},
    "workflow_data": {"type": JSON, "nullable": True},
    "session_data": {"type": JSON, "nullable": True},
    "extra_data": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": True},
    "chat_history": {"type": JSON, "nullable": True},
    "runs": {"type": JSON, "nullable": True},
    "summary": {"type": JSON, "nullable": True},
}

USER_MEMORY_TABLE_SCHEMA = {}
LEARNING_TABLE_SCHEMA = {}
EVAL_TABLE_SCHEMA = {}


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
        "memory": {},
        "learnings": {},
        "eval_runs": {},
    }

    schema = schemas.get(table_type, {})
    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema
