"""MongoDB collection schemas and related utilities"""

from typing import Any, Dict, List

SESSION_COLLECTION_SCHEMA = [
    {"key": "session_id", "unique": True},
    {"key": "user_id"},
    {"key": "session_type"},
    {"key": "agent_id"},
    {"key": "team_id"},
    {"key": "workflow_id"},
    {"key": "created_at"},
    {"key": "updated_at"},
]

MEMORY_COLLECTION_SCHEMA = [
    {"key": "memory_id", "unique": True},
    {"key": "user_id"},
    {"key": "agent_id"},
    {"key": "team_id"},
    {"key": "topics"},
    {"key": "input"},
    {"key": "feedback"},
    {"key": "created_at"},
    {"key": "updated_at"},
]

EVAL_COLLECTION_SCHEMA = [
    {"key": "run_id", "unique": True},
    {"key": "eval_type"},
    {"key": "eval_input"},
    {"key": "agent_id"},
    {"key": "team_id"},
    {"key": "workflow_id"},
    {"key": "model_id"},
    {"key": "created_at"},
    {"key": "updated_at"},
]

KNOWLEDGE_COLLECTION_SCHEMA = [
    {"key": "id", "unique": True},
    {"key": "name"},
    {"key": "description"},
    {"key": "type"},
    {"key": "status"},
    {"key": "status_message"},
    {"key": "metadata"},
    {"key": "size"},
    {"key": "linked_to"},
    {"key": "access_count"},
    {"key": "created_at"},
    {"key": "updated_at"},
    {"key": "external_id"},
]

METRICS_COLLECTION_SCHEMA = [
    {"key": "id", "unique": True},
    {"key": "date"},
    {"key": "aggregation_period"},
    {"key": "created_at"},
    {"key": "updated_at"},
    {"key": [("date", 1), ("aggregation_period", 1)], "unique": True},
]

CULTURAL_KNOWLEDGE_COLLECTION_SCHEMA = [
    {"key": "id", "unique": True},
    {"key": "name"},
    {"key": "agent_id"},
    {"key": "team_id"},
    {"key": "created_at"},
    {"key": "updated_at"},
]

TRACE_COLLECTION_SCHEMA = [
    {"key": "trace_id", "unique": True},
    {"key": "name"},
    {"key": "status"},
    {"key": "run_id"},
    {"key": "session_id"},
    {"key": "user_id"},
    {"key": "agent_id"},
    {"key": "team_id"},
    {"key": "workflow_id"},
    {"key": "start_time"},
    {"key": "end_time"},
    {"key": "created_at"},
]

SPAN_COLLECTION_SCHEMA = [
    {"key": "span_id", "unique": True},
    {"key": "trace_id"},
    {"key": "parent_span_id"},
    {"key": "name"},
    {"key": "span_kind"},
    {"key": "status_code"},
    {"key": "start_time"},
    {"key": "end_time"},
    {"key": "created_at"},
]

LEARNINGS_COLLECTION_SCHEMA = [
    {"key": "learning_id", "unique": True},
    {"key": "learning_type"},
    {"key": "namespace"},
    {"key": "user_id"},
    {"key": "agent_id"},
    {"key": "team_id"},
    {"key": "workflow_id"},
    {"key": "session_id"},
    {"key": "entity_id"},
    {"key": "entity_type"},
    {"key": "created_at"},
    {"key": "updated_at"},
]


def get_collection_indexes(collection_type: str) -> List[Dict[str, Any]]:
    """Get the index definitions for a specific collection type."""
    index_definitions = {
        "sessions": SESSION_COLLECTION_SCHEMA,
        "memories": MEMORY_COLLECTION_SCHEMA,
        "metrics": METRICS_COLLECTION_SCHEMA,
        "evals": EVAL_COLLECTION_SCHEMA,
        "knowledge": KNOWLEDGE_COLLECTION_SCHEMA,
        "culture": CULTURAL_KNOWLEDGE_COLLECTION_SCHEMA,
        "traces": TRACE_COLLECTION_SCHEMA,
        "spans": SPAN_COLLECTION_SCHEMA,
        "learnings": LEARNINGS_COLLECTION_SCHEMA,
    }

    indexes = index_definitions.get(collection_type)
    if not indexes:
        raise ValueError(f"Unknown collection type: {collection_type}")

    return indexes  # type: ignore[return-value]
