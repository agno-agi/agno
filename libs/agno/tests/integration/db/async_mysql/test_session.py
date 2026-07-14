"""Integration tests for AsyncMySQLDb session methods"""

import pytest

from agno.db.base import SessionType
from agno.session import AgentSession, TeamSession, WorkflowSession


@pytest.mark.asyncio
async def test_upsert_and_get_agent_session(async_mysql_db_real):
    """Test upserting and retrieving an agent session"""
    session = AgentSession(
        session_id="test-agent-session",
        agent_id="test-agent",
        user_id="test-user",
        session_data={"key": "value"},
    )

    # Upsert session
    result = await async_mysql_db_real.upsert_session(session)
    assert result is not None
    assert result.session_id == "test-agent-session"

    # Get session back
    retrieved = await async_mysql_db_real.get_session(session_id="test-agent-session", session_type=SessionType.AGENT)
    assert retrieved is not None
    assert retrieved.agent_id == "test-agent"
    assert retrieved.user_id == "test-user"


@pytest.mark.asyncio
async def test_upsert_and_get_team_session(async_mysql_db_real):
    """Test upserting and retrieving a team session"""
    session = TeamSession(
        session_id="test-team-session",
        team_id="test-team",
        user_id="test-user",
        session_data={"key": "value"},
    )

    # Upsert session
    result = await async_mysql_db_real.upsert_session(session)
    assert result is not None
    assert result.session_id == "test-team-session"

    # Get session back
    retrieved = await async_mysql_db_real.get_session(session_id="test-team-session", session_type=SessionType.TEAM)
    assert retrieved is not None
    assert retrieved.team_id == "test-team"


@pytest.mark.asyncio
async def test_upsert_and_get_workflow_session(async_mysql_db_real):
    """Test upserting and retrieving a workflow session"""
    session = WorkflowSession(
        session_id="test-workflow-session",
        workflow_id="test-workflow",
        user_id="test-user",
        session_data={"key": "value"},
    )

    # Upsert session
    result = await async_mysql_db_real.upsert_session(session)
    assert result is not None
    assert result.session_id == "test-workflow-session"

    # Get session back
    retrieved = await async_mysql_db_real.get_session(
        session_id="test-workflow-session", session_type=SessionType.WORKFLOW
    )
    assert retrieved is not None
    assert retrieved.workflow_id == "test-workflow"


@pytest.mark.asyncio
async def test_delete_session(async_mysql_db_real):
    """Test deleting a session"""
    session = AgentSession(
        session_id="test-delete-session",
        agent_id="test-agent",
    )

    # Upsert and then delete
    await async_mysql_db_real.upsert_session(session)
    result = await async_mysql_db_real.delete_session("test-delete-session")
    assert result is True

    # Verify it's gone
    retrieved = await async_mysql_db_real.get_session(session_id="test-delete-session", session_type=SessionType.AGENT)
    assert retrieved is None


@pytest.mark.asyncio
async def test_get_sessions_with_filters(async_mysql_db_real):
    """Test getting sessions with various filters"""
    # Create multiple sessions
    for i in range(3):
        session = AgentSession(
            session_id=f"test-filter-session-{i}",
            agent_id="test-agent",
            user_id=f"user-{i % 2}",
        )
        await async_mysql_db_real.upsert_session(session)

    # Get all sessions
    sessions = await async_mysql_db_real.get_sessions(session_type=SessionType.AGENT)
    assert len(sessions) >= 3

    # Filter by user_id
    user_sessions = await async_mysql_db_real.get_sessions(session_type=SessionType.AGENT, user_id="user-0")
    assert len(user_sessions) >= 1


@pytest.mark.asyncio
async def test_rename_session(async_mysql_db_real):
    """Test renaming a session"""
    session = AgentSession(
        session_id="test-rename-session",
        agent_id="test-agent",
        session_data={"session_name": "Old Name"},
    )

    await async_mysql_db_real.upsert_session(session)

    # Rename the session
    renamed = await async_mysql_db_real.rename_session(
        session_id="test-rename-session", session_type=SessionType.AGENT, session_name="New Name"
    )

    assert renamed is not None
    assert renamed.session_data.get("session_name") == "New Name"


@pytest.mark.asyncio
async def test_upsert_sessions(async_mysql_db_real):
    """Test upsert_sessions with mixed session types (Agent, Team, Workflow)"""
    import time

    # Create agent session
    agent_session = AgentSession(
        session_id="bulk_agent_session_1",
        agent_id="bulk_agent_1",
        user_id="bulk_user_1",
        agent_data={"name": "Bulk Agent 1"},
        session_data={"type": "bulk_test"},
        created_at=int(time.time()),
    )

    # Create team session
    team_session = TeamSession(
        session_id="bulk_team_session_1",
        team_id="bulk_team_1",
        user_id="bulk_user_1",
        team_data={"name": "Bulk Team 1"},
        session_data={"type": "bulk_test"},
        created_at=int(time.time()),
    )

    # Create workflow session
    workflow_session = WorkflowSession(
        session_id="bulk_workflow_session_1",
        workflow_id="bulk_workflow_1",
        user_id="bulk_user_1",
        workflow_data={"name": "Bulk Workflow 1"},
        session_data={"type": "bulk_test"},
        created_at=int(time.time()),
    )

    # Bulk upsert all sessions
    sessions = [agent_session, team_session, workflow_session]
    results = await async_mysql_db_real.upsert_sessions(sessions)

    # Verify results
    assert len(results) == 3

    # Find and verify per session type
    agent_result = next(r for r in results if isinstance(r, AgentSession))
    team_result = next(r for r in results if isinstance(r, TeamSession))
    workflow_result = next(r for r in results if isinstance(r, WorkflowSession))

    # Verify agent session
    assert agent_result.session_id == agent_session.session_id
    assert agent_result.agent_id == agent_session.agent_id
    assert agent_result.agent_data == agent_session.agent_data

    # Verify team session
    assert team_result.session_id == team_session.session_id
    assert team_result.team_id == team_session.team_id
    assert team_result.team_data == team_session.team_data

    # Verify workflow session
    assert workflow_result.session_id == workflow_session.session_id
    assert workflow_result.workflow_id == workflow_session.workflow_id
    assert workflow_result.workflow_data == workflow_session.workflow_data


