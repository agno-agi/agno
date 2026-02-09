import uuid

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team.team import Team


@pytest.fixture
def agent_1(shared_db):
    def get_weather(city: str) -> str:
        """Get the weather for the given city."""
        return f"The weather in {city} is sunny."

    return Agent(
        name="fast-weather-agent",
        id="fast-weather-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
        tools=[get_weather],
    )


@pytest.fixture
def agent_2(shared_db):
    def get_activities(city: str) -> str:
        """Get the activities for the given city."""
        return f"The activities in {city} are swimming and hiking."

    return Agent(
        name="fast-activities-agent",
        id="fast-activities-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
        tools=[get_activities],
    )


@pytest.fixture
def team_1(shared_db):
    def get_weather(city: str) -> str:
        """Get the weather for the given city."""
        return f"The weather in {city} is sunny."

    weather_agent = Agent(
        name="weather-agent",
        id="weather-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
        tools=[get_weather],
    )

    return Team(
        model=OpenAIChat(id="gpt-4o"),
        members=[weather_agent],
        db=shared_db,
    )


@pytest.fixture
def team_2(shared_db):
    def get_activities(city: str) -> str:
        """Get the weather for the given city."""
        return f"The activities in {city} are swimming and hiking."

    activities_agent = Agent(
        name="activities-agent",
        id="activities-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
        tools=[get_activities],
    )

    return Team(
        model=OpenAIChat(id="gpt-4o"),
        members=[activities_agent],
        db=shared_db,
    )


def test_session_sharing_team_to_agent_with_history(agent_1, team_1):
    team_1.add_history_to_context = True
    team_1.num_history_runs = 5
    team_1.store_history_messages = True
    agent_1.add_history_to_context = True
    agent_1.num_history_runs = 5
    agent_1.store_history_messages = True

    session_id = str(uuid.uuid4())
    team_1.run(
        "What is the weather in Tokyo?", session_id=session_id, user_id="user_1", session_state={"city": "Tokyo"}
    )

    session_from_db = team_1.get_session(session_id=session_id)

    assert session_from_db is not None
    assert isinstance(session_from_db, TeamSession)
    assert session_from_db.session_id == session_id
    assert session_from_db.session_data is not None
    assert session_from_db.session_data["session_state"] == {"city": "Tokyo"}
    assert len(session_from_db.runs) == 2, "We should have the team run and the member run"
    assert len(session_from_db.runs[-1].messages) == 5, "First run, no history messages"

    assert isinstance(session_from_db.runs[0], RunOutput)
    assert session_from_db.runs[0].agent_id == "weather-agent-id"
    assert session_from_db.runs[0].parent_run_id == session_from_db.runs[1].run_id
    assert isinstance(session_from_db.runs[1], TeamRunOutput)
    assert session_from_db.runs[1].team_id == team_1.id
    assert session_from_db.runs[1].parent_run_id is None

    agent_1.run(
        "What is the weather in Paris?", session_id=session_id, user_id="user_1", session_state={"city": "Paris"}
    )

    session_from_db = agent_1.get_session(session_id=session_id)
    assert session_from_db is not None
    assert isinstance(session_from_db, AgentSession)
    assert session_from_db.session_id == session_id
    assert session_from_db.session_data is not None
    assert session_from_db.session_data["session_state"] == {"city": "Paris"}
    assert len(session_from_db.runs) == 3, "We should have all previous runs, plus the new agent run"

    assert len(session_from_db.runs[-1].messages) == 8, (
        "Original 4 history messages (not system message), plus the new agent run's messages"
    )
    assert isinstance(session_from_db.runs[0], RunOutput)
    assert session_from_db.runs[0].agent_id == "weather-agent-id"
    assert session_from_db.runs[0].parent_run_id == session_from_db.runs[1].run_id
    assert isinstance(session_from_db.runs[1], TeamRunOutput)
    assert session_from_db.runs[1].team_id == team_1.id
    assert session_from_db.runs[1].parent_run_id is None
    assert isinstance(session_from_db.runs[2], RunOutput)
    assert session_from_db.runs[2].agent_id == agent_1.id
    assert session_from_db.runs[2].parent_run_id is None


