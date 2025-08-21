"""Table schemas and related utils used by the SqliteDb class"""

from typing import Any

try:
    from sqlalchemy.types import JSON, BigInteger, Boolean, Date, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


SESSION_TABLE_SCHEMA = {
    "session_id": {"type": String, "primary_key": True, "nullable": False},
    "session_type": {"type": String, "nullable": False, "index": True},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
    "workflow_id": {"type": String, "nullable": True},
    "user_id": {"type": String, "nullable": True},
    "session_data": {"type": JSON, "nullable": True},
    "agent_data": {"type": JSON, "nullable": True},
    "team_data": {"type": JSON, "nullable": True},
    "workflow_data": {"type": JSON, "nullable": True},
    "metadata": {"type": JSON, "nullable": True},
    "runs": {"type": JSON, "nullable": True},
    "summary": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
}

USER_MEMORY_TABLE_SCHEMA = {
    "memory_id": {"type": String, "primary_key": True, "nullable": False},
    "memory": {"type": JSON, "nullable": False},
    "input": {"type": String, "nullable": True},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
    "user_id": {"type": String, "nullable": True, "index": True},
    "topics": {"type": JSON, "nullable": True},
    "updated_at": {"type": BigInteger, "nullable": True, "index": True},
}

EVAL_TABLE_SCHEMA = {
    "run_id": {"type": String, "primary_key": True, "nullable": False},
    "eval_type": {"type": String, "nullable": False},
    "eval_data": {"type": JSON, "nullable": False},
    "eval_input": {"type": JSON, "nullable": False},
    "name": {"type": String, "nullable": True},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
    "workflow_id": {"type": String, "nullable": True},
    "model_id": {"type": String, "nullable": True},
    "model_provider": {"type": String, "nullable": True},
    "evaluated_component_name": {"type": String, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
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
    "status": {"type": String, "nullable": True},
    "status_message": {"type": String, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "external_id": {"type": String, "nullable": True},
}

METRICS_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "agent_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
    "team_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
    "workflow_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
    "agent_sessions_count": {"type": BigInteger, "nullable": False, "default": 0},
    "team_sessions_count": {"type": BigInteger, "nullable": False, "default": 0},
    "workflow_sessions_count": {"type": BigInteger, "nullable": False, "default": 0},
    "users_count": {"type": BigInteger, "nullable": False, "default": 0},
    "token_metrics": {"type": JSON, "nullable": False, "default": "{}"},
    "model_metrics": {"type": JSON, "nullable": False, "default": "{}"},
    "date": {"type": Date, "nullable": False, "index": True},
    "aggregation_period": {"type": String, "nullable": False, "index": True},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": True},
    "completed": {"type": Boolean, "nullable": False, "default": False},
    "_unique_constraints": [
        {
            "name": "uq_metrics_date_period",
            "columns": ["date", "aggregation_period"],
        }
    ],
}


def get_table_schema_definition(table_type: str) -> dict[str, Any]:
    """
    Get the expected schema definition for the given table.

    Args:
        table_type (str): The type of table to get the schema for.

    Returns:
        Dict[str, Any]: Dictionary containing column definitions for the table
    """
    schemas = {
        "sessions": SESSION_TABLE_SCHEMA,
        "evals": EVAL_TABLE_SCHEMA,
        "metrics": METRICS_TABLE_SCHEMA,
        "memories": USER_MEMORY_TABLE_SCHEMA,
        "knowledge": KNOWLEDGE_TABLE_SCHEMA,
    }
    schema = schemas.get(table_type, {})

    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema  # type: ignore[return-value]
