from __future__ import annotations

from typing import Dict, List, Mapping, Optional

try:
    from sqlalchemy import Column, ForeignKey, Index, MetaData, String, Table, UniqueConstraint
    from sqlalchemy.sql.ddl import CreateTable
    from sqlalchemy.types import JSON, BigInteger, Boolean, Date, Text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

try:  # Prefer JSONB on Postgres while staying dialect agnostic elsewhere.
    from sqlalchemy.dialects.postgresql import JSONB
except Exception:  # pragma: no cover - optional dependency
    JSONB = None  # type: ignore


# Default table names mirror BaseDb defaults.
DEFAULT_TABLE_NAMES: Mapping[str, str] = {
    "sessions": "agno_sessions",
    "memories": "agno_memories",
    "metrics": "agno_metrics",
    "evals": "agno_eval_runs",
    "knowledge": "agno_knowledge",
    "culture": "agno_culture",
    "traces": "agno_traces",
    "spans": "agno_spans",
    "versions": "agno_schema_versions",
}


def _json_type(dialect_name: Optional[str]):
    if JSONB is not None and dialect_name == "postgresql":
        return JSONB()
    return JSON()


def _string(length: Optional[int] = None):
    return String(length) if length is not None else String()


def _build_column_specs(dialect_name: Optional[str]) -> Mapping[str, Dict[str, Dict]]:
    # Column specs are centralized here so every dialect shares the same structure.
    return {
        "sessions": {
            "session_id": {"type": lambda: _string(128), "nullable": False},
            "session_type": {"type": lambda: _string(50), "nullable": False, "index": True},
            "agent_id": {"type": lambda: _string(128), "nullable": True},
            "team_id": {"type": lambda: _string(128), "nullable": True},
            "workflow_id": {"type": lambda: _string(128), "nullable": True},
            "user_id": {"type": lambda: _string(128), "nullable": True},
            "session_data": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "agent_data": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "team_data": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "workflow_data": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "metadata": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "runs": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "summary": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "created_at": {"type": BigInteger, "nullable": False, "index": True},
            "updated_at": {"type": BigInteger, "nullable": True},
            "_unique_constraints": [
                {
                    "name": "uq_session_id",
                    "columns": ["session_id"],
                },
            ],
        },
        "memories": {
            "memory_id": {"type": lambda: _string(128), "primary_key": True, "nullable": False},
            "memory": {"type": lambda: _json_type(dialect_name), "nullable": False},
            "feedback": {"type": Text, "nullable": True},
            "input": {"type": Text, "nullable": True},
            "agent_id": {"type": lambda: _string(128), "nullable": True},
            "team_id": {"type": lambda: _string(128), "nullable": True},
            "user_id": {"type": lambda: _string(128), "nullable": True, "index": True},
            "topics": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "created_at": {"type": BigInteger, "nullable": False, "index": True},
            "updated_at": {"type": BigInteger, "nullable": True, "index": True},
        },
        "evals": {
            "run_id": {"type": lambda: _string(128), "primary_key": True, "nullable": False},
            "eval_type": {"type": lambda: _string(50), "nullable": False},
            "eval_data": {"type": lambda: _json_type(dialect_name), "nullable": False},
            "eval_input": {"type": lambda: _json_type(dialect_name), "nullable": False},
            "name": {"type": lambda: _string(255), "nullable": True},
            "agent_id": {"type": lambda: _string(128), "nullable": True},
            "team_id": {"type": lambda: _string(128), "nullable": True},
            "workflow_id": {"type": lambda: _string(128), "nullable": True},
            "model_id": {"type": lambda: _string(128), "nullable": True},
            "model_provider": {"type": lambda: _string(128), "nullable": True},
            "evaluated_component_name": {"type": lambda: _string(255), "nullable": True},
            "created_at": {"type": BigInteger, "nullable": False, "index": True},
            "updated_at": {"type": BigInteger, "nullable": True},
        },
        "knowledge": {
            "id": {"type": lambda: _string(128), "primary_key": True, "nullable": False},
            "name": {"type": lambda: _string(255), "nullable": False},
            "description": {"type": Text, "nullable": False},
            "metadata": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "type": {"type": lambda: _string(50), "nullable": True},
            "size": {"type": BigInteger, "nullable": True},
            "linked_to": {"type": lambda: _string(128), "nullable": True},
            "access_count": {"type": BigInteger, "nullable": True},
            "status": {"type": lambda: _string(50), "nullable": True},
            "status_message": {"type": Text, "nullable": True},
            "created_at": {"type": BigInteger, "nullable": True},
            "updated_at": {"type": BigInteger, "nullable": True},
            "external_id": {"type": lambda: _string(128), "nullable": True},
        },
        "metrics": {
            "id": {"type": lambda: _string(128), "primary_key": True, "nullable": False},
            "agent_runs_count": {"type": BigInteger, "nullable": False},
            "team_runs_count": {"type": BigInteger, "nullable": False},
            "workflow_runs_count": {"type": BigInteger, "nullable": False},
            "agent_sessions_count": {"type": BigInteger, "nullable": False},
            "team_sessions_count": {"type": BigInteger, "nullable": False},
            "workflow_sessions_count": {"type": BigInteger, "nullable": False},
            "users_count": {"type": BigInteger, "nullable": False},
            "token_metrics": {"type": lambda: _json_type(dialect_name), "nullable": False},
            "model_metrics": {"type": lambda: _json_type(dialect_name), "nullable": False},
            "date": {"type": Date, "nullable": False, "index": True},
            "aggregation_period": {"type": lambda: _string(20), "nullable": False},
            "created_at": {"type": BigInteger, "nullable": False},
            "updated_at": {"type": BigInteger, "nullable": True},
            "completed": {"type": Boolean, "nullable": False},
            "_unique_constraints": [
                {
                    "name": "uq_metrics_date_period",
                    "columns": ["date", "aggregation_period"],
                }
            ],
        },
        "culture": {
            "id": {"type": lambda: _string(128), "primary_key": True, "nullable": False},
            "name": {"type": lambda: _string(255), "nullable": False, "index": True},
            "summary": {"type": Text, "nullable": True},
            "content": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "metadata": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "input": {"type": Text, "nullable": True},
            "created_at": {"type": BigInteger, "nullable": True},
            "updated_at": {"type": BigInteger, "nullable": True},
            "agent_id": {"type": lambda: _string(128), "nullable": True},
            "team_id": {"type": lambda: _string(128), "nullable": True},
        },
        "traces": {
            "trace_id": {"type": lambda: _string(128), "primary_key": True, "nullable": False},
            "name": {"type": lambda: _string(255), "nullable": False},
            "status": {"type": lambda: _string(50), "nullable": False, "index": True},
            "start_time": {"type": lambda: _string(64), "nullable": False, "index": True},
            "end_time": {"type": lambda: _string(64), "nullable": False},
            "duration_ms": {"type": BigInteger, "nullable": False},
            "run_id": {"type": lambda: _string(128), "nullable": True, "index": True},
            "session_id": {"type": lambda: _string(128), "nullable": True, "index": True},
            "user_id": {"type": lambda: _string(128), "nullable": True, "index": True},
            "agent_id": {"type": lambda: _string(128), "nullable": True, "index": True},
            "team_id": {"type": lambda: _string(128), "nullable": True, "index": True},
            "workflow_id": {"type": lambda: _string(128), "nullable": True, "index": True},
            "created_at": {"type": lambda: _string(64), "nullable": False, "index": True},
        },
        "spans": {
            "span_id": {"type": lambda: _string(128), "primary_key": True, "nullable": False},
            "trace_id": {
                "type": lambda: _string(128),
                "nullable": False,
                "index": True,
                "foreign_key": True,
            },
            "parent_span_id": {"type": lambda: _string(128), "nullable": True, "index": True},
            "name": {"type": lambda: _string(255), "nullable": False},
            "span_kind": {"type": lambda: _string(50), "nullable": False},
            "status_code": {"type": lambda: _string(50), "nullable": False},
            "status_message": {"type": Text, "nullable": True},
            "start_time": {"type": lambda: _string(64), "nullable": False, "index": True},
            "end_time": {"type": lambda: _string(64), "nullable": False},
            "duration_ms": {"type": BigInteger, "nullable": False},
            "attributes": {"type": lambda: _json_type(dialect_name), "nullable": True},
            "created_at": {"type": lambda: _string(64), "nullable": False, "index": True},
        },
        "versions": {
            "table_name": {"type": lambda: _string(128), "nullable": False, "primary_key": True},
            "version": {"type": lambda: _string(32), "nullable": False},
            "created_at": {"type": lambda: _string(64), "nullable": False, "index": True},
            "updated_at": {"type": lambda: _string(64), "nullable": True},
        },
    }


