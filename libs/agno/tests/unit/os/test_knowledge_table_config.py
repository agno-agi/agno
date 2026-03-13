"""Tests that knowledge_table reflects the Knowledge's contents_db config in AgentResponse.

Covers the fix for https://github.com/agno-agi/agno/issues/6975 where
AgnoOS always displayed knowledge_table as 'agno_knowledge' regardless
of the user's custom Knowledge contents_db configuration.
"""

from types import SimpleNamespace

import pytest

from agno.agent import Agent
from agno.os.routers.agents.schema import AgentResponse


def _make_db(knowledge_table="agno_knowledge", **kwargs):
    """Create a minimal db-like object with knowledge_table_name."""
    return SimpleNamespace(
        id="test-db",
        knowledge_table_name=knowledge_table,
        session_table_name=kwargs.get("session_table", "agno_sessions"),
        memory_table_name=kwargs.get("memory_table", "agno_memories"),
    )


def _make_knowledge(contents_db=None):
    """Create a minimal knowledge-like object."""
    return SimpleNamespace(contents_db=contents_db)


@pytest.mark.asyncio
async def test_knowledge_table_from_custom_contents_db():
    """When Knowledge has a contents_db with a custom knowledge_table,
    AgentResponse should report that table name, not the agent.db default."""
    custom_db = _make_db(knowledge_table="my_custom_knowledge")
    agent = Agent(name="test-agent")
    agent.knowledge = _make_knowledge(contents_db=custom_db)
    agent.db = _make_db()  # default: "agno_knowledge"

    resp = await AgentResponse.from_agent(agent)

    assert resp.knowledge is not None
    assert resp.knowledge["knowledge_table"] == "my_custom_knowledge"


@pytest.mark.asyncio
async def test_knowledge_table_falls_back_to_agent_db():
    """When Knowledge exists but has no contents_db, fall back to agent.db."""
    agent = Agent(name="test-agent")
    agent.knowledge = _make_knowledge(contents_db=None)
    agent.db = _make_db(knowledge_table="agent_level_table")

    resp = await AgentResponse.from_agent(agent)

    assert resp.knowledge is not None
    assert resp.knowledge["knowledge_table"] == "agent_level_table"


@pytest.mark.asyncio
async def test_knowledge_table_none_without_knowledge():
    """When agent has no knowledge, knowledge_table should be None."""
    agent = Agent(name="test-agent")
    agent.knowledge = None
    agent.db = _make_db(knowledge_table="should_not_appear")

    resp = await AgentResponse.from_agent(agent)

    # knowledge section should either be None or have knowledge_table=None
    if resp.knowledge is not None:
        assert resp.knowledge["knowledge_table"] is None


@pytest.mark.asyncio
async def test_knowledge_table_default_when_no_custom_config():
    """When Knowledge has a contents_db with default config, the default table name
    should still be reported correctly (not silently dropped)."""
    default_db = _make_db()  # knowledge_table defaults to "agno_knowledge"
    agent = Agent(name="test-agent")
    agent.knowledge = _make_knowledge(contents_db=default_db)
    agent.db = _make_db()

    resp = await AgentResponse.from_agent(agent)

    assert resp.knowledge is not None
    assert resp.knowledge["knowledge_table"] == "agno_knowledge"
