"""
Tests for session_type update during upsert operations.

This test reproduces the bug from production where:
1. A session is created with type=agent
2. Later, a team uses the same session_id
3. The session_type doesn't get updated to 'team'
4. GET /sessions/{id}/runs?type=team returns 404 because PostgresDb filters by session_type

The fix: Include session_type in the on_conflict_do_update clause.
"""

import time
import tempfile
import uuid

import pytest
from sqlalchemy import select

from agno.db.sqlite import SqliteDb
from agno.db.base import SessionType
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession


@pytest.fixture
def sqlite_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    table_name = f"sessions_{uuid.uuid4().hex[:8]}"
    db = SqliteDb(session_table=table_name, db_file=db_path)
    yield db


def get_session_with_type_filter(db: SqliteDb, session_id: str, session_type: SessionType):
    """
    Simulate PostgresDb.get_session() behavior which filters by session_type.
    SQLite's get_session doesn't filter by session_type in SQL, but PostgresDb does.
    This is where the 404 bug manifests.
    """
    table = db._get_table(table_type="sessions")
    with db.Session() as sess:
        stmt = select(table).where(table.c.session_id == session_id)
        stmt = stmt.where(table.c.session_type == session_type.value)
        result = sess.execute(stmt).fetchone()
        if result is None:
            return None
        return dict(result._mapping)


def get_raw_session(db: SqliteDb, session_id: str):
    """Get raw session data without any filtering."""
    table = db._get_table(table_type="sessions")
    with db.Session() as sess:
        stmt = select(table).where(table.c.session_id == session_id)
        result = sess.execute(stmt).fetchone()
        if result is None:
            return None
        return dict(result._mapping)


class TestSessionType404Bug:
    """
    Tests that reproduce and verify the fix for the 404 bug.
    
    Bug scenario from production logs:
    - POST /teams/customer_support_team/runs 200 OK (creates/updates session)
    - GET /sessions/{id}/runs?type=team 404 Not Found
    
    Root cause: session_type wasn't being updated during on_conflict_do_update
    """

    def test_agent_to_team_session_type_update(self, sqlite_db: SqliteDb):
        """
        Reproduce the exact production bug:
        1. Agent creates session (session_type=agent)
        2. Team uses same session_id (should update session_type=team)
        3. GET with type=team should return 200, not 404
        """
        session_id = "mobile_session_chase.s@millieclinic.com"
        user_id = "chase.s@millieclinic.com"
        now = int(time.time())

        # Step 1: Agent creates a session first
        agent_session = AgentSession(
            session_id=session_id,
            agent_id="some-agent",
            user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        sqlite_db.upsert_session(agent_session)

        # Verify agent session was created with type=agent
        raw = get_raw_session(sqlite_db, session_id)
        assert raw is not None
        assert raw["session_type"] == "agent"

        # Step 2: Team uses the same session_id (upserts)
        team_session = TeamSession(
            session_id=session_id,
            team_id="customer_support_team",
            user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        sqlite_db.upsert_session(team_session)

        # Step 3: Verify session_type was updated to 'team'
        raw = get_raw_session(sqlite_db, session_id)
        assert raw is not None
        assert raw["session_type"] == "team", (
            f"BUG: session_type is '{raw['session_type']}' but should be 'team'. "
            "This would cause 404 when querying with type=team"
        )

        # Step 4: Simulate PostgresDb query with type=team filter (this is where 404 happens)
        result = get_session_with_type_filter(sqlite_db, session_id, SessionType.TEAM)
        assert result is not None, (
            "404 BUG: Session not found when querying with type=team. "
            "This is the exact bug from production logs."
        )

    def test_team_to_agent_session_type_update(self, sqlite_db: SqliteDb):
        """Test that session_type is updated when changing from team to agent."""
        session_id = f"test_session_{uuid.uuid4().hex[:8]}"
        now = int(time.time())

        # Create team session first
        team_session = TeamSession(
            session_id=session_id,
            team_id="test-team",
            user_id="test-user",
            created_at=now,
            updated_at=now,
        )
        sqlite_db.upsert_session(team_session)

        # Verify team session type
        raw = get_raw_session(sqlite_db, session_id)
        assert raw["session_type"] == "team"

        # Upsert agent session with same ID
        agent_session = AgentSession(
            session_id=session_id,
            agent_id="test-agent",
            user_id="test-user",
            created_at=now,
            updated_at=now,
        )
        sqlite_db.upsert_session(agent_session)

        # Verify session_type was updated to 'agent'
        raw = get_raw_session(sqlite_db, session_id)
        assert raw["session_type"] == "agent"

        # Query with type=agent should work
        result = get_session_with_type_filter(sqlite_db, session_id, SessionType.AGENT)
        assert result is not None

    def test_agent_to_workflow_session_type_update(self, sqlite_db: SqliteDb):
        """Test that session_type is updated when changing from agent to workflow."""
        session_id = f"test_session_{uuid.uuid4().hex[:8]}"
        now = int(time.time())

        # Create agent session first
        agent_session = AgentSession(
            session_id=session_id,
            agent_id="test-agent",
            user_id="test-user",
            created_at=now,
            updated_at=now,
        )
        sqlite_db.upsert_session(agent_session)

        # Upsert workflow session with same ID
        workflow_session = WorkflowSession(
            session_id=session_id,
            workflow_id="test-workflow",
            user_id="test-user",
            created_at=now,
            updated_at=now,
        )
        sqlite_db.upsert_session(workflow_session)

        # Verify session_type was updated to 'workflow'
        raw = get_raw_session(sqlite_db, session_id)
        assert raw["session_type"] == "workflow"

        # Query with type=workflow should work
        result = get_session_with_type_filter(sqlite_db, session_id, SessionType.WORKFLOW)
        assert result is not None

    def test_same_type_upsert_preserves_session_type(self, sqlite_db: SqliteDb):
        """Test that upserting the same session type preserves the session_type."""
        session_id = f"test_session_{uuid.uuid4().hex[:8]}"
        now = int(time.time())

        # Create agent session
        agent_session = AgentSession(
            session_id=session_id,
            agent_id="test-agent",
            user_id="test-user",
            created_at=now,
            updated_at=now,
        )
        sqlite_db.upsert_session(agent_session)

        # Upsert another agent session with same ID
        updated_agent_session = AgentSession(
            session_id=session_id,
            agent_id="test-agent-updated",
            user_id="test-user",
            created_at=now,
            updated_at=now,
        )
        sqlite_db.upsert_session(updated_agent_session)

        # Verify session_type is still 'agent' and agent_id was updated
        raw = get_raw_session(sqlite_db, session_id)
        assert raw["session_type"] == "agent"
        assert raw["agent_id"] == "test-agent-updated"