def build_agno_metadata(
    schema: Optional[str] = None,
    table_names: Optional[Mapping[str, str]] = None,
    dialect_name: Optional[str] = None,
) -> MetaData:
    """
    Build a SQLAlchemy MetaData object containing all Agno internal tables.

    Args:
        schema: Optional schema/namespace to attach to all tables.
        table_names: Optional mapping overriding default table names keyed by table type.
        dialect_name: Dialect name used to pick the correct column types (e.g., JSON vs JSONB).

    Returns:
        MetaData with all Agno control tables registered.
    """
    names = {**DEFAULT_TABLE_NAMES, **(table_names or {})}
    metadata = MetaData(schema=schema)
    specs = _build_column_specs(dialect_name)

    table_order = ["sessions", "memories", "metrics", "evals", "knowledge", "culture", "traces", "spans", "versions"]
    trace_table_name = names["traces"]

    for table_type in table_order:
        table_name = names[table_type]
        table_schema = specs[table_type]

        columns: List[Column] = []
        indexes: List[str] = []
        schema_unique_constraints = table_schema.get("_unique_constraints", [])

        for col_name, col_config in table_schema.items():
            if col_name.startswith("_"):
                continue

            col_type_factory = col_config["type"]
            col_type = col_type_factory() if callable(col_type_factory) else col_type_factory  # type: ignore
            column_args = [col_name, col_type]
            column_kwargs = {
                "nullable": col_config.get("nullable", True),
                "primary_key": col_config.get("primary_key", False),
                "unique": col_config.get("unique", False),
            }

            if col_config.get("index"):
                indexes.append(col_name)

            if col_config.get("foreign_key"):
                fk_target = f"{trace_table_name}.trace_id"
                if schema:
                    fk_target = f"{schema}.{fk_target}"
                column_args.append(ForeignKey(fk_target))

            columns.append(Column(*column_args, **column_kwargs))  # type: ignore

        table = Table(table_name, metadata, *columns, schema=schema)

        for constraint in schema_unique_constraints:
            constraint_name = f"{table_name}_{constraint['name']}"
            table.append_constraint(UniqueConstraint(*constraint["columns"], name=constraint_name))

        for idx_col in indexes:
            idx_name = f"idx_{table_name}_{idx_col}"
            table.append_constraint(Index(idx_name, idx_col))

    return metadata


def compile_ddl_for_metadata(metadata: MetaData, dialect) -> List[str]:
    """Compile CREATE TABLE statements for the given metadata using the provided dialect."""
    statements: List[str] = []
    for table in metadata.sorted_tables:
        ddl = CreateTable(table).compile(dialect=dialect, compile_kwargs={"literal_binds": True})
        statements.append(str(ddl).strip())
    return statements
