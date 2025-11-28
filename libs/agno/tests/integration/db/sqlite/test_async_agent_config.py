"""Integration tests for Agent and Config versioning methods of the AsyncSqliteDb class"""

import pytest

from agno.agent import Agent
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIChat


@pytest.fixture(autouse=True)
async def cleanup_agents_and_configs(async_sqlite_db_real: AsyncSqliteDb):
    """Fixture to clean up agent and config rows after each test"""
    yield

    async with async_sqlite_db_real.async_session_factory() as session:
        try:
            configs_table = await async_sqlite_db_real._get_table("configs")
            if configs_table is not None:
                await session.execute(configs_table.delete())
            
            agents_table = await async_sqlite_db_real._get_table("agents")
            if agents_table is not None:
                await session.execute(agents_table.delete())
            
            await session.commit()
        except Exception:
            await session.rollback()


@pytest.fixture
def sample_agent() -> Agent:
    """Fixture returning a sample Agent"""
    return Agent(
        id="test-agent-1",
        name="Test Agent",
        description="A test agent for integration tests",
        model=OpenAIChat(id="gpt-4"),
    )


# ============================================================================
# Agent Creation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_new_agent_default_version(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test creating a new agent without specifying a version (should default to v1.0)"""
    result = await async_sqlite_db_real.upsert_agent(sample_agent)
    
    assert result is not None
    assert result.id == sample_agent.id
    assert result.name == sample_agent.name
    
    # Verify agent record was created with v1.0 as current_version
    agents_table = await async_sqlite_db_real._get_table("agents")
    async with async_sqlite_db_real.async_session_factory() as sess:
        from sqlalchemy import select
        stmt = select(agents_table).where(agents_table.c.agent_id == sample_agent.id)
        result = await sess.execute(stmt)
        agent_row = result.fetchone()
        
        assert agent_row is not None
        assert agent_row.current_version == "v1.0"
        assert agent_row.deleted_at is None
    
    # Verify config was created
    config = await async_sqlite_db_real.get_config(sample_agent.id, "v1.0")
    assert config is not None
    assert config["entity_id"] == sample_agent.id
    assert config["entity_type"] == "agent"
    assert config["version"] == "v1.0"
    assert config["notes"] == "Initial version"


