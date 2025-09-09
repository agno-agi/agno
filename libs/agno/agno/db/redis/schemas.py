"""Table schemas and related utils used by the RedisDb class"""

from typing import Any

SESSION_SCHEMA = {
    "session_id": {"type": "string", "primary_key": True},
    "session_type": {"type": "string"},
    "agent_id": {"type": "string"},
    "team_id": {"type": "string"},
    "workflow_id": {"type": "string"},
    "user_id": {"type": "string"},
    "session_data": {"type": "json"},
    "agent_data": {"type": "json"},
    "team_data": {"type": "json"},
    "workflow_data": {"type": "json"},
    "metadata": {"type": "json"},
    "runs": {"type": "json"},
    "summary": {"type": "json"},
    "created_at": {"type": "integer"},
    "updated_at": {"type": "integer"},
}

USER_MEMORY_SCHEMA = {
    "memory_id": {"type": "string", "primary_key": True},
    "memory": {"type": "json"},
    "agent_id": {"type": "string"},
    "team_id": {"type": "string"},
    "user_id": {"type": "string"},
    "topics": {"type": "json"},
    "updated_at": {"type": "integer"},
}

METRICS_SCHEMA = {
    "id": {"type": "string", "primary_key": True},
    "agent_runs_count": {"type": "integer", "default": 0},
    "team_runs_count": {"type": "integer", "default": 0},
    "workflow_runs_count": {"type": "integer", "default": 0},
    "agent_sessions_count": {"type": "integer", "default": 0},
    "team_sessions_count": {"type": "integer", "default": 0},
    "workflow_sessions_count": {"type": "integer", "default": 0},
    "users_count": {"type": "integer", "default": 0},
    "token_metrics": {"type": "json", "default": {}},
    "model_metrics": {"type": "json", "default": {}},
    "date": {"type": "date"},
    "aggregation_period": {"type": "string"},
    "created_at": {"type": "integer"},
    "updated_at": {"type": "integer"},
    "completed": {"type": "boolean", "default": False},
}

EVAL_SCHEMA = {
    "run_id": {"type": "string", "primary_key": True},
    "eval_type": {"type": "string"},
    "eval_data": {"type": "json"},
    "eval_input": {"type": "json"},
    "name": {"type": "string"},
    "agent_id": {"type": "string"},
    "team_id": {"type": "string"},
    "workflow_id": {"type": "string"},
    "model_id": {"type": "string"},
    "model_provider": {"type": "string"},
    "evaluated_component_name": {"type": "string"},
    "created_at": {"type": "integer"},
    "updated_at": {"type": "integer"},
}

KNOWLEDGE_SCHEMA = {
    "id": {"type": "string", "primary_key": True},
    "name": {"type": "string"},
    "description": {"type": "string"},
    "metadata": {"type": "json"},
    "type": {"type": "string"},
    "size": {"type": "integer"},
    "linked_to": {"type": "string"},
    "access_count": {"type": "integer"},
    "created_at": {"type": "integer"},
    "updated_at": {"type": "integer"},
    "status": {"type": "string"},
    "status_message": {"type": "string"},
    "external_id": {"type": "string"},
}


def get_table_schema_definition(table_type: str) -> dict[str, Any]:
    """
    Get the expected schema definition for the given table.

    For Redis, we don't need actual schemas since it's a key-value store,
    but we maintain this for compatibility with the base interface.

    Args:
        table_type (str): The type of table to get the schema for.

    Returns:
        Dict[str, Any]: Dictionary containing schema information for the table
    """
    schemas = {
        "sessions": SESSION_SCHEMA,
        "memories": USER_MEMORY_SCHEMA,
        "metrics": METRICS_SCHEMA,
        "evals": EVAL_SCHEMA,
        "knowledge": KNOWLEDGE_SCHEMA,
    }

    schema = schemas.get(table_type, {})
    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema
