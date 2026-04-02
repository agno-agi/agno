"""Unit tests for the session_type=None ("All" filter) feature in PR #7217.

Tests cover:
- GET /sessions with no type returns all session types
- GET /sessions with explicit type filters correctly
- GET /sessions/{id} auto-detects session type
- GET /sessions/{id}/runs auto-detects session type
- component_id filtering with type=None (OR across agent_id/team_id/workflow_id)
- SessionSchema includes session_type field
- Pagination and sorting with mixed types
- Error cases (404, 422)
"""

import time
import uuid

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession


def _build_client(db):
    from agno.os.routers.session.session import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(router, {"default": [db]})
    app.include_router(router)
    return TestClient(app)


def _get_data(response):
    body = response.json()
    if isinstance(body, dict) and "data" in body:
        return body["data"], body.get("meta", {})
    return body, {}


@pytest.fixture
def db_with_sessions():
    """Create an InMemoryDb with one session of each type."""
    db = InMemoryDb()
    uid = uuid.uuid4().hex[:8]
    now = int(time.time())

    agent_session = AgentSession(
        session_id=f"agent-{uid}",
        agent_id="test-agent",
        user_id="user-1",
        session_data={"session_name": "Agent Chat"},
        created_at=now,
        updated_at=now,
        runs=[
            RunOutput(
                run_id=f"run-a-{uid}",
                agent_id="test-agent",
                user_id="user-1",
                status=RunStatus.completed,
                messages=[],
                created_at=now,
            )
        ],
    )
    agent_session.runs[0].content = "Agent response"

    team_session = TeamSession(
        session_id=f"team-{uid}",
        team_id="test-team",
        user_id="user-1",
        session_data={"session_name": "Team Chat"},
        created_at=now + 1,
        updated_at=now + 1,
        runs=[
            TeamRunOutput(
                run_id=f"run-t-{uid}",
                team_id="test-team",
                user_id="user-1",
                status=RunStatus.completed,
                messages=[],
                created_at=now + 1,
            )
        ],
    )
    team_session.runs[0].content = "Team response"

    workflow_session = WorkflowSession(
        session_id=f"wf-{uid}",
        workflow_id="test-workflow",
        user_id="user-1",
        session_data={"session_name": "Workflow Run"},
        created_at=now + 2,
        updated_at=now + 2,
    )

    db.upsert_session(agent_session)
    db.upsert_session(team_session)
    db.upsert_session(workflow_session)

    return db, agent_session, team_session, workflow_session


