"""Tests our API schemas handle all expected parsing."""

import json

from agno.os.routers.memory.schemas import UserMemorySchema


def test_user_memory_schema():
    """Test that our UserMemorySchema handle common memory objects."""
    memory_dict = {
        "memory_id": "123",
        "memory": "This is a test memory",
        "topics": ["test", "memory"],
        "user_id": "456",
        "agent_id": "789",
        "team_id": "101",
        "updated_at": 1719859200,
        "created_at": 1719859200,
    }
    user_memory_schema = UserMemorySchema.from_dict(memory_dict)
    assert user_memory_schema is not None
    assert user_memory_schema.memory == "This is a test memory"
    assert user_memory_schema.topics == ["test", "memory"]
    assert user_memory_schema.user_id == "456"
    assert user_memory_schema.agent_id == "789"
    assert user_memory_schema.team_id == "101"


def test_v1_migrated_user_memories():
    """Test that our UserMemorySchema handles v1 migrated memories."""
    memory_dict = {
        "memory_id": "123",
        "user_id": "456",
        "memory": {"memory": "This is a test memory", "other": "other"},
        "input": "This is a test input",
        "updated_at": 1719859200,
    }
    user_memory_schema = UserMemorySchema.from_dict(memory_dict)
    assert user_memory_schema is not None
    assert user_memory_schema.memory == "This is a test memory"


def test_user_memory_schema_complex_memory_content():
    """Test that our UserMemorySchema handles custom, complex memory content."""
    complex_content = {"user_mem": "This is a test memory", "score": "10", "other_fields": "other_fields"}
    memory_dict = {
        "memory_id": "123",
        "user_id": "456",
        "memory": complex_content,
        "input": "This is a test input",
        "updated_at": 1719859200,
    }
    user_memory_schema = UserMemorySchema.from_dict(memory_dict)
    assert user_memory_schema is not None
    assert json.loads(user_memory_schema.memory) == complex_content
    assert user_memory_schema.user_id == "456"
