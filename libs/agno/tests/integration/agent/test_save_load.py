"""Integration tests for Agent save() and load() methods"""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat


@pytest.fixture
def sample_agent(shared_db):
    """Create a sample agent with db for testing."""
    return Agent(
        id="test-agent-save-load",
        name="Test Agent",
        description="A test agent for save/load tests",
        model=OpenAIChat(id="gpt-4o"),
        instructions="You are a helpful assistant",
        markdown=True,
        db=shared_db,
    )


# ============================================================================
# Save Tests
# ============================================================================


def test_save_basic(sample_agent):
    """Test basic save() without version (should default to v1.0)."""
    # Save the agent
    saved_agent = sample_agent.save()
    
    assert saved_agent is not None
    assert saved_agent.id == sample_agent.id
    assert saved_agent.name == sample_agent.name
    assert saved_agent.description == sample_agent.description
    
    # Verify the agent was saved to the database
    loaded_agent = sample_agent.load()
    assert loaded_agent is not None
    assert loaded_agent.id == sample_agent.id
    assert loaded_agent.name == sample_agent.name
    assert loaded_agent.description == sample_agent.description


def test_save_with_version(sample_agent):
    """Test save() with a specific version."""
    # Save with custom version
    saved_agent = sample_agent.save(version="v2.5")
    
    assert saved_agent is not None
    assert saved_agent.id == sample_agent.id
    
    # Verify the agent was saved with the specified version
    loaded_agent = sample_agent.load(version="v2.5")
    assert loaded_agent is not None
    assert loaded_agent.id == sample_agent.id
    assert loaded_agent.version == "v2.5"


def test_save_updates_existing(sample_agent):
    """Test that save() updates an existing agent configuration."""
    # Save initial version
    sample_agent.save()
    
    # Modify agent
    sample_agent.description = "Updated description"
    sample_agent.name = "Updated Name"
    
    # Save again (should update v1.0)
    saved_agent = sample_agent.save()
    
    assert saved_agent.description == "Updated description"
    assert saved_agent.name == "Updated Name"
    
    # Verify the update was persisted
    loaded_agent = sample_agent.load()
    assert loaded_agent.description == "Updated description"
    assert loaded_agent.name == "Updated Name"


def test_save_without_db():
    """Test that save() raises ValueError when db is not set."""
    agent = Agent(
        id="no-db-agent",
        model=OpenAIChat(id="gpt-4o"),
    )
    
    with pytest.raises(ValueError, match="Database is not set"):
        agent.save()


# ============================================================================
# Load Tests
# ============================================================================


def test_load_default_version(sample_agent):
    """Test load() without version (should load current_version)."""
    # Save agent first
    sample_agent.save()
    
    # Load without version
    loaded_agent = sample_agent.load()
    
    assert loaded_agent is not None
    assert loaded_agent.id == sample_agent.id
    assert loaded_agent.name == sample_agent.name
    assert loaded_agent.description == sample_agent.description
    assert loaded_agent.version == "v1.0"


def test_load_specific_version(sample_agent):
    """Test load() with a specific version."""
    # Save multiple versions
    sample_agent.save(version="v1.0")
    sample_agent.description = "Version 2 description"
    sample_agent.save(version="v2.0")
    
    # Load v1.0
    agent_v1 = sample_agent.load(version="v1.0")
    assert agent_v1 is not None
    assert agent_v1.description == "A test agent for save/load tests"
    assert agent_v1.version == "v1.0"
    
    # Load v2.0
    agent_v2 = sample_agent.load(version="v2.0")
    assert agent_v2 is not None
    assert agent_v2.description == "Version 2 description"
    assert agent_v2.version == "v2.0"


def test_load_nonexistent_agent(sample_agent):
    """Test load() for an agent that doesn't exist."""
    # Try to load an agent that was never saved
    loaded_agent = sample_agent.load()
    assert loaded_agent is None


def test_load_nonexistent_version(sample_agent):
    """Test load() for a version that doesn't exist."""
    # Save agent with v1.0
    sample_agent.save(version="v1.0")
    
    # Try to load a non-existent version
    loaded_agent = sample_agent.load(version="v99.0")
    assert loaded_agent is None


def test_load_without_db():
    """Test that load() raises ValueError when db is not set."""
    agent = Agent(
        id="no-db-agent",
        model=OpenAIChat(id="gpt-4o"),
    )
    
    with pytest.raises(ValueError, match="Database is not set"):
        agent.load()


# ============================================================================
# Round Trip Tests
# ============================================================================


def test_save_load_round_trip(sample_agent):
    """Test complete save and load round trip."""
    # Set various attributes
    sample_agent.instructions = "Be helpful and concise"
    sample_agent.markdown = True
    sample_agent.add_datetime_to_context = True
    sample_agent.tool_call_limit = 5
    
    # Save
    saved_agent = sample_agent.save()
    assert saved_agent is not None
    
    # Create a new agent instance and load
    new_agent = Agent(
        id=sample_agent.id,
        model=OpenAIChat(id="gpt-4o"),
        db=sample_agent.db,
    )
    loaded_agent = new_agent.load()
    
    assert loaded_agent is not None
    assert loaded_agent.id == sample_agent.id
    assert loaded_agent.instructions == "Be helpful and concise"
    assert loaded_agent.markdown is True
    assert loaded_agent.add_datetime_to_context is True
    assert loaded_agent.tool_call_limit == 5


def test_save_load_multiple_versions(sample_agent):
    """Test saving and loading multiple versions."""
    # Save v1.0
    sample_agent.instructions = "Version 1 instructions"
    sample_agent.save(version="v1.0")
    
    # Save v2.0 with different instructions
    sample_agent.instructions = "Version 2 instructions"
    sample_agent.save(version="v2.0")
    
    # Save v3.0 with different instructions
    sample_agent.instructions = "Version 3 instructions"
    sample_agent.save(version="v3.0")
    
    # Load each version and verify
    agent_v1 = sample_agent.load(version="v1.0")
    assert agent_v1.instructions == "Version 1 instructions"
    
    agent_v2 = sample_agent.load(version="v2.0")
    assert agent_v2.instructions == "Version 2 instructions"
    
    agent_v3 = sample_agent.load(version="v3.0")
    assert agent_v3.instructions == "Version 3 instructions"
    
    # Load default (should be v1.0 as current)
    agent_default = sample_agent.load()
    assert agent_default.instructions == "Version 1 instructions"


def test_save_load_with_complex_attributes(sample_agent):
    """Test save and load with complex agent attributes."""
    # Set various complex attributes
    sample_agent.introduction = "Welcome to the test agent"
    sample_agent.user_id = "user-123"
    sample_agent.session_id = "session-456"
    sample_agent.metadata = {"env": "test", "version": "1.0"}
    sample_agent.reasoning = True
    sample_agent.stream = True
    sample_agent.debug_mode = True
    
    # Save
    saved_agent = sample_agent.save()
    assert saved_agent is not None
    
    # Load
    new_agent = Agent(
        id=sample_agent.id,
        model=OpenAIChat(id="gpt-4o"),
        db=sample_agent.db,
    )
    loaded_agent = new_agent.load()
    
    assert loaded_agent is not None
    assert loaded_agent.introduction == "Welcome to the test agent"
    assert loaded_agent.user_id == "user-123"
    assert loaded_agent.session_id == "session-456"
    assert loaded_agent.metadata == {"env": "test", "version": "1.0"}
    assert loaded_agent.reasoning is True
    assert loaded_agent.stream is True
    assert loaded_agent.debug_mode is True