class TestGetSessionsNoType:
    """GET /sessions without type parameter returns all session types."""

    def test_returns_all_three_types(self, db_with_sessions):
        db, agent_s, team_s, wf_s = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?user_id=user-1")
        assert resp.status_code == 200

        data, meta = _get_data(resp)
        session_ids = {s["session_id"] for s in data}
        assert agent_s.session_id in session_ids
        assert team_s.session_id in session_ids
        assert wf_s.session_id in session_ids

    def test_response_includes_session_type_field(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?user_id=user-1")
        data, _ = _get_data(resp)

        types_found = {s.get("session_type") for s in data}
        assert types_found == {"agent", "team", "workflow"}

    def test_response_includes_component_ids(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?user_id=user-1")
        data, _ = _get_data(resp)

        agent_ids = [s.get("agent_id") for s in data if s.get("agent_id")]
        team_ids = [s.get("team_id") for s in data if s.get("team_id")]
        workflow_ids = [s.get("workflow_id") for s in data if s.get("workflow_id")]
        assert len(agent_ids) >= 1
        assert len(team_ids) >= 1
        assert len(workflow_ids) >= 1


class TestGetSessionsWithType:
    """GET /sessions?type=X filters correctly."""

    def test_type_agent_returns_only_agents(self, db_with_sessions):
        db, agent_s, team_s, wf_s = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?type=agent&user_id=user-1")
        assert resp.status_code == 200

        data, _ = _get_data(resp)
        session_ids = {s["session_id"] for s in data}
        assert agent_s.session_id in session_ids
        assert team_s.session_id not in session_ids
        assert wf_s.session_id not in session_ids

    def test_type_team_returns_only_teams(self, db_with_sessions):
        db, agent_s, team_s, wf_s = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?type=team&user_id=user-1")
        data, _ = _get_data(resp)
        session_ids = {s["session_id"] for s in data}
        assert team_s.session_id in session_ids
        assert agent_s.session_id not in session_ids

    def test_type_workflow_returns_only_workflows(self, db_with_sessions):
        db, agent_s, _, wf_s = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?type=workflow&user_id=user-1")
        data, _ = _get_data(resp)
        session_ids = {s["session_id"] for s in data}
        assert wf_s.session_id in session_ids
        assert agent_s.session_id not in session_ids

    def test_invalid_type_returns_422(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?type=invalid")
        assert resp.status_code == 422


class TestGetSessionByIdAutoDetect:
    """GET /sessions/{id} auto-detects session type when no type param is provided."""

    def test_auto_detect_agent_session(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get(f"/sessions/{agent_s.session_id}?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == agent_s.session_id
        assert "agent_id" in data

    def test_auto_detect_team_session(self, db_with_sessions):
        db, _, team_s, _ = db_with_sessions
        client = _build_client(db)

        resp = client.get(f"/sessions/{team_s.session_id}?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == team_s.session_id

    def test_auto_detect_workflow_session(self, db_with_sessions):
        db, _, _, wf_s = db_with_sessions
        client = _build_client(db)

        resp = client.get(f"/sessions/{wf_s.session_id}?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == wf_s.session_id

    def test_nonexistent_session_returns_404(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions/nonexistent-id?user_id=user-1")
        assert resp.status_code == 404

    def test_explicit_type_still_works(self, db_with_sessions):
        db, _, team_s, _ = db_with_sessions
        client = _build_client(db)

        resp = client.get(f"/sessions/{team_s.session_id}?type=team&user_id=user-1")
        assert resp.status_code == 200


class TestGetSessionRunsAutoDetect:
    """GET /sessions/{id}/runs auto-detects session type."""

    def test_agent_session_runs(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get(f"/sessions/{agent_s.session_id}/runs?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["run_id"].startswith("run-a-")

    def test_team_session_runs(self, db_with_sessions):
        db, _, team_s, _ = db_with_sessions
        client = _build_client(db)

        resp = client.get(f"/sessions/{team_s.session_id}/runs?user_id=user-1")
        assert resp.status_code == 200

    def test_session_with_no_runs(self, db_with_sessions):
        db, _, _, wf_s = db_with_sessions
        client = _build_client(db)

        resp = client.get(f"/sessions/{wf_s.session_id}/runs?user_id=user-1")
        assert resp.status_code == 200
        assert resp.json() == []


class TestComponentIdFilter:
    """component_id filter works with and without type parameter."""

    def test_component_id_with_type_none(self, db_with_sessions):
        db, agent_s, team_s, wf_s = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?component_id=test-agent&user_id=user-1")
        assert resp.status_code == 200
        data, _ = _get_data(resp)
        session_ids = {s["session_id"] for s in data}
        assert agent_s.session_id in session_ids
        assert team_s.session_id not in session_ids
        assert wf_s.session_id not in session_ids

    def test_component_id_with_explicit_type(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?type=agent&component_id=test-agent&user_id=user-1")
        assert resp.status_code == 200
        data, _ = _get_data(resp)
        assert len(data) >= 1
        assert all(s.get("agent_id") == "test-agent" for s in data)

    def test_component_id_no_match(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?component_id=nonexistent&user_id=user-1")
        assert resp.status_code == 200
        data, _ = _get_data(resp)
        assert len(data) == 0


class TestPaginationAndSorting:
    """Pagination and sorting work with mixed session types."""

    def test_pagination_limit(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?user_id=user-1&limit=2")
        assert resp.status_code == 200
        data, meta = _get_data(resp)
        assert len(data) <= 2
        assert meta.get("total_count", 0) >= 3

    def test_sort_desc(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?user_id=user-1&sort_by=created_at&sort_order=desc")
        assert resp.status_code == 200
        data, _ = _get_data(resp)
        assert len(data) >= 3


class TestSessionCRUD:
    """POST and DELETE work with optional session_type."""

    def test_create_agent_session(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.post(
            "/sessions?type=agent",
            json={"user_id": "user-1", "agent_id": "new-agent", "session_name": "New Session"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data.get("session_id")

    def test_create_team_session(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.post(
            "/sessions?type=team",
            json={"user_id": "user-1", "team_id": "new-team"},
        )
        assert resp.status_code == 201

    def test_delete_session(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.delete(f"/sessions/{agent_s.session_id}?type=agent&user_id=user-1")
        assert resp.status_code == 204

        # Verify deleted
        resp = client.get(f"/sessions/{agent_s.session_id}?user_id=user-1")
        assert resp.status_code == 404


class TestSessionSchema:
    """SessionSchema correctly includes session_type and component IDs."""

    def test_session_type_inferred_from_agent_id(self):
        from agno.os.schema import SessionSchema

        schema = SessionSchema.from_dict(
            {"session_id": "s1", "agent_id": "a1", "session_data": {"session_name": "Test"}, "created_at": 0}
        )
        assert schema.session_type == "agent"
        assert schema.agent_id == "a1"

    def test_session_type_inferred_from_team_id(self):
        from agno.os.schema import SessionSchema

        schema = SessionSchema.from_dict(
            {"session_id": "s2", "team_id": "t1", "session_data": {"session_name": "Test"}, "created_at": 0}
        )
        assert schema.session_type == "team"
        assert schema.team_id == "t1"

    def test_session_type_inferred_from_workflow_id(self):
        from agno.os.schema import SessionSchema

        schema = SessionSchema.from_dict(
            {"session_id": "s3", "workflow_id": "w1", "session_data": {"session_name": "Test"}, "created_at": 0}
        )
        assert schema.session_type == "workflow"
        assert schema.workflow_id == "w1"

    def test_session_type_from_explicit_field(self):
        from agno.db.base import SessionType
        from agno.os.schema import SessionSchema

        schema = SessionSchema.from_dict(
            {
                "session_id": "s4",
                "session_type": SessionType.TEAM,
                "team_id": "t1",
                "session_data": {"session_name": "Test"},
                "created_at": 0,
            }
        )
        assert schema.session_type == "team"


class TestBackwardsCompatibility:
    """Sessions created by older SDK versions without session_type field should still work."""

    def test_old_sessions_without_session_type_field(self):
        """Sessions from older SDK that lack session_type should be inferred from component IDs."""
        db = InMemoryDb()
        uid = uuid.uuid4().hex[:8]

        # Simulate old SDK sessions: no session_type field, only agent_id/team_id
        db._sessions.append(
            {
                "session_id": f"old-agent-{uid}",
                "agent_id": "legacy-agent",
                "user_id": "user-1",
                "session_data": {"session_name": "Old Agent Session"},
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }
        )
        db._sessions.append(
            {
                "session_id": f"old-team-{uid}",
                "team_id": "legacy-team",
                "user_id": "user-1",
                "session_data": {"session_name": "Old Team Session"},
                "created_at": int(time.time()) + 1,
                "updated_at": int(time.time()) + 1,
            }
        )

        client = _build_client(db)

        # type=None should return both old sessions
        resp = client.get("/sessions?user_id=user-1")
        assert resp.status_code == 200
        data, _ = _get_data(resp)
        session_ids = {s["session_id"] for s in data}
        assert f"old-agent-{uid}" in session_ids
        assert f"old-team-{uid}" in session_ids

        # session_type should be inferred in the response
        types = {s["session_id"]: s.get("session_type") for s in data}
        assert types[f"old-agent-{uid}"] == "agent"
        assert types[f"old-team-{uid}"] == "team"
