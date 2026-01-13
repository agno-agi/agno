from agno.agent.agent import Agent
from agno.utils.string import is_valid_uuid


def test_set_id():
    agent = Agent(
        id="test_id",
    )
    agent.set_id()
    assert agent.id == "test_id"


def test_set_id_from_name():
    agent = Agent(
        name="Test Name",
    )
    agent.set_id()

    # Asserting the set_id method uses the name to generate the id
    agent_id = agent.id
    expected_id = "test-name"
    assert expected_id == agent_id

    # Asserting the set_id method is deterministic
    agent.set_id()
    assert agent.id == agent_id


def test_set_id_auto_generated():
    agent = Agent()
    agent.set_id()
    assert is_valid_uuid(agent.id)


def test_deep_copy():
    """Test that Agent.deep_copy() works with all dataclass fields.

    This test ensures that all dataclass fields with defaults are properly
    handled by deep_copy(), preventing TypeError for unexpected keyword arguments.
    """
    # Create agent with minimal configuration
    # The key is that deep_copy will try to pass ALL dataclass fields to __init__
    original = Agent(name="test-agent")

    # This should not raise TypeError about unexpected keyword arguments
    copied = original.deep_copy()

    # Verify it's a different instance but with same values
    assert copied is not original
    assert copied.name == original.name
    assert copied.user_message_role == "user"
    assert copied.system_message_role == "system"

    # Test deep_copy with update
    updated = original.deep_copy(update={"name": "updated-agent"})
    assert updated.name == "updated-agent"