@pytest.mark.asyncio
async def test_create_new_agent_custom_version(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test creating a new agent with a custom version"""
    result = await async_sqlite_db_real.upsert_agent(sample_agent, version="v2.5")
    
    assert result is not None
    
    # Verify agent was created with custom version as current
    agents_table = await async_sqlite_db_real._get_table("agents")
    async with async_sqlite_db_real.async_session_factory() as sess:
        from sqlalchemy import select
        stmt = select(agents_table).where(agents_table.c.agent_id == sample_agent.id)
        result = await sess.execute(stmt)
        agent_row = result.fetchone()
        
        assert agent_row is not None
        assert agent_row.current_version == "v2.5"
    
    # Verify config was created with custom version
    config = await async_sqlite_db_real.get_config(sample_agent.id, "v2.5")
    assert config is not None
    assert config["version"] == "v2.5"


# ============================================================================
# Agent Update Tests
# ============================================================================


@pytest.mark.asyncio
async def test_update_existing_agent_no_version(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test updating an existing agent without specifying version (should update current_version)"""
    # Create agent first
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    # Update agent
    sample_agent.description = "Updated description"
    result = await async_sqlite_db_real.upsert_agent(sample_agent)
    
    assert result is not None
    assert result.description == "Updated description"
    
    # Verify the v1.0 config was updated
    config = await async_sqlite_db_real.get_config(sample_agent.id, "v1.0")
    assert config is not None
    agent_config = config["config"]
    assert agent_config["description"] == "Updated description"


@pytest.mark.asyncio
async def test_update_existing_agent_new_version(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test creating a new version of an existing agent"""
    # Create agent first
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    # Create new version
    sample_agent.description = "Version 2 description"
    result = await async_sqlite_db_real.upsert_agent(sample_agent, version="v2.0")
    
    assert result is not None
    
    # Verify v1.0 still exists and unchanged
    config_v1 = await async_sqlite_db_real.get_config(sample_agent.id, "v1.0")
    assert config_v1 is not None
    assert config_v1["config"]["description"] == "A test agent for integration tests"
    
    # Verify v2.0 was created
    config_v2 = await async_sqlite_db_real.get_config(sample_agent.id, "v2.0")
    assert config_v2 is not None
    assert config_v2["config"]["description"] == "Version 2 description"
    
    # Verify current_version is still v1.0 (not changed)
    agents_table = await async_sqlite_db_real._get_table("agents")
    async with async_sqlite_db_real.async_session_factory() as sess:
        from sqlalchemy import select
        stmt = select(agents_table).where(agents_table.c.agent_id == sample_agent.id)
        result = await sess.execute(stmt)
        agent_row = result.fetchone()
        assert agent_row.current_version == "v1.0"


@pytest.mark.asyncio
async def test_update_agent_no_current_version_set(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test updating an agent that has no current_version set (edge case)"""
    # Create agent first
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    # Manually clear current_version to simulate edge case
    agents_table = await async_sqlite_db_real._get_table("agents")
    async with async_sqlite_db_real.async_session_factory() as sess:
        stmt = agents_table.update().where(
            agents_table.c.agent_id == sample_agent.id
        ).values(current_version=None)
        await sess.execute(stmt)
        await sess.commit()
    
    # Update agent without version
    sample_agent.description = "Updated without version"
    result = await async_sqlite_db_real.upsert_agent(sample_agent)
    
    assert result is not None
    
    # Should create v1.0 and set as current
    agents_table = await async_sqlite_db_real._get_table("agents")
    async with async_sqlite_db_real.async_session_factory() as sess:
        from sqlalchemy import select
        stmt = select(agents_table).where(agents_table.c.agent_id == sample_agent.id)
        result = await sess.execute(stmt)
        agent_row = result.fetchone()
        assert agent_row.current_version == "v1.0"


# ============================================================================
# Agent Retrieval Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_agent_default_version(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test getting an agent without specifying version (should use current_version)"""
    # Create agent
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    # Get agent without version
    retrieved_agent = await async_sqlite_db_real.get_agent(sample_agent.id)
    
    assert retrieved_agent is not None
    assert isinstance(retrieved_agent, Agent)
    assert retrieved_agent.id == sample_agent.id
    assert retrieved_agent.name == sample_agent.name
    assert retrieved_agent.description == sample_agent.description


@pytest.mark.asyncio
async def test_get_agent_specific_version(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test getting a specific version of an agent"""
    # Create agent
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    # Create v2.0
    sample_agent.description = "Version 2"
    await async_sqlite_db_real.upsert_agent(sample_agent, version="v2.0")
    
    # Get v1.0 explicitly
    agent_v1 = await async_sqlite_db_real.get_agent(sample_agent.id, version="v1.0")
    assert agent_v1 is not None
    assert agent_v1.description == "A test agent for integration tests"
    
    # Get v2.0 explicitly
    agent_v2 = await async_sqlite_db_real.get_agent(sample_agent.id, version="v2.0")
    assert agent_v2 is not None
    assert agent_v2.description == "Version 2"
    
    # Get without version (should return v1.0 as it's current)
    agent_current = await async_sqlite_db_real.get_agent(sample_agent.id)
    assert agent_current is not None
    assert agent_current.description == "A test agent for integration tests"


@pytest.mark.asyncio
async def test_get_agent_nonexistent(async_sqlite_db_real: AsyncSqliteDb):
    """Test getting an agent that doesn't exist"""
    result = await async_sqlite_db_real.get_agent("nonexistent-agent")
    assert result is None


@pytest.mark.asyncio
async def test_get_agent_nonexistent_version(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test getting a version that doesn't exist"""
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    result = await async_sqlite_db_real.get_agent(sample_agent.id, version="v99.0")
    assert result is None


# ============================================================================
# Agent Version Management Tests
# ============================================================================


@pytest.mark.asyncio
async def test_set_agent_config_version(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test setting the current_version pointer for an agent"""
    # Create agent with multiple versions
    await async_sqlite_db_real.upsert_agent(sample_agent)
    sample_agent.description = "Version 2"
    await async_sqlite_db_real.upsert_agent(sample_agent, version="v2.0")
    
    # Switch to v2.0
    success = await async_sqlite_db_real.set_agent_config_version(sample_agent.id, "v2.0")
    assert success is True
    
    # Verify current_version was updated
    agents_table = await async_sqlite_db_real._get_table("agents")
    async with async_sqlite_db_real.async_session_factory() as sess:
        from sqlalchemy import select
        stmt = select(agents_table).where(agents_table.c.agent_id == sample_agent.id)
        result = await sess.execute(stmt)
        agent_row = result.fetchone()
        assert agent_row.current_version == "v2.0"
    
    # Verify get_agent now returns v2.0 by default
    agent = await async_sqlite_db_real.get_agent(sample_agent.id)
    assert agent is not None
    assert agent.description == "Version 2"


@pytest.mark.asyncio
async def test_set_agent_config_version_nonexistent_agent(async_sqlite_db_real: AsyncSqliteDb):
    """Test setting version for a nonexistent agent"""
    success = await async_sqlite_db_real.set_agent_config_version("nonexistent-agent", "v1.0")
    assert success is False


# ============================================================================
# Agent Deletion Tests
# ============================================================================


@pytest.mark.asyncio
async def test_delete_agent_soft_delete(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test soft deleting an agent (sets deleted_at timestamp)"""
    # Create agent
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    # Delete agent
    success = await async_sqlite_db_real.delete_agent(sample_agent.id)
    assert success is True
    
    # Verify agent is soft deleted
    agents_table = await async_sqlite_db_real._get_table("agents")
    async with async_sqlite_db_real.async_session_factory() as sess:
        from sqlalchemy import select
        stmt = select(agents_table).where(agents_table.c.agent_id == sample_agent.id)
        result = await sess.execute(stmt)
        agent_row = result.fetchone()
        
        assert agent_row is not None  # Row still exists
        assert agent_row.deleted_at is not None  # But has deleted_at timestamp
    
    # Verify get_agent returns None for deleted agent
    agent = await async_sqlite_db_real.get_agent(sample_agent.id)
    assert agent is None


@pytest.mark.asyncio
async def test_delete_agent_nonexistent(async_sqlite_db_real: AsyncSqliteDb):
    """Test deleting a nonexistent agent"""
    success = await async_sqlite_db_real.delete_agent("nonexistent-agent")
    assert success is False


# ============================================================================
# Config CRUD Tests
# ============================================================================


@pytest.mark.asyncio
async def test_upsert_config_create(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test creating a new config"""
    config_data = sample_agent.to_dict()
    
    result = await async_sqlite_db_real.upsert_config(
        entity_id="test-entity",
        entity_type="agent",
        version="v1.0",
        config=config_data,
        notes="Test config"
    )
    
    assert result is not None
    assert result["entity_id"] == "test-entity"
    assert result["entity_type"] == "agent"
    assert result["version"] == "v1.0"
    assert result["notes"] == "Test config"
    assert result["config"] == config_data


@pytest.mark.asyncio
async def test_upsert_config_update(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test updating an existing config"""
    config_data_v1 = {"key": "value1"}
    
    # Create initial config
    await async_sqlite_db_real.upsert_config(
        entity_id="test-entity",
        entity_type="agent",
        version="v1.0",
        config=config_data_v1,
        notes="Initial"
    )
    
    # Update config
    config_data_v2 = {"key": "value2", "new_key": "new_value"}
    result = await async_sqlite_db_real.upsert_config(
        entity_id="test-entity",
        entity_type="agent",
        version="v1.0",
        config=config_data_v2,
        notes="Updated"
    )
    
    assert result is not None
    assert result["config"] == config_data_v2
    assert result["notes"] == "Updated"


@pytest.mark.asyncio
async def test_upsert_config_with_set_as_current(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test creating a config and setting it as current for an agent"""
    # Create agent first
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    # Create new version and set as current
    config_data = sample_agent.to_dict()
    config_data["description"] = "Version 3"
    
    result = await async_sqlite_db_real.upsert_config(
        entity_id=sample_agent.id,
        entity_type="agent",
        version="v3.0",
        config=config_data,
        notes="Version 3",
        set_as_current=True
    )
    
    assert result is not None
    
    # Verify current_version was updated
    agents_table = await async_sqlite_db_real._get_table("agents")
    async with async_sqlite_db_real.async_session_factory() as sess:
        from sqlalchemy import select
        stmt = select(agents_table).where(agents_table.c.agent_id == sample_agent.id)
        result = await sess.execute(stmt)
        agent_row = result.fetchone()
        assert agent_row.current_version == "v3.0"


@pytest.mark.asyncio
async def test_upsert_config_different_entity_types(async_sqlite_db_real: AsyncSqliteDb):
    """Test creating configs for different entity types (agent, team, workflow)"""
    # Agent config
    agent_config = await async_sqlite_db_real.upsert_config(
        entity_id="agent-1",
        entity_type="agent",
        version="v1.0",
        config={"type": "agent"},
    )
    assert agent_config is not None
    assert agent_config["entity_type"] == "agent"
    
    # Team config
    team_config = await async_sqlite_db_real.upsert_config(
        entity_id="team-1",
        entity_type="team",
        version="v1.0",
        config={"type": "team"},
    )
    assert team_config is not None
    assert team_config["entity_type"] == "team"
    
    # Workflow config
    workflow_config = await async_sqlite_db_real.upsert_config(
        entity_id="workflow-1",
        entity_type="workflow",
        version="v1.0",
        config={"type": "workflow"},
    )
    assert workflow_config is not None
    assert workflow_config["entity_type"] == "workflow"


@pytest.mark.asyncio
async def test_get_config(async_sqlite_db_real: AsyncSqliteDb):
    """Test retrieving a config"""
    config_data = {"key": "value"}
    
    # Create config
    await async_sqlite_db_real.upsert_config(
        entity_id="test-entity",
        entity_type="agent",
        version="v1.0",
        config=config_data,
    )
    
    # Get config
    result = await async_sqlite_db_real.get_config("test-entity", "v1.0")
    
    assert result is not None
    assert result["entity_id"] == "test-entity"
    assert result["version"] == "v1.0"
    assert result["config"] == config_data


@pytest.mark.asyncio
async def test_get_config_nonexistent(async_sqlite_db_real: AsyncSqliteDb):
    """Test getting a nonexistent config"""
    result = await async_sqlite_db_real.get_config("nonexistent-entity", "v1.0")
    assert result is None


@pytest.mark.asyncio
async def test_delete_config(async_sqlite_db_real: AsyncSqliteDb):
    """Test deleting a config"""
    # Create config
    await async_sqlite_db_real.upsert_config(
        entity_id="test-entity",
        entity_type="agent",
        version="v1.0",
        config={"key": "value"},
    )
    
    # Verify it exists
    config = await async_sqlite_db_real.get_config("test-entity", "v1.0")
    assert config is not None
    
    # Delete config
    success = await async_sqlite_db_real.delete_config("test-entity", "v1.0")
    assert success is True
    
    # Verify it's gone
    config = await async_sqlite_db_real.get_config("test-entity", "v1.0")
    assert config is None


@pytest.mark.asyncio
async def test_delete_config_nonexistent(async_sqlite_db_real: AsyncSqliteDb):
    """Test deleting a nonexistent config"""
    success = await async_sqlite_db_real.delete_config("nonexistent-entity", "v1.0")
    assert success is False


# ============================================================================
# Integration Workflow Tests
# ============================================================================


@pytest.mark.asyncio
async def test_complete_versioning_workflow(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test a complete workflow of versioning an agent"""
    # 1. Create initial agent (v1.0)
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    # 2. Verify v1.0 is current
    agent = await async_sqlite_db_real.get_agent(sample_agent.id)
    assert agent is not None
    assert agent.description == "A test agent for integration tests"
    
    # 3. Create v2.0 with changes
    sample_agent.description = "Version 2 - Added new features"
    await async_sqlite_db_real.upsert_agent(sample_agent, version="v2.0")
    
    # 4. Create v3.0 with more changes
    sample_agent.description = "Version 3 - Major update"
    await async_sqlite_db_real.upsert_agent(sample_agent, version="v3.0")
    
    # 5. Verify all versions exist
    v1 = await async_sqlite_db_real.get_agent(sample_agent.id, version="v1.0")
    v2 = await async_sqlite_db_real.get_agent(sample_agent.id, version="v2.0")
    v3 = await async_sqlite_db_real.get_agent(sample_agent.id, version="v3.0")
    
    assert v1 is not None and v1.description == "A test agent for integration tests"
    assert v2 is not None and v2.description == "Version 2 - Added new features"
    assert v3 is not None and v3.description == "Version 3 - Major update"
    
    # 6. Current version should still be v1.0
    current = await async_sqlite_db_real.get_agent(sample_agent.id)
    assert current is not None
    assert current.description == "A test agent for integration tests"
    
    # 7. Switch to v3.0
    await async_sqlite_db_real.set_agent_config_version(sample_agent.id, "v3.0")
    
    # 8. Verify current version is now v3.0
    current = await async_sqlite_db_real.get_agent(sample_agent.id)
    assert current is not None
    assert current.description == "Version 3 - Major update"
    
    # 9. Update current version (v3.0) in place
    sample_agent.description = "Version 3 - Updated"
    await async_sqlite_db_real.upsert_agent(sample_agent)
    
    # 10. Verify v3.0 was updated
    current = await async_sqlite_db_real.get_agent(sample_agent.id)
    assert current is not None
    assert current.description == "Version 3 - Updated"
    
    # 11. Verify other versions unchanged
    v1 = await async_sqlite_db_real.get_agent(sample_agent.id, version="v1.0")
    v2 = await async_sqlite_db_real.get_agent(sample_agent.id, version="v2.0")
    assert v1 is not None and v1.description == "A test agent for integration tests"
    assert v2 is not None and v2.description == "Version 2 - Added new features"


@pytest.mark.asyncio
async def test_multiple_agents_with_versions(async_sqlite_db_real: AsyncSqliteDb):
    """Test managing multiple agents with different versions"""
    # Create multiple agents
    agent1 = Agent(id="agent-1", name="Agent 1", model=OpenAIChat(id="gpt-4"))
    agent2 = Agent(id="agent-2", name="Agent 2", model=OpenAIChat(id="gpt-4"))
    
    # Create both agents
    await async_sqlite_db_real.upsert_agent(agent1)
    await async_sqlite_db_real.upsert_agent(agent2)
    
    # Create multiple versions for agent1
    agent1.description = "Agent 1 v2"
    await async_sqlite_db_real.upsert_agent(agent1, version="v2.0")
    
    # Create one version for agent2
    agent2.description = "Agent 2 v2"
    await async_sqlite_db_real.upsert_agent(agent2, version="v2.0")
    
    # Verify isolation
    a1_v1 = await async_sqlite_db_real.get_agent("agent-1", version="v1.0")
    a1_v2 = await async_sqlite_db_real.get_agent("agent-1", version="v2.0")
    a2_v1 = await async_sqlite_db_real.get_agent("agent-2", version="v1.0")
    a2_v2 = await async_sqlite_db_real.get_agent("agent-2", version="v2.0")
    
    assert a1_v1 is not None and a1_v1.description is None
    assert a1_v2 is not None and a1_v2.description == "Agent 1 v2"
    assert a2_v1 is not None and a2_v1.description is None
    assert a2_v2 is not None and a2_v2.description == "Agent 2 v2"


@pytest.mark.asyncio
async def test_config_timestamps(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test that config timestamps are properly set and updated"""
    import asyncio
    
    # Create config
    result1 = await async_sqlite_db_real.upsert_config(
        entity_id="test-entity",
        entity_type="agent",
        version="v1.0",
        config={"key": "value1"},
    )
    
    assert result1 is not None
    assert result1["created_at"] is not None
    assert result1["updated_at"] is not None
    created_at = result1["created_at"]
    
    # Wait a bit
    await asyncio.sleep(0.1)
    
    # Update config
    result2 = await async_sqlite_db_real.upsert_config(
        entity_id="test-entity",
        entity_type="agent",
        version="v1.0",
        config={"key": "value2"},
    )
    
    assert result2 is not None
    assert result2["created_at"] == created_at  # Should be preserved
    assert result2["updated_at"] != created_at  # Should be updated
    assert result2["updated_at"] > created_at  # Should be newer


# ============================================================================
# Cross-entity Config Tests
# ============================================================================


@pytest.mark.asyncio
async def test_configs_isolated_between_entities(async_sqlite_db_real: AsyncSqliteDb):
    """Test that configs are properly isolated between different entities"""
    # Create configs for different entities with same version
    await async_sqlite_db_real.upsert_config(
        entity_id="agent-1",
        entity_type="agent",
        version="v1.0",
        config={"entity": "agent-1", "data": "agent data"},
    )
    
    await async_sqlite_db_real.upsert_config(
        entity_id="team-1",
        entity_type="team",
        version="v1.0",
        config={"entity": "team-1", "data": "team data"},
    )
    
    await async_sqlite_db_real.upsert_config(
        entity_id="workflow-1",
        entity_type="workflow",
        version="v1.0",
        config={"entity": "workflow-1", "data": "workflow data"},
    )
    
    # Verify each config is unique
    agent_config = await async_sqlite_db_real.get_config("agent-1", "v1.0")
    team_config = await async_sqlite_db_real.get_config("team-1", "v1.0")
    workflow_config = await async_sqlite_db_real.get_config("workflow-1", "v1.0")
    
    assert agent_config is not None
    assert agent_config["config"]["entity"] == "agent-1"
    assert agent_config["entity_type"] == "agent"
    
    assert team_config is not None
    assert team_config["config"]["entity"] == "team-1"
    assert team_config["entity_type"] == "team"
    
    assert workflow_config is not None
    assert workflow_config["config"]["entity"] == "workflow-1"
    assert workflow_config["entity_type"] == "workflow"


@pytest.mark.asyncio
async def test_same_entity_multiple_versions(async_sqlite_db_real: AsyncSqliteDb):
    """Test that the same entity can have multiple version configs"""
    entity_id = "multi-version-agent"
    
    # Create multiple versions
    versions = ["v1.0", "v1.1", "v2.0", "v2.1", "v3.0"]
    for version in versions:
        await async_sqlite_db_real.upsert_config(
            entity_id=entity_id,
            entity_type="agent",
            version=version,
            config={"version": version, "data": f"Config for {version}"},
            notes=f"Notes for {version}"
        )
    
    # Verify all versions exist and are independent
    for version in versions:
        config = await async_sqlite_db_real.get_config(entity_id, version)
        assert config is not None
        assert config["version"] == version
        assert config["config"]["version"] == version
        assert config["notes"] == f"Notes for {version}"


@pytest.mark.asyncio
async def test_delete_version_doesnt_affect_others(async_sqlite_db_real: AsyncSqliteDb):
    """Test that deleting one version doesn't affect other versions"""
    entity_id = "delete-test-agent"
    
    # Create multiple versions
    await async_sqlite_db_real.upsert_config(
        entity_id=entity_id,
        entity_type="agent",
        version="v1.0",
        config={"version": "v1.0"},
    )
    await async_sqlite_db_real.upsert_config(
        entity_id=entity_id,
        entity_type="agent",
        version="v2.0",
        config={"version": "v2.0"},
    )
    await async_sqlite_db_real.upsert_config(
        entity_id=entity_id,
        entity_type="agent",
        version="v3.0",
        config={"version": "v3.0"},
    )
    
    # Delete v2.0
    success = await async_sqlite_db_real.delete_config(entity_id, "v2.0")
    assert success is True
    
    # Verify v2.0 is gone
    v2 = await async_sqlite_db_real.get_config(entity_id, "v2.0")
    assert v2 is None
    
    # Verify v1.0 and v3.0 still exist
    v1 = await async_sqlite_db_real.get_config(entity_id, "v1.0")
    v3 = await async_sqlite_db_real.get_config(entity_id, "v3.0")
    assert v1 is not None
    assert v3 is not None


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


@pytest.mark.asyncio
async def test_get_agent_after_soft_delete(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test that get_agent returns None after soft delete"""
    # Create and delete agent
    await async_sqlite_db_real.upsert_agent(sample_agent)
    await async_sqlite_db_real.delete_agent(sample_agent.id)
    
    # Try to get agent
    agent = await async_sqlite_db_real.get_agent(sample_agent.id)
    assert agent is None
    
    # Configs should still exist
    config = await async_sqlite_db_real.get_config(sample_agent.id, "v1.0")
    assert config is not None


@pytest.mark.asyncio
async def test_set_version_on_deleted_agent(async_sqlite_db_real: AsyncSqliteDb, sample_agent: Agent):
    """Test that setting version on a deleted agent fails"""
    # Create and delete agent
    await async_sqlite_db_real.upsert_agent(sample_agent)
    await async_sqlite_db_real.delete_agent(sample_agent.id)
    
    # Try to set version
    success = await async_sqlite_db_real.set_agent_config_version(sample_agent.id, "v1.0")
    assert success is False


@pytest.mark.asyncio
async def test_agent_metadata_preservation(async_sqlite_db_real: AsyncSqliteDb):
    """Test that agent metadata is properly stored and retrieved"""
    agent = Agent(
        id="metadata-test",
        name="Metadata Agent",
        description="Testing metadata",
        model=OpenAIChat(id="gpt-4"),
    )
    
    # Create agent
    await async_sqlite_db_real.upsert_agent(agent)
    
    # Verify agent table has correct metadata
    agents_table = await async_sqlite_db_real._get_table("agents")
    async with async_sqlite_db_real.async_session_factory() as sess:
        from sqlalchemy import select
        stmt = select(agents_table).where(agents_table.c.agent_id == agent.id)
        result = await sess.execute(stmt)
        agent_row = result.fetchone()
        
        assert agent_row is not None
        assert agent_row.agent_name == "Metadata Agent"
        assert agent_row.created_at is not None
        assert agent_row.updated_at is not None


@pytest.mark.asyncio
async def test_config_with_complex_data(async_sqlite_db_real: AsyncSqliteDb):
    """Test that complex config data is properly serialized and deserialized"""
    complex_config = {
        "model": {"id": "gpt-4", "provider": "openai"},
        "tools": [
            {"name": "search", "params": {"engine": "google"}},
            {"name": "calculator", "params": {"precision": 10}},
        ],
        "instructions": ["Be helpful", "Be concise"],
        "metadata": {
            "nested": {
                "deeply": {
                    "nested": "value"
                }
            }
        },
        "numbers": [1, 2, 3, 4, 5],
        "boolean": True,
        "null_value": None,
    }
    
    # Create config with complex data
    result = await async_sqlite_db_real.upsert_config(
        entity_id="complex-test",
        entity_type="agent",
        version="v1.0",
        config=complex_config,
    )
    
    assert result is not None
    
    # Retrieve and verify
    retrieved = await async_sqlite_db_real.get_config("complex-test", "v1.0")
    assert retrieved is not None
    assert retrieved["config"] == complex_config
    assert retrieved["config"]["model"]["id"] == "gpt-4"
    assert len(retrieved["config"]["tools"]) == 2
    assert retrieved["config"]["metadata"]["nested"]["deeply"]["nested"] == "value"

