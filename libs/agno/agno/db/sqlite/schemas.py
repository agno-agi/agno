"""Table schemas and related utils used by the SqliteDb class"""

from typing import Any

from agno.db.schemas.mcp_oauth import MCP_OAUTH_TABLE_SCHEMAS

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
    "summary": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
}


def _get_run_table_schema(session_table_name: str = "agno_sessions") -> dict[str, Any]:
    """Runs table schema with ``session_id`` FK → sessions ON DELETE CASCADE.

    SQLite requires ``PRAGMA foreign_keys = ON`` on the connection for the
    constraint to actually enforce — the adapter enables this in its
    connection init hook.
    """
    return {
        "run_id": {"type": String, "primary_key": True, "nullable": False},
        "session_id": {
            "type": String,
            "nullable": False,
            "index": True,
            # Concrete table name (see postgres schemas.py for rationale).
            "foreign_key": f"{session_table_name}.session_id",
            "ondelete": "CASCADE",
        },
        "run_type": {"type": String, "nullable": False, "index": True},
        "agent_id": {"type": String, "nullable": True, "index": True},
        "team_id": {"type": String, "nullable": True, "index": True},
        "workflow_id": {"type": String, "nullable": True, "index": True},
        "user_id": {"type": String, "nullable": True, "index": True},
        "parent_run_id": {"type": String, "nullable": True},
        "status": {"type": String, "nullable": True, "index": True},
        "run_index": {"type": BigInteger, "nullable": True},
        "run_data": {"type": JSON, "nullable": False},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
        "updated_at": {"type": BigInteger, "nullable": True},
        # Composite index so "most recent N runs of a session"
        # (WHERE session_id=? ORDER BY run_index DESC LIMIT N) is index-served.
        "__composite_indexes__": [
            {"name": "agno_runs_session_id_run_index", "columns": ["session_id", "run_index"]},
        ],
    }


