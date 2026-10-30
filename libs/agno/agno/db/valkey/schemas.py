"""Table schemas and related utils used by the ValkeyDb class"""

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
    "input": {"type": "string"},
    "feedback": {"type": "string"},
    "created_at": {"type": "integer"},
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
    "user_id": {"type": "string", "default": ""},
    "created_at": {"type": "integer"},
    "updated_at": {"type": "integer"},
    "completed": {"type": "boolean", "default": False},
}

OS_METRICS_SCHEMA = {
    "aggregation_period": {"type": "string", "primary_key": True},
    "date": {"type": "date", "primary_key": True},
    "user_id": {"type": "string", "primary_key": True, "default": ""},
    "component_type": {"type": "string", "primary_key": True},
    "component_id": {"type": "string", "primary_key": True},
    "parent_component_id": {"type": "string", "primary_key": True, "default": ""},
    "sessions_count": {"type": "integer", "default": 0},
    "runs_count": {"type": "integer", "default": 0},
    "input_tokens": {"type": "integer", "default": 0},
    "output_tokens": {"type": "integer", "default": 0},
    "total_tokens": {"type": "integer", "default": 0},
    "duration_runs_count": {"type": "integer", "default": 0},
    "total_duration_ms": {"type": "integer", "default": 0},
    "max_duration_ms": {"type": "integer"},
    "time_to_first_token_runs_count": {"type": "integer", "default": 0},
    "total_time_to_first_token_ms": {"type": "integer", "default": 0},
    "max_time_to_first_token_ms": {"type": "integer"},
    "model_calls_count": {"type": "integer", "default": 0},
    "total_model_call_ms": {"type": "integer", "default": 0},
    "max_model_call_ms": {"type": "integer"},
    "buckets_version": {"type": "integer", "default": 1},
    "status_metrics": {"type": "json", "default": {}},
    "additional_token_metrics": {"type": "json", "default": {}},
    "duration_buckets": {"type": "json", "default": {}},
    "time_to_first_token_buckets": {"type": "json", "default": {}},
    "model_call_buckets": {"type": "json", "default": {}},
    "model_metrics": {"type": "json", "default": []},
    "additional_metrics": {"type": "json", "default": {}},
    "created_at": {"type": "integer"},
    "updated_at": {"type": "integer"},
}

OS_METRICS_TOTALS_SCHEMA = {
    "aggregation_period": {"type": "string", "primary_key": True},
    "date": {"type": "date", "primary_key": True},
    "sessions_count": {"type": "integer", "default": 0},
    "runs_count": {"type": "integer", "default": 0},
    "input_tokens": {"type": "integer", "default": 0},
    "output_tokens": {"type": "integer", "default": 0},
    "total_tokens": {"type": "integer", "default": 0},
    "duration_runs_count": {"type": "integer", "default": 0},
    "total_duration_ms": {"type": "integer", "default": 0},
    "max_duration_ms": {"type": "integer"},
    "time_to_first_token_runs_count": {"type": "integer", "default": 0},
    "total_time_to_first_token_ms": {"type": "integer", "default": 0},
    "max_time_to_first_token_ms": {"type": "integer"},
    "model_calls_count": {"type": "integer", "default": 0},
    "total_model_call_ms": {"type": "integer", "default": 0},
    "max_model_call_ms": {"type": "integer"},
    "buckets_version": {"type": "integer", "default": 1},
    "status_metrics": {"type": "json", "default": {}},
    "additional_token_metrics": {"type": "json", "default": {}},
    "duration_buckets": {"type": "json", "default": {}},
    "time_to_first_token_buckets": {"type": "json", "default": {}},
    "model_call_buckets": {"type": "json", "default": {}},
    "model_metrics": {"type": "json", "default": []},
    "additional_metrics": {"type": "json", "default": {}},
    "created_at": {"type": "integer"},
    "updated_at": {"type": "integer"},
    "completed": {"type": "boolean", "default": False},
    "version": {"type": "integer", "default": 1},
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


LEARNING_SCHEMA = {
    "learning_id": {"type": "string", "primary_key": True},
    "learning_type": {"type": "string"},
    "namespace": {"type": "string"},
    "user_id": {"type": "string"},
    "agent_id": {"type": "string"},
    "team_id": {"type": "string"},
    "workflow_id": {"type": "string"},
    "session_id": {"type": "string"},
    "entity_id": {"type": "string"},
    "entity_type": {"type": "string"},
    "content": {"type": "json"},
    "metadata": {"type": "json"},
    "created_at": {"type": "integer"},
    "updated_at": {"type": "integer"},
}

TRACE_SCHEMA = {
    "trace_id": {"type": "string", "primary_key": True},
    "name": {"type": "string"},
    "status": {"type": "string"},
    "duration_ms": {"type": "integer"},
    "run_id": {"type": "string"},
    "session_id": {"type": "string"},
    "user_id": {"type": "string"},
    "agent_id": {"type": "string"},
    "team_id": {"type": "string"},
    "workflow_id": {"type": "string"},
    "start_time": {"type": "string"},
    "end_time": {"type": "string"},
    "created_at": {"type": "string"},
}

SPAN_SCHEMA = {
    "span_id": {"type": "string", "primary_key": True},
    "trace_id": {"type": "string"},
    "parent_span_id": {"type": "string"},
    "name": {"type": "string"},
    "span_kind": {"type": "string"},
    "status_code": {"type": "string"},
    "status_message": {"type": "string"},
    "start_time": {"type": "string"},
    "end_time": {"type": "string"},
    "attributes": {"type": "json"},
    "created_at": {"type": "string"},
}


def get_table_schema_definition(table_type: str) -> dict[str, Any]:
    """
    Get the expected schema definition for the given table.

    For Valkey, we don't need actual schemas since it's a key-value store,
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
        "os_metrics": OS_METRICS_SCHEMA,
        "os_metrics_totals": OS_METRICS_TOTALS_SCHEMA,
        "evals": EVAL_SCHEMA,
        "knowledge": KNOWLEDGE_SCHEMA,
        "learnings": LEARNING_SCHEMA,
        "traces": TRACE_SCHEMA,
        "spans": SPAN_SCHEMA,
    }

    schema = schemas.get(table_type, {})
    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema
