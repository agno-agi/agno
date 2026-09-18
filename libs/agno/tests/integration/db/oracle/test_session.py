"""Integration tests for OracleDb session methods"""

import threading
import time

from agno.db.base import SessionType
from agno.session import AgentSession, TeamSession, WorkflowSession


def test_upsert_and_get_agent_session(oracle_db_real):
    """Test upserting and retrieving an agent session"""
    session = AgentSession(
        session_id="test-agent-session",
        agent_id="test-agent",
        user_id="test-user",
        session_data={"key": "value"},
        created_at=int(time.time()),
    )

    # Upsert session
    result = oracle_db_real.upsert_session(session)
    assert result is not None
    assert result.session_id == "test-agent-session"

    # Get session back
    retrieved = oracle_db_real.get_session(session_id="test-agent-session", session_type=SessionType.AGENT)
    assert retrieved is not None
    assert retrieved.agent_id == "test-agent"
    assert retrieved.user_id == "test-user"


def test_upsert_and_get_team_session(oracle_db_real):
    """Test upserting and retrieving a team session"""
    session = TeamSession(
        session_id="test-team-session",
        team_id="test-team",
        user_id="test-user",
        session_data={"key": "value"},
        created_at=int(time.time()),
    )

    # Upsert session
    result = oracle_db_real.upsert_session(session)
    assert result is not None
    assert result.session_id == "test-team-session"

    # Get session back
    retrieved = oracle_db_real.get_session(session_id="test-team-session", session_type=SessionType.TEAM)
    assert retrieved is not None
    assert retrieved.team_id == "test-team"


def test_upsert_and_get_workflow_session(oracle_db_real):
    """Test upserting and retrieving a workflow session"""
    session = WorkflowSession(
        session_id="test-workflow-session",
        workflow_id="test-workflow",
        user_id="test-user",
        session_data={"key": "value"},
    )

    # Upsert session
    result = oracle_db_real.upsert_session(session)
    assert result is not None
    assert result.session_id == "test-workflow-session"

    # Get session back
    retrieved = oracle_db_real.get_session(session_id="test-workflow-session", session_type=SessionType.WORKFLOW)
    assert retrieved is not None
    assert retrieved.workflow_id == "test-workflow"


def test_delete_session(oracle_db_real):
    """Test deleting a session"""
    session = AgentSession(
        session_id="test-delete-session",
        agent_id="test-agent",
        created_at=int(time.time()),
    )

    # Upsert and then delete
    oracle_db_real.upsert_session(session)
    result = oracle_db_real.delete_session("test-delete-session")
    assert result is True

    # Verify it's gone
    retrieved = oracle_db_real.get_session(session_id="test-delete-session", session_type=SessionType.AGENT)
    assert retrieved is None


def test_delete_session_scoped_by_user_id(oracle_db_real):
    """Verify delete_session with user_id only deletes sessions owned by that user (IDOR protection)."""
    alice_session = AgentSession(
        session_id="shared_sess_1", agent_id="agent_1", user_id="alice", created_at=int(time.time())
    )
    bob_session = AgentSession(
        session_id="shared_sess_2", agent_id="agent_1", user_id="bob", created_at=int(time.time())
    )
    oracle_db_real.upsert_session(alice_session)
    oracle_db_real.upsert_session(bob_session)

    # Bob tries to delete Alice's session
    result = oracle_db_real.delete_session("shared_sess_1", user_id="bob")
    assert result is False

    # Alice's session is untouched
    retrieved = oracle_db_real.get_session(session_id="shared_sess_1", session_type=SessionType.AGENT)
    assert retrieved is not None


def test_delete_multiple_sessions(oracle_db_real):
    """Test deleting multiple sessions"""
    sessions = []
    session_ids = []
    for i in range(3):
        session = AgentSession(session_id=f"session_{i}", agent_id=f"agent_{i}", created_at=int(time.time()))
        sessions.append(session)
        session_ids.append(session.session_id)
        oracle_db_real.upsert_session(session)

    # Verify they exist
    all_sessions = oracle_db_real.get_sessions(session_type=SessionType.AGENT)
    assert len(all_sessions) >= 3

    # Delete multiple sessions
    oracle_db_real.delete_sessions(session_ids[:2])  # Delete first 2

    remaining_ids = {s.session_id for s in oracle_db_real.get_sessions(session_type=SessionType.AGENT)}
    assert "session_0" not in remaining_ids
    assert "session_1" not in remaining_ids
    assert "session_2" in remaining_ids


