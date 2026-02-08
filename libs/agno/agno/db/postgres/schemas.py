"""Table schemas and related utils used by the PostgresDb class"""

from typing import Any

try:
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.types import BigInteger, Boolean, Date, Integer, String, Text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

SESSION_TABLE_SCHEMA = {
    "session_id": {"type": String, "primary_key": True, "nullable": False},
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


def _get_span_table_schema(traces_table_name: str = "agno_traces", db_schema: str = "agno") -> dict[str, Any]:
    """Get the span table schema with the correct foreign key reference.

    Args:
        traces_table_name: The name of the traces table to reference in the foreign key.
        db_schema: The database schema name.

    Returns:
        The span table schema dictionary.
    """
    return {
        "span_id": {"type": String, "primary_key": True, "nullable": False},
        "trace_id": {
            "type": String,
            "nullable": False,
            "index": True,
            "foreign_key": f"{db_schema}.{traces_table_name}.trace_id",
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


COMPONENT_TABLE_SCHEMA = {
    "component_id": {"type": String, "primary_key": True},
    "component_type": {"type": String, "nullable": False, "index": True},  # agent|team|workflow
    "name": {"type": String, "nullable": True, "index": True},
    "description": {"type": Text, "nullable": True},
    "current_version": {"type": Integer, "nullable": True, "index": True},
    "metadata": {"type": JSONB, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "deleted_at": {"type": BigInteger, "nullable": True},
}

COMPONENT_CONFIGS_TABLE_SCHEMA = {
    "component_id": {"type": String, "primary_key": True, "foreign_key": "components.component_id"},
    "version": {"type": Integer, "primary_key": True},
    "label": {"type": String, "nullable": True},  # stable|v1.2.0|pre-refactor
    "stage": {"type": String, "nullable": False, "default": "draft", "index": True},  # draft|published
    "config": {"type": JSONB, "nullable": False},
    "notes": {"type": Text, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "deleted_at": {"type": BigInteger, "nullable": True},
}

COMPONENT_LINKS_TABLE_SCHEMA = {
    "parent_component_id": {"type": String, "nullable": False},
    "parent_version": {"type": Integer, "nullable": False},
    "link_kind": {"type": String, "nullable": False, "index": True},
    "link_key": {"type": String, "nullable": False},
    "child_component_id": {"type": String, "nullable": False, "foreign_key": "components.component_id"},
    "child_version": {"type": Integer, "nullable": True},
    "position": {"type": Integer, "nullable": False},
    "meta": {"type": JSONB, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": True, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "__primary_key__": ["parent_component_id", "parent_version", "link_kind", "link_key"],
    "__foreign_keys__": [
        {
            "columns": ["parent_component_id", "parent_version"],
            "ref_table": "component_configs",
            "ref_columns": ["component_id", "version"],
        }
    ],
}
SCHEDULE_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "name": {"type": String, "nullable": False},
    "description": {"type": Text, "nullable": True},
    "method": {"type": String, "nullable": False, "default": "POST"},
    "endpoint": {"type": String, "nullable": False},
    "payload": {"type": JSONB, "nullable": True},
    "cron_expr": {"type": String, "nullable": False},
    "timezone": {"type": String, "nullable": False, "default": "UTC"},
    "timeout_seconds": {"type": BigInteger, "nullable": False, "default": 3600},
    "max_retries": {"type": BigInteger, "nullable": False, "default": 0},
    "retry_delay_seconds": {"type": BigInteger, "nullable": False, "default": 60},
    "enabled": {"type": Boolean, "nullable": False, "default": True},
    "next_run_at": {"type": BigInteger, "nullable": True, "index": True},
    "locked_by": {"type": String, "nullable": True},
    "locked_at": {"type": BigInteger, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "_unique_constraints": [
        {
            "name": "uq_schedule_name",
            "columns": ["name"],
        },
    ],
}

SCHEDULE_RUNS_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "schedule_id": {"type": String, "nullable": False, "index": True},
    "attempt": {"type": BigInteger, "nullable": False, "default": 1},
    "triggered_at": {"type": BigInteger, "nullable": True},
    "completed_at": {"type": BigInteger, "nullable": True},
    "status": {"type": String, "nullable": False, "default": "running", "index": True},
    "status_code": {"type": BigInteger, "nullable": True},
    "run_id": {"type": String, "nullable": True},
    "session_id": {"type": String, "nullable": True},
    "error": {"type": Text, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
}

APPROVAL_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "run_id": {"type": String, "nullable": False, "index": True},
    "session_id": {"type": String, "nullable": False, "index": True},
    "status": {"type": String, "nullable": False, "index": True},
    "source_type": {"type": String, "nullable": False, "index": True},
    "agent_id": {"type": String, "nullable": True, "index": True},
    "team_id": {"type": String, "nullable": True, "index": True},
    "workflow_id": {"type": String, "nullable": True, "index": True},
    "user_id": {"type": String, "nullable": True, "index": True},
    "schedule_id": {"type": String, "nullable": True, "index": True},
    "schedule_run_id": {"type": String, "nullable": True},
    "source_name": {"type": String, "nullable": True},
    "requirements": {"type": JSONB, "nullable": True},
    "context": {"type": JSONB, "nullable": True},
    "resolved_by": {"type": String, "nullable": True},
    "resolved_at": {"type": BigInteger, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
}

LEARNINGS_TABLE_SCHEMA = {
    "learning_id": {"type": String, "primary_key": True, "nullable": False},
    "learning_type": {"type": String, "nullable": False, "index": True},
    "namespace": {"type": String, "nullable": True, "index": True},
    "user_id": {"type": String, "nullable": True, "index": True},
    "agent_id": {"type": String, "nullable": True, "index": True},
    "team_id": {"type": String, "nullable": True, "index": True},
    "workflow_id": {"type": String, "nullable": True, "index": True},
    "session_id": {"type": String, "nullable": True, "index": True},
    "entity_id": {"type": String, "nullable": True, "index": True},
    "entity_type": {"type": String, "nullable": True, "index": True},
    "content": {"type": JSONB, "nullable": False},
    "metadata": {"type": JSONB, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
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
        "memories": MEMORY_TABLE_SCHEMA,
        "knowledge": KNOWLEDGE_TABLE_SCHEMA,
        "culture": CULTURAL_KNOWLEDGE_TABLE_SCHEMA,
        "versions": VERSIONS_TABLE_SCHEMA,
        "traces": TRACE_TABLE_SCHEMA,
        "components": COMPONENT_TABLE_SCHEMA,
        "component_configs": COMPONENT_CONFIGS_TABLE_SCHEMA,
        "component_links": COMPONENT_LINKS_TABLE_SCHEMA,
        "learnings": LEARNINGS_TABLE_SCHEMA,
        "schedules": SCHEDULE_TABLE_SCHEMA,
        "schedule_runs": SCHEDULE_RUNS_TABLE_SCHEMA,
        "approvals": APPROVAL_TABLE_SCHEMA,
    }

    schema = schemas.get(table_type, {})
    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema  # type: ignore[return-value]
