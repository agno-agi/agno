"""Table schemas and related utils used by the SingleStoreDb class"""

from typing import Any

try:
    from sqlalchemy.types import JSON, BigInteger, Boolean, Date, String, Text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

SESSION_TABLE_SCHEMA = {
    "session_id": {"type": lambda: String(128), "primary_key": True, "nullable": False},
    "session_type": {"type": lambda: String(20), "nullable": False, "index": True},
    "agent_id": {"type": lambda: String(128), "nullable": True},
    "team_id": {"type": lambda: String(128), "nullable": True},
    "workflow_id": {"type": lambda: String(128), "nullable": True},
    "user_id": {"type": lambda: String(128), "nullable": True},
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
    "memory_id": {"type": lambda: String(128), "primary_key": True, "nullable": False},
    "memory": {"type": JSON, "nullable": False},
    "input": {"type": Text, "nullable": True},
    "agent_id": {"type": lambda: String(128), "nullable": True},
    "team_id": {"type": lambda: String(128), "nullable": True},
    "user_id": {"type": lambda: String(128), "nullable": True, "index": True},
    "topics": {"type": JSON, "nullable": True},
    "feedback": {"type": Text, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True, "index": True},
}

EVAL_TABLE_SCHEMA = {
    "run_id": {"type": lambda: String(128), "primary_key": True, "nullable": False},
    "eval_type": {"type": lambda: String(50), "nullable": False},
    "eval_data": {"type": JSON, "nullable": False},
    "eval_input": {"type": JSON, "nullable": False},
    "name": {"type": lambda: String(255), "nullable": True},
    "agent_id": {"type": lambda: String(128), "nullable": True},
    "team_id": {"type": lambda: String(128), "nullable": True},
    "workflow_id": {"type": lambda: String(128), "nullable": True},
    "model_id": {"type": lambda: String(128), "nullable": True},
    "model_provider": {"type": lambda: String(50), "nullable": True},
    "evaluated_component_name": {"type": lambda: String(255), "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
}

KNOWLEDGE_TABLE_SCHEMA = {
    "id": {"type": lambda: String(128), "primary_key": True, "nullable": False},
    "name": {"type": lambda: String(255), "nullable": False},
    "description": {"type": Text, "nullable": False},
    "metadata": {"type": JSON, "nullable": True},
    "type": {"type": lambda: String(50), "nullable": True},
    "size": {"type": BigInteger, "nullable": True},
    "linked_to": {"type": lambda: String(128), "nullable": True},
    "access_count": {"type": BigInteger, "nullable": True},
    "status": {"type": lambda: String(50), "nullable": True},
    "status_message": {"type": Text, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "external_id": {"type": lambda: String(128), "nullable": True},
}

METRICS_TABLE_SCHEMA = {
    "id": {"type": lambda: String(128), "primary_key": True, "nullable": False},
    "agent_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
    "team_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
    "workflow_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
    "agent_sessions_count": {"type": BigInteger, "nullable": False, "default": 0},
    "team_sessions_count": {"type": BigInteger, "nullable": False, "default": 0},
    "workflow_sessions_count": {"type": BigInteger, "nullable": False, "default": 0},
    "users_count": {"type": BigInteger, "nullable": False, "default": 0},
    "token_metrics": {"type": JSON, "nullable": False, "default": {}},
    "model_metrics": {"type": JSON, "nullable": False, "default": {}},
    "date": {"type": Date, "nullable": False, "index": True},
    "aggregation_period": {"type": lambda: String(20), "nullable": False, "index": True},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": True},
    "completed": {"type": Boolean, "nullable": False, "default": False},
}

CULTURAL_KNOWLEDGE_TABLE_SCHEMA = {
    "id": {"type": lambda: String(128), "primary_key": True, "nullable": False},
    "name": {"type": lambda: String(255), "nullable": False, "index": True},
    "summary": {"type": Text, "nullable": True},
    "content": {"type": JSON, "nullable": True},
    "metadata": {"type": JSON, "nullable": True},
    "input": {"type": Text, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "agent_id": {"type": lambda: String(128), "nullable": True},
    "team_id": {"type": lambda: String(128), "nullable": True},
}


VERSIONS_TABLE_SCHEMA = {
    "table_name": {"type": lambda: String(128), "nullable": False, "primary_key": True},
    "version": {"type": lambda: String(10), "nullable": False},
    "created_at": {"type": lambda: String(128), "nullable": False, "index": True},
    "updated_at": {"type": lambda: String(128), "nullable": True},
}

TRACE_TABLE_SCHEMA = {
    "trace_id": {"type": lambda: String(128), "primary_key": True, "nullable": False},
    "name": {"type": lambda: String(512), "nullable": False},
    "status": {"type": lambda: String(20), "nullable": False, "index": True},
    "start_time": {"type": lambda: String(64), "nullable": False, "index": True},  # ISO 8601 datetime string
    "end_time": {"type": lambda: String(64), "nullable": False},  # ISO 8601 datetime string
    "duration_ms": {"type": BigInteger, "nullable": False},
    "run_id": {"type": lambda: String(128), "nullable": True, "index": True},
    "session_id": {"type": lambda: String(128), "nullable": True, "index": True},
    "user_id": {"type": lambda: String(128), "nullable": True, "index": True},
    "agent_id": {"type": lambda: String(128), "nullable": True, "index": True},
    "team_id": {"type": lambda: String(128), "nullable": True, "index": True},
    "workflow_id": {"type": lambda: String(128), "nullable": True, "index": True},
    "created_at": {"type": lambda: String(64), "nullable": False, "index": True},  # ISO 8601 datetime string
}


def _get_span_table_schema(traces_table_name: str = "agno_traces", db_schema: str = "agno") -> dict[str, Any]:
    """Get the span table schema with the correct foreign key reference.

    Args:
        traces_table_name: The name of the traces table to reference in the foreign key.
        db_schema: The database schema name.

    Returns:
        The span table schema dictionary.
    """
    return {
        "span_id": {"type": lambda: String(128), "primary_key": True, "nullable": False},
        "trace_id": {
            "type": lambda: String(128),
            "nullable": False,
            "index": True,
            "foreign_key": f"{db_schema}.{traces_table_name}.trace_id",
        },
        "parent_span_id": {"type": lambda: String(128), "nullable": True, "index": True},
        "name": {"type": lambda: String(512), "nullable": False},
        "span_kind": {"type": lambda: String(50), "nullable": False},
        "status_code": {"type": lambda: String(20), "nullable": False},
        "status_message": {"type": Text, "nullable": True},
        "start_time": {"type": lambda: String(64), "nullable": False, "index": True},  # ISO 8601 datetime string
        "end_time": {"type": lambda: String(64), "nullable": False},  # ISO 8601 datetime string
        "duration_ms": {"type": BigInteger, "nullable": False},
        "attributes": {"type": JSON, "nullable": True},
        "created_at": {"type": lambda: String(64), "nullable": False, "index": True},  # ISO 8601 datetime string
    }


def get_table_schema_definition(
    table_type: str, traces_table_name: str = "agno_traces", db_schema: str = "agno"
) -> dict[str, Any]:
    """
    Get the expected schema definition for the given table.

    Args:
        table_type (str): The type of table to get the schema for.
        traces_table_name (str): The name of the traces table (used for spans foreign key).
        db_schema (str): The database schema name (used for spans foreign key).

    Returns:
        Dict[str, Any]: Dictionary containing column definitions for the table
    """
    # Handle spans table specially to resolve the foreign key reference
    if table_type == "spans":
        return _get_span_table_schema(traces_table_name, db_schema)

    schemas = {
        "sessions": SESSION_TABLE_SCHEMA,
        "evals": EVAL_TABLE_SCHEMA,
        "metrics": METRICS_TABLE_SCHEMA,
        "memories": USER_MEMORY_TABLE_SCHEMA,
        "knowledge": KNOWLEDGE_TABLE_SCHEMA,
        "culture": CULTURAL_KNOWLEDGE_TABLE_SCHEMA,
        "versions": VERSIONS_TABLE_SCHEMA,
        "traces": TRACE_TABLE_SCHEMA,
    }
    schema = schemas.get(table_type, {})

    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema  # type: ignore[return-value]