def test_get_sessions_with_filters(oracle_db_real):
    """Test getting sessions with various filters"""
    # Create multiple sessions
    for i in range(3):
        session = AgentSession(
            session_id=f"test-filter-session-{i}",
            agent_id="test-agent",
            user_id=f"user-{i % 2}",
            created_at=int(time.time()),
        )
        oracle_db_real.upsert_session(session)

    # Get all sessions
    sessions = oracle_db_real.get_sessions(session_type=SessionType.AGENT)
    assert len(sessions) >= 3

    # Filter by user_id
    user_sessions = oracle_db_real.get_sessions(session_type=SessionType.AGENT, user_id="user-0")
    assert len(user_sessions) >= 1


def test_get_sessions_with_pagination(oracle_db_real):
    """Test getting sessions with pagination"""
    for i in range(5):
        session = AgentSession(session_id=f"page-session-{i}", agent_id="test-agent", created_at=int(time.time()))
        oracle_db_real.upsert_session(session)

    page1, total = oracle_db_real.get_sessions(session_type=SessionType.AGENT, limit=2, page=1, deserialize=False)
    assert len(page1) <= 2
    assert total >= 5


def test_get_sessions_with_session_name_filter(oracle_db_real):
    """Test getting sessions filtered by (case-insensitive) session_name, via JSON_VALUE + LIKE"""
    session = AgentSession(
        session_id="test-name-filter-session",
        agent_id="test-agent",
        session_data={"session_name": "My Custom Session Name"},
        created_at=int(time.time()),
    )
    oracle_db_real.upsert_session(session)

    matches, total = oracle_db_real.get_sessions(
        session_type=SessionType.AGENT, session_name="custom session", deserialize=False
    )
    assert total >= 1
    assert any(s["session_id"] == "test-name-filter-session" for s in matches)


def test_rename_session(oracle_db_real):
    """Test renaming a session"""
    session = AgentSession(
        session_id="test-rename-session",
        agent_id="test-agent",
        session_data={"session_name": "Old Name"},
        created_at=int(time.time()),
    )

    oracle_db_real.upsert_session(session)

    # Rename the session
    renamed = oracle_db_real.rename_session(
        session_id="test-rename-session", session_type=SessionType.AGENT, session_name="New Name"
    )

    assert renamed is not None
    assert renamed.session_data.get("session_name") == "New Name"


def test_upsert_sessions(oracle_db_real):
    """Test upsert_sessions with mixed session types (Agent, Team, Workflow)"""
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
    results = oracle_db_real.upsert_sessions(sessions)

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


def test_upsert_sessions_update(oracle_db_real):
    """Test upsert_sessions correctly updates existing sessions"""
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
    oracle_db_real.upsert_sessions([session1, session2])

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
    results = oracle_db_real.upsert_sessions([updated_session1, updated_session2])
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


def test_get_sessions_without_type_returns_all(oracle_db_real):
    """get_sessions(session_type=None) returns agent, team, and workflow sessions together."""
    agent = AgentSession(session_id="none-type-agent", agent_id="a1", user_id="u1", created_at=int(time.time()))
    team = TeamSession(session_id="none-type-team", team_id="t1", user_id="u1", created_at=int(time.time()))
    workflow = WorkflowSession(session_id="none-type-wf", workflow_id="w1", user_id="u1")

    oracle_db_real.upsert_session(agent)
    oracle_db_real.upsert_session(team)
    oracle_db_real.upsert_session(workflow)

    # session_type=None should return all three
    sessions_raw, total_count = oracle_db_real.get_sessions(session_type=None, deserialize=False)
    assert total_count >= 3
    session_ids = {s["session_id"] for s in sessions_raw}
    assert "none-type-agent" in session_ids
    assert "none-type-team" in session_ids
    assert "none-type-wf" in session_ids

    # Deserialized path should auto-detect correct types
    sessions = oracle_db_real.get_sessions(session_type=None)
    assert len(sessions) >= 3
    types = {type(s) for s in sessions}
    assert AgentSession in types
    assert TeamSession in types
    assert WorkflowSession in types


def test_get_session_without_type_auto_detects(oracle_db_real):
    """get_session(session_type=None) auto-detects the correct session type for deserialization."""
    agent = AgentSession(session_id="auto-detect-agent", agent_id="a1", created_at=int(time.time()))
    team = TeamSession(session_id="auto-detect-team", team_id="t1", created_at=int(time.time()))

    oracle_db_real.upsert_session(agent)
    oracle_db_real.upsert_session(team)

    result = oracle_db_real.get_session(session_id="auto-detect-agent", session_type=None)
    assert result is not None
    assert isinstance(result, AgentSession)

    result = oracle_db_real.get_session(session_id="auto-detect-team", session_type=None)
    assert result is not None
    assert isinstance(result, TeamSession)


