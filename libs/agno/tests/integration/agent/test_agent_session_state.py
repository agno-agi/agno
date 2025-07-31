import pytest

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat


@pytest.fixture
def chat_agent(agent_storage, memory):
    """Create an agent with storage and memory for testing."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        memory=memory,
    )


def test_agent_session_state(chat_agent, agent_storage):
    session_id = "session_1"

    chat_agent.session_id = session_id
    chat_agent.session_name = "my_test_session"
    chat_agent.session_state = {"test_key": "test_value"}
    chat_agent.team_session_state = {"team_test_key": "team_test_value"}

    response = chat_agent.run("Hello, how are you?")
    assert response.run_id is not None
    assert chat_agent.session_id == session_id
    assert chat_agent.session_name == "my_test_session"
    assert chat_agent.session_state == {"current_session_id": session_id, "test_key": "test_value"}
    assert chat_agent.team_session_state == {"current_session_id": session_id, "team_test_key": "team_test_value"}
    session_from_storage = agent_storage.read(session_id=session_id)
    assert session_from_storage is not None
    assert session_from_storage.session_id == session_id
    assert session_from_storage.session_data["session_name"] == "my_test_session"
    assert session_from_storage.session_data["session_state"] == {
        "current_session_id": session_id,
        "test_key": "test_value",
    }

    # Run again with the same session ID
    response = chat_agent.run("What can you do?", session_id=session_id)
    assert response.run_id is not None
    assert chat_agent.session_id == session_id
    assert chat_agent.session_name == "my_test_session"
    assert chat_agent.session_state == {"current_session_id": session_id, "test_key": "test_value"}

    # Run with a different session ID
    response = chat_agent.run("What can you do?", session_id="session_2")
    assert response.run_id is not None
    assert chat_agent.session_id == "session_2"
    assert chat_agent.session_name is None
    assert chat_agent.session_state == {"current_session_id": "session_2"}

    # Run again with original session ID
    response = chat_agent.run("What name should I call you?", session_id=session_id)
    assert response.run_id is not None
    assert chat_agent.session_id == session_id
    assert chat_agent.session_name == "my_test_session"
    assert chat_agent.session_state == {"current_session_id": session_id, "test_key": "test_value"}


def test_agent_session_state_stream(chat_agent):
    session_id = "session_1"

    chat_agent.session_id = session_id
    chat_agent.session_name = "my_test_session"
    chat_agent.session_state = {"test_key": "test_value"}
    chat_agent.team_session_state = {"team_test_key": "team_test_value"}

    for _ in chat_agent.run("Hello, how are you?", stream=True):
        pass
    response = chat_agent.run_response
    assert response.run_id is not None
    assert chat_agent.session_id == session_id
    assert chat_agent.session_name == "my_test_session"
    assert chat_agent.session_state == {"current_session_id": session_id, "test_key": "test_value"}
    assert chat_agent.team_session_state == {"current_session_id": session_id, "team_test_key": "team_test_value"}


def test_agent_session_state_switch_session_id(chat_agent):
    session_id_1 = "session_1"
    session_id_2 = "session_2"

    chat_agent.session_name = "my_test_session"
    chat_agent.session_state = {"test_key": "test_value"}

    # First run with a session ID (reset should not happen)
    response = chat_agent.run("What can you do?", session_id=session_id_1)
    assert response.run_id is not None
    assert chat_agent.session_id == session_id_1
    assert chat_agent.session_name == "my_test_session"
    assert chat_agent.session_state == {"current_session_id": session_id_1, "test_key": "test_value"}

    # Second run with different session ID
    response = chat_agent.run("What can you do?", session_id=session_id_2)
    assert response.run_id is not None
    assert chat_agent.session_id == session_id_2
    assert chat_agent.session_name is None
    assert chat_agent.session_state == {"current_session_id": session_id_2}

    # Third run with the original session ID
    response = chat_agent.run("What can you do?", session_id=session_id_1)
    assert response.run_id is not None
    assert chat_agent.session_id == session_id_1
    assert chat_agent.session_name == "my_test_session"
    assert chat_agent.session_state == {"current_session_id": session_id_1, "test_key": "test_value"}


def test_agent_session_state_on_run(chat_agent):
    session_id_1 = "session_1"
    session_id_2 = "session_2"

    chat_agent.session_name = "my_test_session"

    # First run with a different session ID
    response = chat_agent.run("What can you do?", session_id=session_id_1, session_state={"test_key": "test_value"})
    assert response.run_id is not None
    assert chat_agent.session_id == session_id_1
    assert chat_agent.session_state == {"current_session_id": session_id_1, "test_key": "test_value"}

    # Second run with different session ID
    response = chat_agent.run("What can you do?", session_id=session_id_2)
    assert response.run_id is not None
    assert chat_agent.session_id == session_id_2
    assert chat_agent.session_state == {"current_session_id": session_id_2}

    # Third run with the original session ID
    response = chat_agent.run(
        "What can you do?", session_id=session_id_1, session_state={"something_else": "other_value"}
    )
    assert response.run_id is not None
    assert chat_agent.session_id == session_id_1
    assert chat_agent.session_state == {
        "current_session_id": session_id_1,
        "test_key": "test_value",
        "something_else": "other_value",
    }, "Merging session state should work"