@pytest.mark.asyncio
async def test_upsert_sessions_update(async_mysql_db_real):
    """Test upsert_sessions correctly updates existing sessions"""
    import time

    # Insert sessions
    session1 = AgentSession(
        session_id="bulk_update_1",
        agent_id="agent_1",
        user_id="user_1",
        agent_data={"name": "Original Agent 1"},
        session_data={"version": 1},
        created_at=int(time.time()),
    )
    session2 = AgentSession(
        session_id="bulk_update_2",
        agent_id="agent_2",
        user_id="user_1",
        agent_data={"name": "Original Agent 2"},
        session_data={"version": 1},
        created_at=int(time.time()),
    )
    await async_mysql_db_real.upsert_sessions([session1, session2])

    # Update sessions
    updated_session1 = AgentSession(
        session_id="bulk_update_1",
        agent_id="agent_1",
        user_id="user_1",
        agent_data={"name": "Updated Agent 1", "updated": True},
        session_data={"version": 2, "updated": True},
        created_at=session1.created_at,  # Keep original created_at
    )
    updated_session2 = AgentSession(
        session_id="bulk_update_2",
        agent_id="agent_2",
        user_id="user_1",
        agent_data={"name": "Updated Agent 2", "updated": True},
        session_data={"version": 2, "updated": True},
        created_at=session2.created_at,  # Keep original created_at
    )
    results = await async_mysql_db_real.upsert_sessions([updated_session1, updated_session2])
    assert len(results) == 2

    # Verify sessions were updated
    for result in results:
        assert isinstance(result, AgentSession)
        assert result.agent_data is not None and result.agent_data["updated"] is True
        assert result.session_data is not None and result.session_data["version"] == 2
        assert result.session_data is not None and result.session_data["updated"] is True

        # created_at should be preserved
        if result.session_id == "bulk_update_1":
            assert result.created_at == session1.created_at
        else:
            assert result.created_at == session2.created_at


# ── session_type=None integration tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_sessions_without_type_returns_all(async_mysql_db_real):
    """get_sessions(session_type=None) returns agent, team, and workflow sessions together."""
    agent = AgentSession(session_id="none-type-agent", agent_id="a1", user_id="u1")
    team = TeamSession(session_id="none-type-team", team_id="t1", user_id="u1")
    workflow = WorkflowSession(session_id="none-type-wf", workflow_id="w1", user_id="u1")

    await async_mysql_db_real.upsert_session(agent)
    await async_mysql_db_real.upsert_session(team)
    await async_mysql_db_real.upsert_session(workflow)

    # session_type=None should return all three
    sessions_raw, total_count = await async_mysql_db_real.get_sessions(session_type=None, deserialize=False)
    assert total_count >= 3
    session_ids = {s["session_id"] for s in sessions_raw}
    assert "none-type-agent" in session_ids
    assert "none-type-team" in session_ids
    assert "none-type-wf" in session_ids

    # Deserialized path should auto-detect correct types
    sessions = await async_mysql_db_real.get_sessions(session_type=None)
    assert len(sessions) >= 3
    types = {type(s) for s in sessions}
    assert AgentSession in types
    assert TeamSession in types
    assert WorkflowSession in types


@pytest.mark.asyncio
async def test_get_sessions_without_type_with_component_id(async_mysql_db_real):
    """get_sessions(session_type=None, component_id=X) uses OR across agent_id/team_id/workflow_id."""
    agent = AgentSession(session_id="comp-filter-agent", agent_id="comp-a1", user_id="u1")
    team = TeamSession(session_id="comp-filter-team", team_id="comp-t1", user_id="u1")

    await async_mysql_db_real.upsert_session(agent)
    await async_mysql_db_real.upsert_session(team)

    # Filter by agent component_id without specifying type
    sessions_raw, total_count = await async_mysql_db_real.get_sessions(
        session_type=None, component_id="comp-a1", deserialize=False
    )
    assert total_count >= 1
    assert any(s["session_id"] == "comp-filter-agent" for s in sessions_raw)

    # Filter by nonexistent component_id
    sessions_raw, total_count = await async_mysql_db_real.get_sessions(
        session_type=None, component_id="nonexistent", deserialize=False
    )
    assert total_count == 0


@pytest.mark.asyncio
async def test_get_session_without_type_auto_detects(async_mysql_db_real):
    """get_session(session_type=None) auto-detects the correct session type for deserialization."""
    agent = AgentSession(session_id="auto-detect-agent", agent_id="a1")
    team = TeamSession(session_id="auto-detect-team", team_id="t1")

    await async_mysql_db_real.upsert_session(agent)
    await async_mysql_db_real.upsert_session(team)

    result = await async_mysql_db_real.get_session(session_id="auto-detect-agent", session_type=None)
    assert result is not None
    assert isinstance(result, AgentSession)

    result = await async_mysql_db_real.get_session(session_id="auto-detect-team", session_type=None)
    assert result is not None
    assert isinstance(result, TeamSession)