# -- Oracle-specific extra cases --


def test_upsert_session_merge_is_idempotent(oracle_db_real):
    """Upserting the exact same session twice via MERGE must not duplicate the row."""
    session = AgentSession(
        session_id="test-merge-idempotent-session",
        agent_id="test-agent",
        user_id="test-user",
        session_data={"key": "value"},
        created_at=int(time.time()),
    )

    oracle_db_real.upsert_session(session)
    oracle_db_real.upsert_session(session)

    sessions_raw, total_count = oracle_db_real.get_sessions(session_type=SessionType.AGENT, deserialize=False)
    matching = [s for s in sessions_raw if s["session_id"] == "test-merge-idempotent-session"]
    assert len(matching) == 1


def test_upsert_session_ownership_check_rejects_divergent_user_id(oracle_db_real):
    """upsert_session must refuse to hijack a session owned by a different user_id."""
    original = AgentSession(
        session_id="test-ownership-session",
        agent_id="test-agent",
        user_id="alice",
        session_data={"owner": "alice"},
        created_at=int(time.time()),
    )
    result = oracle_db_real.upsert_session(original)
    assert result is not None
    assert result.user_id == "alice"

    hijack_attempt = AgentSession(
        session_id="test-ownership-session",
        agent_id="test-agent",
        user_id="bob",
        session_data={"owner": "bob"},
        created_at=int(time.time()),
    )
    hijack_result = oracle_db_real.upsert_session(hijack_attempt)
    assert hijack_result is None

    # Original row must be untouched
    retrieved = oracle_db_real.get_session(session_id="test-ownership-session", session_type=SessionType.AGENT)
    assert retrieved is not None
    assert retrieved.user_id == "alice"
    assert retrieved.session_data.get("owner") == "alice"


def test_upsert_sessions_bulk_does_not_reassign_owner(oracle_db_real):
    """Bulk upsert must not update (nor reassign) a session owned by another user."""
    session = AgentSession(
        session_id="test-bulk-owner-guard",
        agent_id="test-agent",
        user_id="owner-user",
        session_data={"original": True},
        created_at=int(time.time()),
    )
    assert oracle_db_real.upsert_session(session) is not None

    hijack = AgentSession(
        session_id="test-bulk-owner-guard",
        agent_id="test-agent",
        user_id="other-user",
        session_data={"hijacked": True},
        created_at=int(time.time()),
    )
    results = oracle_db_real.upsert_sessions([hijack])
    assert results == []

    retrieved = oracle_db_real.get_session(session_id="test-bulk-owner-guard", session_type=SessionType.AGENT)
    assert retrieved is not None
    assert retrieved.user_id == "owner-user"
    assert (retrieved.session_data or {}).get("original") is True
    assert "hijacked" not in (retrieved.session_data or {})


def test_upsert_sessions_bulk_same_owner_updates(oracle_db_real):
    """Bulk upsert still updates rows that belong to the same user."""
    session = AgentSession(
        session_id="test-bulk-owner-update",
        agent_id="test-agent",
        user_id="owner-user",
        session_data={"version": 1},
        created_at=int(time.time()),
    )
    assert oracle_db_real.upsert_session(session) is not None

    session.session_data = {"version": 2}
    results = oracle_db_real.upsert_sessions([session])
    assert len(results) == 1
    assert (results[0].session_data or {}).get("version") == 2


def test_upsert_session_concurrent_first_save_retries(oracle_db_real):
    """Two concurrent first saves of the same new session race into the MERGE's
    insert branch; the loser hits ORA-00001 and must retry onto the update branch
    instead of dropping the session."""
    warmup = WorkflowSession(
        session_id="test-race-warmup",
        workflow_id="test-workflow",
        user_id="test-user",
        created_at=int(time.time()),
    )
    assert oracle_db_real.upsert_session(warmup) is not None

    session = WorkflowSession(
        session_id="test-race-session",
        workflow_id="test-workflow",
        user_id="test-user",
        created_at=int(time.time()),
    )
    results = {}
    barrier = threading.Barrier(2)

    def save(worker: str) -> None:
        barrier.wait()
        results[worker] = oracle_db_real.upsert_session(session)

    threads = [threading.Thread(target=save, args=(worker,)) for worker in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results["a"] is not None
    assert results["b"] is not None

    persisted = oracle_db_real.get_session("test-race-session", session_type=SessionType.WORKFLOW)
    assert persisted is not None