USER_MEMORY_TABLE_SCHEMA = {
    "memory_id": {"type": String, "primary_key": True, "nullable": False},
    "memory": {"type": JSON, "nullable": False},
    "input": {"type": String, "nullable": True},
    "agent_id": {"type": String, "nullable": True},
    "team_id": {"type": String, "nullable": True},
    "user_id": {"type": String, "nullable": True, "index": True},
    "topics": {"type": JSON, "nullable": True},
    "feedback": {"type": String, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
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
    "user_id": {"type": String, "nullable": True, "index": True},
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
    # Uploader. NULL means shared: visible to all (legacy and admin uploads).
    "user_id": {"type": String, "nullable": True, "index": True},
    # Composite index so "my content + shared"
    # (WHERE (user_id=? OR user_id IS NULL) AND linked_to=?) is index-served.
    "__composite_indexes__": [
        {"name": "ix_knowledge_user_linked_to", "columns": ["user_id", "linked_to"]},
    ],
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
    # Owner of this metric bucket. Empty string, not NULL, for "no owner":
    # SQL treats multiple NULLs as distinct, which would break the unique constraint below.
    "user_id": {"type": String, "nullable": False, "default": "", "index": True},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": True},
    "completed": {"type": Boolean, "nullable": False, "default": False},
    "_unique_constraints": [
        {
            "name": "uq_metrics_user_date_period",
            "columns": ["user_id", "date", "aggregation_period"],
        }
    ],
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


def _get_span_table_schema(traces_table_name: str = "agno_traces") -> dict[str, Any]:
    """Get the span table schema with the correct foreign key reference.

    Args:
        traces_table_name: The name of the traces table to reference in the foreign key.

    Returns:
        The span table schema dictionary.
    """
    return {
        "span_id": {"type": String, "primary_key": True, "nullable": False},
        "trace_id": {
            "type": String,
            "nullable": False,
            "index": True,
            "foreign_key": f"{traces_table_name}.trace_id",
        },
        "parent_span_id": {"type": String, "nullable": True, "index": True},
        "name": {"type": String, "nullable": False},
        "span_kind": {"type": String, "nullable": False},
        "status_code": {"type": String, "nullable": False},
        "status_message": {"type": String, "nullable": True},
        "start_time": {"type": String, "nullable": False, "index": True},  # ISO 8601 datetime string
        "end_time": {"type": String, "nullable": False},  # ISO 8601 datetime string
        "duration_ms": {"type": BigInteger, "nullable": False},
        "attributes": {"type": JSON, "nullable": True},
        "created_at": {"type": String, "nullable": False, "index": True},  # ISO 8601 datetime string
    }


VERSIONS_TABLE_SCHEMA = {
    "table_name": {"type": String, "nullable": False, "primary_key": True},
    "version": {"type": String, "nullable": False},
    "created_at": {"type": String, "nullable": False, "index": True},
    "updated_at": {"type": String, "nullable": True},
}

COMPONENTS_TABLE_SCHEMA = {
    "component_id": {"type": String, "primary_key": True},
    "component_type": {"type": String, "nullable": False, "index": True},  # agent|team|workflow
    "name": {"type": String, "nullable": False, "index": True},
    "user_id": {"type": String, "nullable": True, "index": True},
    "description": {"type": String, "nullable": True},
    "current_version": {"type": BigInteger, "nullable": True, "index": True},
    "metadata": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "deleted_at": {"type": BigInteger, "nullable": True},
}

COMPONENT_CONFIGS_TABLE_SCHEMA = {
    "component_id": {"type": String, "primary_key": True, "nullable": False},
    "version": {"type": BigInteger, "primary_key": True, "nullable": False},
    "label": {"type": String, "nullable": True},  # stable|v1.2.0|pre-refactor
    "stage": {"type": String, "nullable": False, "default": "draft", "index": True},  # draft|published
    "config": {"type": JSON, "nullable": False},
    "notes": {"type": String, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
}

COMPONENT_LINKS_TABLE_SCHEMA = {
    "parent_component_id": {"type": String, "primary_key": True, "nullable": False},
    "parent_version": {"type": BigInteger, "primary_key": True, "nullable": False},
    "link_kind": {"type": String, "primary_key": True, "nullable": False, "index": True},
    "link_key": {"type": String, "primary_key": True, "nullable": False},
    "child_component_id": {"type": String, "nullable": False},
    "child_version": {"type": BigInteger, "nullable": True},
    "position": {"type": BigInteger, "nullable": False},
    "meta": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": True, "index": True},
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
    "content": {"type": JSON, "nullable": False},
    "metadata": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
}


SCHEDULE_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "name": {"type": String, "nullable": False, "index": True},
    "description": {"type": String, "nullable": True},
    "method": {"type": String, "nullable": False},
    "endpoint": {"type": String, "nullable": False},
    "payload": {"type": JSON, "nullable": True},
    "cron_expr": {"type": String, "nullable": False},
    "timezone": {"type": String, "nullable": False},
    "timeout_seconds": {"type": BigInteger, "nullable": False},
    "max_retries": {"type": BigInteger, "nullable": False},
    "retry_delay_seconds": {"type": BigInteger, "nullable": False},
    "enabled": {"type": Boolean, "nullable": False, "default": True},
    "next_run_at": {"type": BigInteger, "nullable": True, "index": True},
    "locked_by": {"type": String, "nullable": True},
    "locked_at": {"type": BigInteger, "nullable": True},
    # Owner. NULL means system-created: executor, migrations, legacy rows.
    "user_id": {"type": String, "nullable": True, "index": True},
    # Which control plane manages this row ("studio" for builder-created ones)
    # plus the exact component target and writing-run provenance. Nullable so
    # legacy rows need only the ALTERs in the v3 migration.
    "managed_by": {"type": String, "nullable": True, "index": True},
    "target_type": {"type": String, "nullable": True},
    "target_id": {"type": String, "nullable": True, "index": True},
    "created_by_run_id": {"type": String, "nullable": True},
    "created_by_session_id": {"type": String, "nullable": True},
    "updated_by_run_id": {"type": String, "nullable": True},
    "updated_by_session_id": {"type": String, "nullable": True},
    "disabled_reason": {"type": String, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "__composite_indexes__": [
        {"name": "enabled_next_run_at", "columns": ["enabled", "next_run_at"]},
        # Serves the "my active schedules" list read.
        {"name": "user_enabled_next_run_at", "columns": ["user_id", "enabled", "next_run_at"]},
    ],
    # Names are unique per owner. The router's check-then-insert races under
    # concurrent creates, so the DB backs it with two partial unique indexes
    # (NULLs are distinct in a plain unique constraint, and SQLite cannot drop
    # a table-level constraint, so named partial indexes cover both buckets).
    "_partial_unique_indexes": [
        {"name": "uq_user_name", "columns": ["user_id", "name"], "where": "user_id IS NOT NULL"},
        {"name": "uq_unowned_name", "columns": ["name"], "where": "user_id IS NULL"},
    ],
}

APPROVAL_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "run_id": {"type": String, "nullable": False, "index": True},
    "session_id": {"type": String, "nullable": False, "index": True},
    "status": {"type": String, "nullable": False, "index": True},
    "source_type": {"type": String, "nullable": False, "index": True},
    "approval_type": {"type": String, "nullable": True, "index": True},
    "pause_type": {"type": String, "nullable": False, "index": True},
    "tool_name": {"type": String, "nullable": True},
    "tool_args": {"type": JSON, "nullable": True},
    "expires_at": {"type": BigInteger, "nullable": True},
    "agent_id": {"type": String, "nullable": True, "index": True},
    "team_id": {"type": String, "nullable": True, "index": True},
    "workflow_id": {"type": String, "nullable": True, "index": True},
    "user_id": {"type": String, "nullable": True, "index": True},
    "schedule_id": {"type": String, "nullable": True, "index": True},
    "schedule_run_id": {"type": String, "nullable": True, "index": True},
    "source_name": {"type": String, "nullable": True},
    "requirements": {"type": JSON, "nullable": True},
    "context": {"type": JSON, "nullable": True},
    "resolution_data": {"type": JSON, "nullable": True},
    "resolved_by": {"type": String, "nullable": True},
    "resolved_at": {"type": BigInteger, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    # Run status from the associated run. Updated when run completes/errors/cancels.
    # Values: "PAUSED", "COMPLETED", "RUNNING", "ERROR", "CANCELLED", or None.
    "run_status": {"type": String, "nullable": True, "index": True},
}

AUTH_TOKEN_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "provider": {"type": String, "nullable": False, "index": True},
    # Empty string for single-user mode
    "user_id": {"type": String, "nullable": False, "index": True},
    "service": {"type": String, "nullable": False, "index": True},
    "token_data": {"type": JSON, "nullable": False},
    "granted_scopes": {"type": JSON, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "updated_at": {"type": BigInteger, "nullable": True},
    "_unique_constraints": [
        {"name": "uq_auth_token_provider_user_service", "columns": ["provider", "user_id", "service"]}
    ],
}

SERVICE_ACCOUNT_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "name": {"type": String, "nullable": False},
    # Ownership: the user this account belongs to (created_by is audit: who minted it).
    # NULL means a workspace-level machine account with no owning user.
    "user_id": {"type": String, "nullable": True},
    "token_hash": {"type": String, "nullable": False, "unique": True, "index": True},
    "token_prefix": {"type": String, "nullable": False},
    "scopes": {"type": JSON, "nullable": False},
    "created_at": {"type": BigInteger, "nullable": False, "index": True},
    "expires_at": {"type": BigInteger, "nullable": True},
    "last_used_at": {"type": BigInteger, "nullable": True},
    "revoked_at": {"type": BigInteger, "nullable": True},
    "created_by": {"type": String, "nullable": True},
    # Names are reusable after revocation (rotation keeps the same identity),
    # so uniqueness only applies to active accounts.
    "_partial_unique_indexes": [{"name": "uq_active_name", "columns": ["name"], "where": "revoked_at IS NULL"}],
}


def _get_schedule_runs_table_schema(schedules_table_name: str = "agno_schedules") -> dict[str, Any]:
    """Get the schedule runs table schema with a foreign key to the schedules table."""
    return {
        "id": {"type": String, "primary_key": True, "nullable": False},
        "schedule_id": {
            "type": String,
            "nullable": False,
            "index": True,
            "foreign_key": f"{schedules_table_name}.id",
            "ondelete": "CASCADE",
        },
        "attempt": {"type": BigInteger, "nullable": False},
        "triggered_at": {"type": BigInteger, "nullable": True},
        "completed_at": {"type": BigInteger, "nullable": True},
        "status": {"type": String, "nullable": False, "index": True},
        "status_code": {"type": BigInteger, "nullable": True},
        "run_id": {"type": String, "nullable": True},
        "session_id": {"type": String, "nullable": True},
        "error": {"type": String, "nullable": True},
        "input": {"type": JSON, "nullable": True},
        "output": {"type": JSON, "nullable": True},
        "requirements": {"type": JSON, "nullable": True},
        # Denormalised from agno_schedules.user_id so run reads scope by owner without a JOIN.
        "user_id": {"type": String, "nullable": True, "index": True},
        "created_at": {"type": BigInteger, "nullable": False, "index": True},
    }


TOOL_RESULTS_TABLE_SCHEMA = {
    "result_id": {"type": String, "primary_key": True, "nullable": False},
    "namespace": {"type": String, "nullable": False},
    "path": {"type": String, "nullable": False},
    "session_id": {"type": String, "nullable": False},
    "run_id": {"type": String, "nullable": False},
    "tool_call_id": {"type": String, "nullable": False},
    "tool_name": {"type": String, "nullable": False},
    "args_hash": {"type": String, "nullable": False},
    "content_type": {"type": String, "nullable": False},
    "size_bytes": {"type": BigInteger, "nullable": False},
    "line_count": {"type": BigInteger, "nullable": False},
    "preview": {"type": String, "nullable": False},
    "user_id": {"type": String, "nullable": True},
    "created_at": {"type": BigInteger, "nullable": False},
    "expires_at": {"type": BigInteger, "nullable": True, "index": True},
    "_unique_constraints": [
        # Two result ids must never point at one payload.
        {"name": "uq_tool_results_namespace_path", "columns": ["namespace", "path"]},
    ],
    "__composite_indexes__": [
        # Session cleanup and the newest-first listing.
        {"name": "session_created_at", "columns": ["session_id", "created_at"]},
    ],
}


def get_table_schema_definition(
    table_type: str,
    traces_table_name: str = "agno_traces",
    schedules_table_name: str = "agno_schedules",
    session_table_name: str = "agno_sessions",
) -> dict[str, Any]:
    """
    Get the expected schema definition for the given table.

    Args:
        table_type (str): The type of table to get the schema for.
        traces_table_name (str): The name of the traces table (used for spans foreign key).
        schedules_table_name (str): The name of the schedules table (used for schedule_runs foreign key).
        session_table_name (str): The name of the sessions table (used for the
            runs table's ``session_id`` foreign key).

    Returns:
        Dict[str, Any]: Dictionary containing column definitions for the table
    """
    # Handle tables with dynamic foreign key references
    if table_type == "spans":
        return _get_span_table_schema(traces_table_name)
    if table_type == "schedule_runs":
        return _get_schedule_runs_table_schema(schedules_table_name)
    if table_type == "runs":
        return _get_run_table_schema(session_table_name)

    schemas = {
        "sessions": SESSION_TABLE_SCHEMA,
        # "runs" is handled by _get_run_table_schema above (needs session_table_name)
        "evals": EVAL_TABLE_SCHEMA,
        "metrics": METRICS_TABLE_SCHEMA,
        "memories": USER_MEMORY_TABLE_SCHEMA,
        "knowledge": KNOWLEDGE_TABLE_SCHEMA,
        "traces": TRACE_TABLE_SCHEMA,
        "versions": VERSIONS_TABLE_SCHEMA,
        "components": COMPONENTS_TABLE_SCHEMA,
        "component_configs": COMPONENT_CONFIGS_TABLE_SCHEMA,
        "component_links": COMPONENT_LINKS_TABLE_SCHEMA,
        "learnings": LEARNINGS_TABLE_SCHEMA,
        "schedules": SCHEDULE_TABLE_SCHEMA,
        "tool_results": TOOL_RESULTS_TABLE_SCHEMA,
        "approvals": APPROVAL_TABLE_SCHEMA,
        "auth_tokens": AUTH_TOKEN_TABLE_SCHEMA,
        "service_accounts": SERVICE_ACCOUNT_TABLE_SCHEMA,
        **MCP_OAUTH_TABLE_SCHEMAS,
    }
    schema = schemas.get(table_type, {})

    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema  # type: ignore[return-value]
