"""Table schemas and related utils used by the PostgresDb class"""

from typing import Any

try:
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.types import BigInteger, Boolean, Date, String, Text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

SESSION_TABLE_SCHEMA = {
    "session_id": {"type": String, "nullable": False},
    "session_type": {"type": String, "nullable": False, "index": True},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
    "workflow_id": {"type": String, "nullable": True},
    "user_id": {"type": String, "nullable": True},
    "session_data": {"type": JSONB, "nullable": True},
    "agent_data": {"type": JSONB, "nullable": True},
    "team_data": {"type": JSONB, "nullable": True},
    "workflow_data": {"type": JSONB, "nullable": True},
    "metadata": {"type": JSONB, "nullable": True},
    "runs": {"type": JSONB, "nullable": True},
    "summary": {"type": JSONB, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "_unique_constraints": [
        {
            "name": "uq_session_id",
            "columns": ["session_id"],
        },
    ],
}

MEMORY_TABLE_SCHEMA = {
    "memory_id": {"type": String, "primary_key": True, "nullable": False},
    "memory": {"type": JSONB, "nullable": False},
    "feedback": {"type": Text, "nullable": True},
    "input": {"type": Text, "nullable": True},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
    "user_id": {"type": String, "nullable": True, "index": True},
    "topics": {"type": JSONB, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True, "index": True},
}

EVAL_TABLE_SCHEMA = {
    "run_id": {"type": String, "primary_key": True, "nullable": False},
    "eval_type": {"type": String, "nullable": False},
    "eval_data": {"type": JSONB, "nullable": False},
    "eval_input": {"type": JSONB, "nullable": False},
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
    "description": {"type": Text, "nullable": False},
    "metadata": {"type": JSONB, "nullable": True},
    "type": {"type": String, "nullable": True},
    "size": {"type": BigInteger, "nullable": True},
    "linked_to": {"type": String, "nullable": True},
    "access_count": {"type": BigInteger, "nullable": True},
    "status": {"type": String, "nullable": True},
    "status_message": {"type": Text, "nullable": True},
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
    "token_metrics": {"type": JSONB, "nullable": False, "default": {}},
    "model_metrics": {"type": JSONB, "nullable": False, "default": {}},
    "date": {"type": Date, "nullable": False, "index": True},
    "aggregation_period": {"type": String, "nullable": False},
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

CULTURAL_KNOWLEDGE_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "name": {"type": String, "nullable": False, "index": True},
    "summary": {"type": Text, "nullable": True},
    "content": {"type": JSONB, "nullable": True},
    "metadata": {"type": JSONB, "nullable": True},
    "input": {"type": Text, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
}

VERSIONS_TABLE_SCHEMA = {
    "table_name": {"type": String, "nullable": False, "primary_key": True},
    "version": {"type": String, "nullable": False},
    "created_at": {"type": String, "nullable": False, "index": True},
    "updated_at": {"type": String, "nullable": True},
}

TRACE_TABLE_SCHEMA = {
    "trace_id": {"type": String, "primary_key": True, "nullable": False},
    "name": {"type": String, "nullable": False},
    "status": {"type": String, "nullable": False, "index": True},
    "start_time": {"type": String, "nullable": False, "index": True},  # ISO 8601 datetime string
    "end_time": {"type": String, "nullable": False},  # ISO 8601 datetime string
    "duration_ms": {"type": BigInteger, "nullable": False},
    "run_id": {"type": String, "nullable": True, "index": True},
    "session_id": {"type": String, "nullable": True, "index": True},
    "user_id": {"type": String, "nullable": True, "index": True},
    "agent_id": {"type": String, "nullable": True, "index": True},
    "team_id": {"type": String, "nullable": True, "index": True},
    "workflow_id": {"type": String, "nullable": True, "index": True},
    "created_at": {"type": String, "nullable": False, "index": True},  # ISO 8601 datetime string
}

SPAN_TABLE_SCHEMA = {
    "span_id": {"type": String, "primary_key": True, "nullable": False},
    "trace_id": {
        "type": String,
        "nullable": False,
        "index": True,
        "foreign_key": "agno_traces.trace_id",  # Foreign key to traces table
    },
    "parent_span_id": {"type": String, "nullable": True, "index": True},
    "name": {"type": String, "nullable": False},
    "span_kind": {"type": String, "nullable": False},
    "status_code": {"type": String, "nullable": False},
    "status_message": {"type": Text, "nullable": True},
    "start_time": {"type": String, "nullable": False, "index": True},  # ISO 8601 datetime string
    "end_time": {"type": String, "nullable": False},  # ISO 8601 datetime string
    "duration_ms": {"type": BigInteger, "nullable": False},
    "attributes": {"type": JSONB, "nullable": True},
    "created_at": {"type": String, "nullable": False, "index": True},  # ISO 8601 datetime string
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
        "memories": MEMORY_TABLE_SCHEMA,
        "knowledge": KNOWLEDGE_TABLE_SCHEMA,
        "culture": CULTURAL_KNOWLEDGE_TABLE_SCHEMA,
        "versions": VERSIONS_TABLE_SCHEMA,
        "traces": TRACE_TABLE_SCHEMA,
        "spans": SPAN_TABLE_SCHEMA,
    }

    schema = schemas.get(table_type, {})
    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema  # type: ignore[return-value]
