"""Tests that sessions with the same session_id but different session_types
are stored independently and do not overwrite each other.

Regression tests for https://github.com/agno-agi/agno/issues/6733
"""

import time

import pytest

from agno.db.base import SessionType
from agno.db.sqlite.sqlite import SqliteDb
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession


@pytest.fixture
def db(tmp_path):
    """Create a SQLite database in a temporary directory."""
    db = SqliteDb(db_url=f"sqlite:///{tmp_path}/test.db")
    return db


def _now():
    return int(time.time())


class TestSessionTypeIsolation:
    """Verify that Agent, Team, and Workflow sessions with the same
    session_id coexist independently in the database."""

    def test_agent_and_team_same_session_id(self, db):
        """An AgentSession upsert must NOT overwrite an existing TeamSession
        that has the same session_id."""
        shared_id = "shared-session-001"

        # 1. Upsert a TeamSession
        team_session = TeamSession(
            session_id=shared_id,
            team_id="team-alpha",
            session_data={"note": "team data"},
            created_at=_now(),
        )
        result = db.upsert_session(team_session)
        assert result is not None
        assert isinstance(result, TeamSession)
        assert result.team_id == "team-alpha"

        # 2. Upsert an AgentSession with the SAME session_id
        agent_session = AgentSession(
            session_id=shared_id,
            agent_id="agent-beta",
            session_data={"note": "agent data"},
            created_at=_now(),
        )
        result = db.upsert_session(agent_session)
        assert result is not None
        assert isinstance(result, AgentSession)
        assert result.agent_id == "agent-beta"

        # 3. Verify the TeamSession is still intact
        team_result = db.get_session(shared_id, SessionType.TEAM)
        assert team_result is not None
        assert isinstance(team_result, TeamSession)
        assert team_result.team_id == "team-alpha"
        assert team_result.session_data["note"] == "team data"

        # 4. Verify the AgentSession is also intact
        agent_result = db.get_session(shared_id, SessionType.AGENT)
        assert agent_result is not None
        assert isinstance(agent_result, AgentSession)
        assert agent_result.agent_id == "agent-beta"
        assert agent_result.session_data["note"] == "agent data"

    def test_all_three_types_same_session_id(self, db):
        """Agent, Team, and Workflow sessions should all coexist with
        the same session_id."""
        shared_id = "shared-session-002"
        ts = _now()

        db.upsert_session(AgentSession(session_id=shared_id, agent_id="a1", created_at=ts))
        db.upsert_session(TeamSession(session_id=shared_id, team_id="t1", created_at=ts))
        db.upsert_session(WorkflowSession(session_id=shared_id, workflow_id="w1", created_at=ts))

        agent_result = db.get_session(shared_id, SessionType.AGENT)
        team_result = db.get_session(shared_id, SessionType.TEAM)
        workflow_result = db.get_session(shared_id, SessionType.WORKFLOW)

        assert isinstance(agent_result, AgentSession)
        assert agent_result.agent_id == "a1"

        assert isinstance(team_result, TeamSession)
        assert team_result.team_id == "t1"

        assert isinstance(workflow_result, WorkflowSession)
        assert workflow_result.workflow_id == "w1"

    def test_upsert_updates_correct_session_type(self, db):
        """Updating an AgentSession should not affect a TeamSession with
        the same session_id."""
        shared_id = "shared-session-003"
        ts = _now()

        # Create both
        db.upsert_session(
            TeamSession(
                session_id=shared_id,
                team_id="t1",
                session_data={"note": "original team"},
                created_at=ts,
            )
        )
        db.upsert_session(
            AgentSession(
                session_id=shared_id,
                agent_id="a1",
                session_data={"note": "original agent"},
                created_at=ts,
            )
        )

        # Update only the AgentSession
        db.upsert_session(
            AgentSession(
                session_id=shared_id,
                agent_id="a1",
                session_data={"note": "updated agent"},
                created_at=ts,
            )
        )

        # Team session must be unchanged
        team_result = db.get_session(shared_id, SessionType.TEAM)
        assert isinstance(team_result, TeamSession)
        assert team_result.session_data["note"] == "original team"

        # Agent session must be updated
        agent_result = db.get_session(shared_id, SessionType.AGENT)
        assert isinstance(agent_result, AgentSession)
        assert agent_result.session_data["note"] == "updated agent"

    def test_bulk_upsert_preserves_isolation(self, db):
        """Bulk upsert of agent sessions should not overwrite team sessions
        with the same session_ids."""
        shared_id = "shared-session-005"
        ts = _now()

        # Create a team session first
        db.upsert_session(
            TeamSession(
                session_id=shared_id,
                team_id="t1",
                session_data={"note": "team data"},
                created_at=ts,
            )
        )

        # Bulk upsert agent sessions including one with the same session_id
        agent_sessions = [
            AgentSession(session_id=shared_id, agent_id="a1", created_at=ts),
            AgentSession(session_id="unique-agent-session", agent_id="a2", created_at=ts),
        ]
        db.upsert_sessions(agent_sessions)

        # Team session must be preserved
        team_result = db.get_session(shared_id, SessionType.TEAM)
        assert team_result is not None
        assert isinstance(team_result, TeamSession)
        assert team_result.session_data["note"] == "team data"
