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


# ---------------------------------------------------------------------------
# Lineage fields on RunSchema / TeamRunSchema — surfaced through GET /runs so
# the FE can render fork / regenerate / branch-session relationships.
# ---------------------------------------------------------------------------


def test_run_schema_round_trips_lineage_fields():
    """All five lineage fields on RunOutput must survive serialization through
    RunSchema.from_dict — otherwise GET /runs silently drops them."""
    from agno.os.schema import RunSchema

    run_dict = {
        "run_id": "child",
        "agent_id": "a1",
        "status": "COMPLETED",
        "content": "hi",
        "forked_from_run_id": "parent-run",
        "forked_from_message_index": 5,
        "forked_from_session_id": "parent-session",
        "regenerated_from": "regen-parent",
        "last_checkpoint_at_message_index": 4,
    }

    schema = RunSchema.from_dict(run_dict)

    assert schema.forked_from_run_id == "parent-run"
    assert schema.forked_from_message_index == 5
    assert schema.forked_from_session_id == "parent-session"
    assert schema.regenerated_from == "regen-parent"
    assert schema.last_checkpoint_at_message_index == 4


def test_run_schema_lineage_defaults_to_none_when_absent():
    """Plain non-forked runs shouldn't have spurious lineage values set."""
    from agno.os.schema import RunSchema

    schema = RunSchema.from_dict({"run_id": "solo", "agent_id": "a1", "status": "COMPLETED"})

    assert schema.forked_from_run_id is None
    assert schema.forked_from_message_index is None
    assert schema.forked_from_session_id is None
    assert schema.regenerated_from is None
    assert schema.last_checkpoint_at_message_index is None


def test_team_run_schema_round_trips_lineage_fields():
    from agno.os.schema import TeamRunSchema

    run_dict = {
        "run_id": "child-team",
        "team_id": "t1",
        "status": "COMPLETED",
        "content": "hi",
        "forked_from_run_id": "parent-team",
        "forked_from_message_index": 3,
        "forked_from_session_id": "parent-team-session",
        "regenerated_from": "regen-parent-team",
        "last_checkpoint_at_message_index": 2,
    }

    schema = TeamRunSchema.from_dict(run_dict)

    assert schema.forked_from_run_id == "parent-team"
    assert schema.forked_from_message_index == 3
    assert schema.forked_from_session_id == "parent-team-session"
    assert schema.regenerated_from == "regen-parent-team"
    assert schema.last_checkpoint_at_message_index == 2


def test_team_run_schema_lineage_defaults_to_none_when_absent():
    from agno.os.schema import TeamRunSchema

    schema = TeamRunSchema.from_dict({"run_id": "solo-team", "team_id": "t1", "status": "COMPLETED"})

    assert schema.forked_from_run_id is None
    assert schema.forked_from_message_index is None
    assert schema.forked_from_session_id is None
    assert schema.regenerated_from is None
    assert schema.last_checkpoint_at_message_index is None
