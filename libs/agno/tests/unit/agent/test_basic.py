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
