"""Firestore collection schemas and related utilities"""

from typing import Any, Dict, List

SESSION_COLLECTION_SCHEMA = [
    {"key": "session_id"},
    {"key": "user_id"},
    {"key": "session_type"},
    {"key": "agent_id"},
    {"key": "team_id"},
    {"key": "workflow_id"},
    {"key": "created_at"},
    {"key": "updated_at"},
    {"key": "session_data.session_name"},
    # Composite indexes for get_sessions queries with sorting
    # These match the actual query patterns: filters + created_at ordering
    {"key": [("session_type", "ASCENDING"), ("created_at", "DESCENDING")], "collection_group": False},
    {
        "key": [("session_type", "ASCENDING"), ("agent_id", "ASCENDING"), ("created_at", "DESCENDING")],
        "collection_group": False,
    },
    {
        "key": [("session_type", "ASCENDING"), ("team_id", "ASCENDING"), ("created_at", "DESCENDING")],
        "collection_group": False,
    },
    {
        "key": [("session_type", "ASCENDING"), ("workflow_id", "ASCENDING"), ("created_at", "DESCENDING")],
        "collection_group": False,
    },
    # For user-specific queries with sorting
    {
        "key": [("user_id", "ASCENDING"), ("session_type", "ASCENDING"), ("created_at", "DESCENDING")],
        "collection_group": False,
    },
    {
        "key": [
            ("user_id", "ASCENDING"),
            ("session_type", "ASCENDING"),
            ("agent_id", "ASCENDING"),
            ("created_at", "DESCENDING"),
        ],
        "collection_group": False,
    },
    {
        "key": [
            ("user_id", "ASCENDING"),
            ("session_type", "ASCENDING"),
            ("team_id", "ASCENDING"),
            ("created_at", "DESCENDING"),
        ],
        "collection_group": False,
    },
    {
        "key": [
            ("user_id", "ASCENDING"),
            ("session_type", "ASCENDING"),
            ("workflow_id", "ASCENDING"),
            ("created_at", "DESCENDING"),
        ],
        "collection_group": False,
    },
]

USER_MEMORY_COLLECTION_SCHEMA = [
    {"key": "memory_id", "unique": True},
    {"key": "user_id"},
    {"key": "agent_id"},
    {"key": "team_id"},
    {"key": "topics"},
    {"key": "updated_at"},
    # Composite indexes for memory queries
    {"key": [("user_id", "ASCENDING"), ("agent_id", "ASCENDING")], "collection_group": False},
    {"key": [("user_id", "ASCENDING"), ("team_id", "ASCENDING")], "collection_group": False},
    {"key": [("user_id", "ASCENDING"), ("workflow_id", "ASCENDING")], "collection_group": False},
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
    # Composite index for metrics uniqueness (same as MongoDB)
    {"key": [("date", "ASCENDING"), ("aggregation_period", "ASCENDING")], "collection_group": False, "unique": True},
]


def get_collection_indexes(collection_type: str) -> List[Dict[str, Any]]:
    """Get the index definitions for a specific collection type."""
    index_definitions = {
        "sessions": SESSION_COLLECTION_SCHEMA,
        "memories": USER_MEMORY_COLLECTION_SCHEMA,
        "metrics": METRICS_COLLECTION_SCHEMA,
        "evals": EVAL_COLLECTION_SCHEMA,
        "knowledge": KNOWLEDGE_COLLECTION_SCHEMA,
    }

    indexes = index_definitions.get(collection_type)
    if not indexes:
        raise ValueError(f"Unknown collection type: {collection_type}")

    return indexes  # type: ignore
