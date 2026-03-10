"""Integration tests for the Session related methods of the AsyncPostgresDb class"""

import time

import pytest
import pytest_asyncio

from agno.db.base import SessionType
from agno.db.postgres import AsyncPostgresDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession


@pytest_asyncio.fixture(autouse=True)
async def cleanup_sessions(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up session rows after each test"""
    yield

    try:
        sessions_table = await async_postgres_db_real._get_table("sessions")
        async with async_postgres_db_real.async_session_factory() as session:
            await session.execute(sessions_table.delete())
            await session.commit()
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture
def sample_agent_session() -> AgentSession:
    """Fixture returning a sample AgentSession"""
    agent_run = RunOutput(
        run_id="test_agent_run_1",
        agent_id="test_agent_1",
        user_id="test_user_1",
        status=RunStatus.completed,
        messages=[],
    )
    return AgentSession(
        session_id="test_agent_session_1",
        agent_id="test_agent_1",
        user_id="test_user_1",
        team_id="test_team_1",
        session_data={"session_name": "Test Agent Session", "key": "value"},
        agent_data={"name": "Test Agent", "model": "gpt-4"},
        metadata={"extra_key": "extra_value"},
        runs=[agent_run],
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )


@pytest.fixture
def sample_team_session() -> TeamSession:
    """Fixture returning a sample TeamSession"""
    team_run = TeamRunOutput(
        run_id="test_team_run_1",
        team_id="test_team_1",
        user_id="test_user_1",
        status=RunStatus.completed,
    )
    return TeamSession(
        session_id="test_team_session_1",
        team_id="test_team_1",
        user_id="test_user_1",
        session_data={"session_name": "Test Team Session", "team_key": "team_value"},
        team_data={"name": "Test Team", "description": "A test team"},
        runs=[team_run],
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )


@pytest.mark.asyncio
async def test_upsert_agent_session(async_postgres_db_real: AsyncPostgresDb, sample_agent_session: AgentSession):
    """Test upserting an agent session"""
    # First insert
    result = await async_postgres_db_real.upsert_session(sample_agent_session)

    assert result is not None
    assert isinstance(result, AgentSession)
    assert result.session_id == "test_agent_session_1"
    assert result.agent_id == "test_agent_1"
    assert result.user_id == "test_user_1"

    # Update the session
    sample_agent_session.session_data["updated"] = True
    updated_result = await async_postgres_db_real.upsert_session(sample_agent_session)

    assert updated_result is not None
    assert updated_result.session_data["updated"] is True


@pytest.mark.asyncio
async def test_upsert_team_session(async_postgres_db_real: AsyncPostgresDb, sample_team_session: TeamSession):
    """Test upserting a team session"""
    # First insert
    result = await async_postgres_db_real.upsert_session(sample_team_session)

    assert result is not None
    assert isinstance(result, TeamSession)
    assert result.session_id == "test_team_session_1"
    assert result.team_id == "test_team_1"
    assert result.user_id == "test_user_1"


@pytest.mark.asyncio
async def test_get_agent_session(async_postgres_db_real: AsyncPostgresDb, sample_agent_session: AgentSession):
    """Test getting an agent session"""
    # First upsert the session
    await async_postgres_db_real.upsert_session(sample_agent_session)

    # Now get it back
    result = await async_postgres_db_real.get_session(session_id="test_agent_session_1", session_type=SessionType.AGENT)

    assert result is not None
    assert isinstance(result, AgentSession)
    assert result.session_id == "test_agent_session_1"
    assert result.agent_id == "test_agent_1"
    assert result.session_data["key"] == "value"


@pytest.mark.asyncio
async def test_get_team_session(async_postgres_db_real: AsyncPostgresDb, sample_team_session: TeamSession):
    """Test getting a team session"""
    # First upsert the session
    await async_postgres_db_real.upsert_session(sample_team_session)

    # Now get it back
    result = await async_postgres_db_real.get_session(session_id="test_team_session_1", session_type=SessionType.TEAM)

    assert result is not None
    assert isinstance(result, TeamSession)
    assert result.session_id == "test_team_session_1"
    assert result.team_id == "test_team_1"
    assert result.session_data["team_key"] == "team_value"


@pytest.mark.asyncio
async def test_get_sessions_with_filtering(
    async_postgres_db_real: AsyncPostgresDb, sample_agent_session: AgentSession, sample_team_session: TeamSession
):
    """Test getting sessions with various filters"""
    # Insert both sessions
    await async_postgres_db_real.upsert_session(sample_agent_session)
    await async_postgres_db_real.upsert_session(sample_team_session)

    # Get all agent sessions
    agent_sessions = await async_postgres_db_real.get_sessions(session_type=SessionType.AGENT)
    assert len(agent_sessions) == 1
    assert agent_sessions[0].session_id == "test_agent_session_1"

    # Get all team sessions
    team_sessions = await async_postgres_db_real.get_sessions(session_type=SessionType.TEAM)
    assert len(team_sessions) == 1
    assert team_sessions[0].session_id == "test_team_session_1"

    # Filter by user_id
    user_sessions = await async_postgres_db_real.get_sessions(session_type=SessionType.AGENT, user_id="test_user_1")
    assert len(user_sessions) == 1
    assert user_sessions[0].user_id == "test_user_1"


@pytest.mark.asyncio
async def test_get_sessions_with_pagination(async_postgres_db_real: AsyncPostgresDb):
    """Test getting sessions with pagination"""
    # Create multiple sessions
    sessions = []
    for i in range(5):
        agent_run = RunOutput(
            run_id=f"test_run_{i}",
            agent_id=f"test_agent_{i}",
            user_id="test_user_1",
            status=RunStatus.completed,
            messages=[],
        )
        session = AgentSession(
            session_id=f"test_session_{i}",
            agent_id=f"test_agent_{i}",
            user_id="test_user_1",
            session_data={"session_name": f"Test Session {i}"},
            agent_data={"name": f"Test Agent {i}"},
            runs=[agent_run],
            created_at=int(time.time()) + i,  # Different timestamps
        )
        sessions.append(session)
        await async_postgres_db_real.upsert_session(session)

    # Test pagination - get first page
    result, total_count = await async_postgres_db_real.get_sessions(
        session_type=SessionType.AGENT, limit=2, page=1, deserialize=False
    )

    assert len(result) == 2
    assert total_count == 5

    # Test pagination - get second page
    result, total_count = await async_postgres_db_real.get_sessions(
        session_type=SessionType.AGENT, limit=2, page=2, deserialize=False
    )

    assert len(result) == 2
    assert total_count == 5


@pytest.mark.asyncio
async def test_delete_session(async_postgres_db_real: AsyncPostgresDb, sample_agent_session: AgentSession):
    """Test deleting a single session"""
    # First insert the session
    await async_postgres_db_real.upsert_session(sample_agent_session)

    # Verify it exists
    result = await async_postgres_db_real.get_session(session_id="test_agent_session_1", session_type=SessionType.AGENT)
    assert result is not None

    # Delete it
    success = await async_postgres_db_real.delete_session("test_agent_session_1")
    assert success is True

    # Verify it's gone
    result = await async_postgres_db_real.get_session(session_id="test_agent_session_1", session_type=SessionType.AGENT)
    assert result is None


@pytest.mark.asyncio
async def test_delete_sessions_bulk(async_postgres_db_real: AsyncPostgresDb):
    """Test deleting multiple sessions"""
    # Create and insert multiple sessions
    session_ids = []
    for i in range(3):
        agent_run = RunOutput(
            run_id=f"test_run_{i}",
            agent_id=f"test_agent_{i}",
            user_id="test_user_1",
            status=RunStatus.completed,
            messages=[],
        )
        session = AgentSession(
            session_id=f"test_session_{i}",
            agent_id=f"test_agent_{i}",
            user_id="test_user_1",
            runs=[agent_run],
            created_at=int(time.time()) + i,
        )
        session_ids.append(f"test_session_{i}")
        await async_postgres_db_real.upsert_session(session)

    # Verify they exist
    sessions = await async_postgres_db_real.get_sessions(session_type=SessionType.AGENT)
    assert len(sessions) == 3

    # Delete all of them
    await async_postgres_db_real.delete_sessions(session_ids)

    # Verify they're gone
    sessions = await async_postgres_db_real.get_sessions(session_type=SessionType.AGENT)
    assert len(sessions) == 0


@pytest.mark.asyncio
async def test_rename_session(async_postgres_db_real: AsyncPostgresDb, sample_agent_session: AgentSession):
    """Test renaming a session"""
    # First insert the session
    await async_postgres_db_real.upsert_session(sample_agent_session)

    # Rename it
    result = await async_postgres_db_real.rename_session(
        session_id="test_agent_session_1", session_type=SessionType.AGENT, session_name="New Session Name"
    )

    assert result is not None
    assert isinstance(result, AgentSession)
    assert result.session_data["session_name"] == "New Session Name"

    # Verify the change persisted
    retrieved = await async_postgres_db_real.get_session(
        session_id="test_agent_session_1", session_type=SessionType.AGENT
    )
    assert retrieved.session_data["session_name"] == "New Session Name"