def test_session_sharing_agent_to_team_with_history(agent_1, team_1):
    team_1.add_history_to_context = True
    team_1.num_history_runs = 5
    team_1.store_history_messages = True
    agent_1.add_history_to_context = True
    agent_1.num_history_runs = 5
    agent_1.store_history_messages = True

    session_id = str(uuid.uuid4())
    agent_1.run(
        "What is the weather in Tokyo?", session_id=session_id, user_id="user_1", session_state={"city": "Tokyo"}
    )

    session_from_db = agent_1.get_session(session_id=session_id)

    assert session_from_db is not None
    assert isinstance(session_from_db, AgentSession)
    assert session_from_db.session_id == session_id
    assert session_from_db.session_data is not None
    assert session_from_db.session_data["session_state"] == {"city": "Tokyo"}
    assert len(session_from_db.runs) == 1, "We should have the agent run"
    assert len(session_from_db.runs[-1].messages) == 4, "First run, no history messages"
    assert isinstance(session_from_db.runs[0], RunOutput)
    assert session_from_db.runs[0].agent_id == agent_1.id
    assert session_from_db.runs[0].parent_run_id is None

    team_1.run(
        "What is the weather in Paris?", session_id=session_id, user_id="user_1", session_state={"city": "Paris"}
    )

    session_from_db = team_1.get_session(session_id=session_id)
    assert session_from_db is not None
    assert isinstance(session_from_db, TeamSession)
    assert session_from_db.session_id == session_id
    assert session_from_db.session_data is not None
    assert session_from_db.session_data["session_state"] == {"city": "Paris"}
    assert len(session_from_db.runs) == 3, "We should have the first agent run, plus the new team run and member run"

    assert len(session_from_db.runs[-1].messages) == 9, "Original 4 history messages, plus the new team run's messages"

    assert isinstance(session_from_db.runs[0], RunOutput)
    assert session_from_db.runs[0].agent_id == agent_1.id
    assert session_from_db.runs[0].parent_run_id is None
    assert isinstance(session_from_db.runs[1], RunOutput)
    assert session_from_db.runs[1].agent_id == "weather-agent-id"
    assert session_from_db.runs[1].parent_run_id == session_from_db.runs[2].run_id
    assert isinstance(session_from_db.runs[2], TeamRunOutput)
    assert session_from_db.runs[2].team_id == team_1.id
    assert session_from_db.runs[2].parent_run_id is None


def test_session_sharing_agent_to_agent_with_history(agent_1, agent_2):
    agent_1.add_history_to_context = True
    agent_1.num_history_runs = 5
    agent_1.store_history_messages = True
    agent_2.add_history_to_context = True
    agent_2.num_history_runs = 5
    agent_2.store_history_messages = True

    session_id = str(uuid.uuid4())

    agent_1.run(
        "What is the weather in Tokyo?", session_id=session_id, user_id="user_1", session_state={"city": "Tokyo"}
    )

    session_from_db = agent_1.get_session(session_id=session_id)

    assert session_from_db is not None
    assert isinstance(session_from_db, AgentSession)
    assert session_from_db.session_id == session_id
    assert session_from_db.session_data is not None
    assert session_from_db.session_data["session_state"] == {"city": "Tokyo"}
    assert len(session_from_db.runs) == 1, "We should have the agent run"

    assert len(session_from_db.runs[-1].messages) == 4, "First run, no history messages"

    agent_2.run(
        "What are activities in Tokyo?", session_id=session_id, user_id="user_1", session_state={"city": "Tokyo"}
    )

    session_from_db = agent_2.get_session(session_id=session_id)
    assert session_from_db is not None
    assert isinstance(session_from_db, AgentSession)
    assert session_from_db.session_id == session_id
    assert session_from_db.session_data is not None
    assert session_from_db.session_data["session_state"] == {"city": "Tokyo"}
    assert len(session_from_db.runs) == 2, "We should have the first agent run, plus the new agent run"

    assert len(session_from_db.runs[-1].messages) == 8, "Original 4 history messages, plus the new agent run's messages"


def test_session_sharing_team_to_team_with_history(team_1, team_2):
    team_1.add_history_to_context = True
    team_1.num_history_runs = 5
    team_1.store_history_messages = True
    team_2.add_history_to_context = True
    team_2.num_history_runs = 5
    team_2.store_history_messages = True

    session_id = str(uuid.uuid4())

    team_1.run(
        "What is the weather in Tokyo?", session_id=session_id, user_id="user_1", session_state={"city": "Tokyo"}
    )

    session_from_db = team_1.get_session(session_id=session_id)

    assert session_from_db is not None
    assert isinstance(session_from_db, TeamSession)
    assert session_from_db.session_id == session_id
    assert session_from_db.session_data is not None
    assert session_from_db.session_data["session_state"] == {"city": "Tokyo"}
    assert len(session_from_db.runs) == 2, "We should have the team run and the member run"
    assert len(session_from_db.runs[-1].messages) == 5, "First run, no history messages"

    team_2.run(
        "What are activities in Tokyo?", session_id=session_id, user_id="user_1", session_state={"city": "Tokyo"}
    )

    session_from_db = team_2.get_session(session_id=session_id)
    assert session_from_db is not None
    assert isinstance(session_from_db, TeamSession)
    assert session_from_db.session_id == session_id
    assert session_from_db.session_data is not None
    assert session_from_db.session_data["session_state"] == {"city": "Tokyo"}
    assert len(session_from_db.runs) == 4, (
        "We should have the first team run and member run, plus the new team run and member run"
    )
    assert len(session_from_db.runs[-1].messages) == 9, "Original 4 history messages, plus the new team run's messages"
