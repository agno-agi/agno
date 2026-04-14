"""Tests our API schemas handle all expected parsing."""

import json

import pytest

from agno.agent import Agent
from agno.knowledge import Knowledge
from agno.os.routers.agents.schema import AgentResponse
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


class _FakeDb:
    """Minimal stand-in for a BaseDb with configurable table names."""

    def __init__(self, id="fake", knowledge_table="agno_knowledge"):
        self.id = id
        self.session_table_name = "agno_sessions"
        self.knowledge_table_name = knowledge_table
        self.memory_table_name = "agno_memory"


@pytest.mark.asyncio
async def test_knowledge_table_from_contents_db():
    """knowledge_table should reflect knowledge.contents_db, not agent.db."""
    knowledge = Knowledge(
        name="Test Knowledge",
        contents_db=_FakeDb(id="custom-db", knowledge_table="custom_knowledge_table"),  # type: ignore[arg-type]
    )
    agent = Agent(name="test-agent", knowledge=knowledge, search_knowledge=True)
    agent.db = _FakeDb(id="agent-db", knowledge_table="agno_knowledge")  # type: ignore[arg-type]

    resp = await AgentResponse.from_agent(agent)

    assert resp.knowledge is not None
    assert resp.knowledge["knowledge_table"] == "custom_knowledge_table"


@pytest.mark.asyncio
async def test_knowledge_table_fallback_to_agent_db():
    """When knowledge.contents_db is None, fall back to agent.db."""
    knowledge = Knowledge(name="Test Knowledge")
    agent = Agent(name="test-agent", knowledge=knowledge, search_knowledge=True)
    agent.db = _FakeDb(id="agent-db", knowledge_table="agent_level_table")  # type: ignore[arg-type]

    resp = await AgentResponse.from_agent(agent)

    assert resp.knowledge is not None
    assert resp.knowledge["knowledge_table"] == "agent_level_table"


@pytest.mark.asyncio
async def test_knowledge_table_none_when_no_knowledge():
    """No knowledge_table when agent has no knowledge."""
    agent = Agent(name="test-agent")

    resp = await AgentResponse.from_agent(agent)

    if resp.knowledge is not None:
        assert resp.knowledge.get("knowledge_table") is None
