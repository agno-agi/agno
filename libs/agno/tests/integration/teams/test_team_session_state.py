import pytest

from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


@pytest.fixture
def route_team(team_storage, memory):
    """Create a route team with storage and memory for testing."""
    return Team(
        name="Route Team",
        mode="route",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        storage=team_storage,
        memory=memory,
        enable_user_memories=True,
    )


def test_team_session_state(route_team, team_storage):
    session_id = "session_1"

    route_team.session_id = session_id
    route_team.session_name = "my_test_session"
    route_team.session_state = {"test_key": "test_value"}
    route_team.team_session_state = {"team_test_key": "team_test_value"}

    response = route_team.run("Hello, how are you?")
    assert response.run_id is not None
    assert route_team.session_id == session_id
    assert route_team.session_name == "my_test_session"
    assert route_team.session_state == {"current_session_id": session_id, "test_key": "test_value"}
    assert route_team.team_session_state == {"current_session_id": session_id, "team_test_key": "team_test_value"}
    session_from_storage = team_storage.read(session_id=session_id)
    assert session_from_storage is not None
    assert session_from_storage.session_id == session_id
    assert session_from_storage.session_data["session_name"] == "my_test_session"
    assert session_from_storage.session_data["session_state"] == {
        "current_session_id": session_id,
        "test_key": "test_value",
    }

    # Run again with the same session ID
    response = route_team.run("What can you do?", session_id=session_id)
    assert response.run_id is not None
    assert route_team.session_id == session_id
    assert route_team.session_name == "my_test_session"
    assert route_team.session_state == {"current_session_id": session_id, "test_key": "test_value"}

    # Run with a different session ID
    response = route_team.run("What can you do?", session_id="session_2")
    assert response.run_id is not None
    assert route_team.session_id == "session_2"
    assert route_team.session_name is None
    assert route_team.session_state == {"current_session_id": "session_2"}

    # Run again with original session ID
    response = route_team.run("What name should I call you?", session_id=session_id)
    assert response.run_id is not None
    assert route_team.session_id == session_id
    assert route_team.session_name == "my_test_session"
    assert route_team.session_state == {"current_session_id": session_id, "test_key": "test_value"}


def test_team_session_state_stream(route_team):
    session_id = "session_1"

    route_team.session_id = session_id
    route_team.session_name = "my_test_session"
    route_team.session_state = {"test_key": "test_value"}
    route_team.team_session_state = {"team_test_key": "team_test_value"}

    for _ in route_team.run("Hello, how are you?", stream=True):
        pass
    response = route_team.run_response
    assert response.run_id is not None
    assert route_team.session_id == session_id
    assert route_team.session_name == "my_test_session"
    assert route_team.session_state == {"current_session_id": session_id, "test_key": "test_value"}
    assert route_team.team_session_state == {"current_session_id": session_id, "team_test_key": "team_test_value"}


def test_team_session_state_switch_session_id(route_team):
    session_id_1 = "session_1"
    session_id_2 = "session_2"

    route_team.session_name = "my_test_session"
    route_team.session_state = {"test_key": "test_value"}

    # First run with a different session ID
    response = route_team.run("What can you do?", session_id=session_id_1)
    assert response.run_id is not None
    assert route_team.session_id == session_id_1
    assert route_team.session_name == "my_test_session"
    assert route_team.session_state == {"current_session_id": session_id_1, "test_key": "test_value"}

    # Second run with different session ID
    response = route_team.run("What can you do?", session_id=session_id_2)
    assert response.run_id is not None
    assert route_team.session_id == session_id_2
    assert route_team.session_name is None
    assert route_team.session_state == {"current_session_id": session_id_2}

    # Third run with the original session ID
    response = route_team.run("What can you do?", session_id=session_id_1)
    assert response.run_id is not None
    assert route_team.session_id == session_id_1
    assert route_team.session_name == "my_test_session"
    assert route_team.session_state == {"current_session_id": session_id_1, "test_key": "test_value"}


def test_team_session_state_on_run(route_team):
    session_id_1 = "session_1"
    session_id_2 = "session_2"

    route_team.session_name = "my_test_session"

    # First run with a different session ID
    response = route_team.run("What can you do?", session_id=session_id_1, session_state={"test_key": "test_value"})
    assert response.run_id is not None
    assert route_team.session_id == session_id_1
    assert route_team.session_name == "my_test_session"  # Correctly set from the first run
    assert route_team.session_state == {"current_session_id": session_id_1, "test_key": "test_value"}

    # Second run with different session ID
    response = route_team.run("What can you do?", session_id=session_id_2)
    assert response.run_id is not None
    assert route_team.session_id == session_id_2
    assert route_team.session_name is None  # Should be unset, new session ID
    assert route_team.session_state == {"current_session_id": session_id_2}

    # Third run with the original session ID
    response = route_team.run(
        "What can you do?", session_id=session_id_1, session_state={"something_else": "other_value"}
    )
    assert response.run_id is not None
    assert route_team.session_id == session_id_1
    assert route_team.session_name == "my_test_session"  # Should load what was set on the first run
    assert route_team.session_state == {
        "current_session_id": session_id_1,
        "test_key": "test_value",
        "something_else": "other_value",
    }, "Merging session state should work"
