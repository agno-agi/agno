from typing import Any, Dict, Optional

from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


def team_factory(shared_db, session_id: Optional[str] = None, session_state: Optional[Dict[str, Any]] = None):
    return Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        session_id=session_id,
        session_state=session_state,
        members=[],
        db=shared_db,
        enable_user_memories=True,
        markdown=True,
        telemetry=False,
    )


def test_team_set_session_name(shared_db):
    session_id = "session_1"
    session_state = {"test_key": "test_value"}

    team = team_factory(shared_db, session_id, session_state)

    team.run("Hello, how are you?")

    team.set_session_name(session_id=session_id, session_name="my_test_session")

    session_from_storage = team.get_session(session_id=session_id)
    assert session_from_storage is not None
    assert session_from_storage.session_id == session_id
    assert session_from_storage.session_data is not None
    assert session_from_storage.session_data["session_name"] == "my_test_session"


def test_team_get_session_name(shared_db):
    session_id = "session_1"
    team = team_factory(shared_db, session_id)
    team.run("Hello, how are you?")
    team.set_session_name(session_id=session_id, session_name="my_test_session")
    assert team.get_session_name() == "my_test_session"


def test_team_get_session_state(shared_db):
    session_id = "session_1"
    team = team_factory(shared_db, session_id, session_state={"test_key": "test_value"})
    team.run("Hello, how are you?")
    assert team.get_session_state() == {"test_key": "test_value"}


def test_team_get_session_metrics(shared_db):
    session_id = "session_1"
    team = team_factory(shared_db, session_id)
    team.run("Hello, how are you?")
    metrics = team.get_session_metrics()
    assert metrics is not None
    assert metrics.total_tokens > 0
    assert metrics.input_tokens > 0
    assert metrics.output_tokens > 0
    assert metrics.total_tokens == metrics.input_tokens + metrics.output_tokens
