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
    agent_id = agent.id
    assert is_valid_uuid(agent_id)

    agent.set_id()
    # It is deterministic, so it should be the same
    assert agent.id == agent_id


def test_set_id_auto_generated():
    agent = Agent()
    agent.set_id()
    assert is_valid_uuid(agent.id)
