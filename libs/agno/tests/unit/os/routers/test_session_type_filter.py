"""Unit tests for optional session_type filtering in the session router."""

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


def _seed_session(db: InMemoryDb, session: dict) -> None:
    """Insert a raw session dict directly into InMemoryDb's session store."""
    db._sessions[session["session_id"]] = session


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
        created_times = [s.get("created_at") for s in data if s.get("created_at")]
        if len(created_times) >= 2:
            assert created_times[0] >= created_times[-1]


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


class TestBackwardsCompatibility:
    """Sessions created by older SDK versions without session_type field should still work."""

    def test_old_sessions_without_session_type_field(self):
        """Sessions from older SDK that lack session_type should be inferred from component IDs."""
        db = InMemoryDb()
        uid = uuid.uuid4().hex[:8]

        # Simulate old SDK sessions: no session_type field, only agent_id/team_id
        _seed_session(
            db,
            {
                "session_id": f"old-agent-{uid}",
                "agent_id": "legacy-agent",
                "user_id": "user-1",
                "session_data": {"session_name": "Old Agent Session"},
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            },
        )
        _seed_session(
            db,
            {
                "session_id": f"old-team-{uid}",
                "team_id": "legacy-team",
                "user_id": "user-1",
                "session_data": {"session_name": "Old Team Session"},
                "created_at": int(time.time()) + 1,
                "updated_at": int(time.time()) + 1,
            },
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


class TestGetSessionRunById:
    """GET /sessions/{session_id}/runs/{run_id} endpoint tests."""

    def test_get_specific_agent_run(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)
        run_id = agent_s.runs[0].run_id

        resp = client.get(f"/sessions/{agent_s.session_id}/runs/{run_id}?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data.get("agent_id") == "test-agent"

    def test_get_specific_team_run(self, db_with_sessions):
        db, _, team_s, _ = db_with_sessions
        client = _build_client(db)
        run_id = team_s.runs[0].run_id

        resp = client.get(f"/sessions/{team_s.session_id}/runs/{run_id}?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data.get("team_id") == "test-team"

    def test_nonexistent_run_returns_404(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get(f"/sessions/{agent_s.session_id}/runs/nonexistent-run?user_id=user-1")
        assert resp.status_code == 404

    def test_nonexistent_session_returns_404(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions/nonexistent-session/runs/some-run?user_id=user-1")
        assert resp.status_code == 404

    def test_session_with_no_runs_returns_404(self, db_with_sessions):
        db, _, _, wf_s = db_with_sessions
        client = _build_client(db)

        resp = client.get(f"/sessions/{wf_s.session_id}/runs/any-run?user_id=user-1")
        assert resp.status_code == 404

    def test_run_type_auto_detected_from_run_fields(self):
        """Run type detection uses run's own fields (workflow_id > team_id > agent_id)."""
        db = InMemoryDb()
        now = int(time.time())
        uid = uuid.uuid4().hex[:8]

        # Insert a raw session with mixed run types directly
        _seed_session(
            db,
            {
                "session_id": f"mixed-{uid}",
                "agent_id": "a1",
                "user_id": "user-1",
                "session_type": "agent",
                "session_data": {"session_name": "Mixed Runs"},
                "created_at": now,
                "updated_at": now,
                "runs": [
                    {"run_id": "run-agent", "agent_id": "a1", "created_at": now},
                    {"run_id": "run-team", "team_id": "t1", "created_at": now},
                    {"run_id": "run-workflow", "workflow_id": "w1", "created_at": now},
                ],
            },
        )

        client = _build_client(db)

        # Agent run should return RunSchema (has agent_id, no workflow_id/team_id)
        resp = client.get(f"/sessions/mixed-{uid}/runs/run-agent?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("agent_id") == "a1"

        # Team run should return TeamRunSchema
        resp = client.get(f"/sessions/mixed-{uid}/runs/run-team?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("team_id") == "t1"

        # Workflow run should return WorkflowRunSchema
        resp = client.get(f"/sessions/mixed-{uid}/runs/run-workflow?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("workflow_id") == "w1"


class TestRunTimestampFiltering:
    """GET /sessions/{id}/runs with created_after/created_before filters."""

    def test_both_timestamp_filters(self):
        db = InMemoryDb()
        now = int(time.time())
        uid = uuid.uuid4().hex[:8]

        agent_session = AgentSession(
            session_id=f"ts3-{uid}",
            agent_id="test-agent",
            user_id="user-1",
            session_data={"session_name": "Timestamp Test 3"},
            created_at=now - 200,
            updated_at=now,
            runs=[
                RunOutput(
                    run_id="very-old",
                    agent_id="test-agent",
                    status=RunStatus.completed,
                    messages=[],
                    created_at=now - 100,
                ),
                RunOutput(
                    run_id="middle",
                    agent_id="test-agent",
                    status=RunStatus.completed,
                    messages=[],
                    created_at=now - 50,
                ),
                RunOutput(
                    run_id="very-new",
                    agent_id="test-agent",
                    status=RunStatus.completed,
                    messages=[],
                    created_at=now,
                ),
            ],
        )
        db.upsert_session(agent_session)
        client = _build_client(db)

        resp = client.get(f"/sessions/ts3-{uid}/runs?user_id=user-1&created_after={now - 75}&created_before={now - 25}")
        assert resp.status_code == 200
        data = resp.json()
        run_ids = [r["run_id"] for r in data]
        assert run_ids == ["middle"]


def _seed_agent_session_with_runs(db: InMemoryDb, session_id: str, count: int, start_at: int = 1_700_000_000) -> None:
    _seed_session(
        db,
        {
            "session_id": session_id,
            "agent_id": "test-agent",
            "user_id": "user-1",
            "session_type": "agent",
            "session_data": {"session_name": "Paginated Runs"},
            "created_at": start_at,
            "updated_at": start_at,
            "runs": [
                {
                    "run_id": f"run-{i}",
                    "agent_id": "test-agent",
                    "status": "COMPLETED",
                    "created_at": start_at + i,
                    "input": {"input_content": f"question {i}"},
                }
                for i in range(count)
            ],
        },
    )


class TestSessionRunsPagination:
    """GET /sessions/{id}/runs pagination is opt-in via limit and pages by run_index."""

    @pytest.fixture
    def client(self):
        db = InMemoryDb()
        _seed_agent_session_with_runs(db, "paged", count=5)
        return _build_client(db)

    def test_no_params_returns_bare_list_with_run_index(self, client):
        resp = client.get("/sessions/paged/runs?user_id=user-1")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert [(r["run_id"], r["run_index"]) for r in body] == [(f"run-{i}", i) for i in range(5)]

    def test_limit_returns_newest_runs_in_chronological_order(self, client):
        resp = client.get("/sessions/paged/runs?user_id=user-1&limit=2")
        assert resp.status_code == 200
        body = resp.json()
        assert [r["run_index"] for r in body["data"]] == [3, 4]
        assert body["meta"] == {
            "limit": 2,
            "total_count": 5,
            "has_more": True,
            "oldest_run_index": 3,
            "newest_run_index": 4,
        }

    def test_before_run_index_pages_back_to_the_start(self, client):
        resp = client.get("/sessions/paged/runs?user_id=user-1&limit=2&before_run_index=3")
        body = resp.json()
        assert [r["run_index"] for r in body["data"]] == [1, 2]
        assert body["meta"]["has_more"] is True

        resp = client.get("/sessions/paged/runs?user_id=user-1&limit=2&before_run_index=1")
        body = resp.json()
        assert [r["run_index"] for r in body["data"]] == [0]
        assert body["meta"]["has_more"] is False

    def test_after_run_index_pages_forward(self, client):
        resp = client.get("/sessions/paged/runs?user_id=user-1&limit=2&after_run_index=0")
        body = resp.json()
        assert [r["run_index"] for r in body["data"]] == [1, 2]
        assert body["meta"]["has_more"] is True

        resp = client.get("/sessions/paged/runs?user_id=user-1&limit=2&after_run_index=2")
        body = resp.json()
        assert [r["run_index"] for r in body["data"]] == [3, 4]
        assert body["meta"]["has_more"] is False

    def test_limit_larger_than_session_has_no_more(self, client):
        body = client.get("/sessions/paged/runs?user_id=user-1&limit=50").json()
        assert len(body["data"]) == 5
        assert body["meta"]["has_more"] is False

    def test_both_cursors_rejected(self, client):
        resp = client.get("/sessions/paged/runs?user_id=user-1&limit=2&before_run_index=3&after_run_index=0")
        assert resp.status_code == 422

    @pytest.mark.parametrize("cursor", ["before_run_index=3", "after_run_index=0"])
    def test_cursor_without_limit_rejected(self, client, cursor):
        resp = client.get(f"/sessions/paged/runs?user_id=user-1&{cursor}")
        assert resp.status_code == 422

    def test_run_index_is_stable_under_filters(self):
        """run_index is the position in the full history, not in the filtered result."""
        db = InMemoryDb()
        _seed_agent_session_with_runs(db, "filtered", count=5, start_at=1_700_000_000)
        client = _build_client(db)

        body = client.get("/sessions/filtered/runs?user_id=user-1&created_after=1700000003&limit=10").json()
        assert [r["run_index"] for r in body["data"]] == [3, 4]
        assert body["meta"]["total_count"] == 2

    def test_status_filter_applies_before_paging(self):
        """A status filter narrows the runs first, so a page is full and total_count counts matches."""
        db = InMemoryDb()
        _seed_agent_session_with_runs(db, "mixed", count=6)
        for run in db._sessions["mixed"]["runs"][::2]:
            run["status"] = "ERROR"
        client = _build_client(db)

        body = client.get("/sessions/mixed/runs?user_id=user-1&status=error&limit=2").json()
        assert [r["run_index"] for r in body["data"]] == [2, 4]
        assert body["meta"] == {
            "limit": 2,
            "total_count": 3,
            "has_more": True,
            "oldest_run_index": 2,
            "newest_run_index": 4,
        }

    def test_invalid_status_rejected_when_paging(self, client):
        resp = client.get("/sessions/paged/runs?user_id=user-1&status=bogus&limit=2")
        assert resp.status_code == 400

    def test_single_run_carries_run_index(self, client):
        resp = client.get("/sessions/paged/runs/run-3?user_id=user-1")
        assert resp.status_code == 200
        assert resp.json()["run_index"] == 3

    def test_missing_session_returns_404(self, client):
        resp = client.get("/sessions/missing/runs?user_id=user-1&limit=2")
        assert resp.status_code == 404


def _seed_team_session(db: InMemoryDb, session_id: str, runs: list) -> None:
    _seed_session(
        db,
        {
            "session_id": session_id,
            "team_id": "team",
            "user_id": "user-1",
            "session_type": "team",
            "created_at": 1_700_000_000,
            "runs": runs,
        },
    )


def _team_run(run_id: str, created_at: int, **extra) -> dict:
    return {"run_id": run_id, "team_id": "team", "created_at": created_at, **extra}


def _member_run(run_id: str, parent_run_id: str, created_at: int, **extra) -> dict:
    return {"run_id": run_id, "agent_id": "member", "parent_run_id": parent_run_id, "created_at": created_at, **extra}


class TestSessionRunsPaginationGroups:
    """Pages count top-level runs; member and step runs come along with their parent."""

    def test_members_do_not_consume_the_limit(self):
        db = InMemoryDb()
        runs = []
        for i in range(5):
            runs += [_member_run(f"m{i}a", f"p{i}", 10 * i), _member_run(f"m{i}b", f"p{i}", 10 * i + 1)]
            runs.append(_team_run(f"p{i}", 10 * i + 2))
        _seed_team_session(db, "team-groups", runs)
        client = _build_client(db)

        body = client.get("/sessions/team-groups/runs?type=team&user_id=user-1&limit=2").json()
        assert [r["run_id"] for r in body["data"]] == ["m3a", "m3b", "p3", "m4a", "m4b", "p4"]
        assert body["meta"]["total_count"] == 5
        assert body["meta"]["has_more"] is True

        older = client.get(
            f"/sessions/team-groups/runs?type=team&user_id=user-1&limit=2&before_run_index={body['meta']['oldest_run_index']}"
        ).json()
        assert [r["run_id"] for r in older["data"]] == ["m1a", "m1b", "p1", "m2a", "m2b", "p2"]

    def test_meta_cursor_does_not_skip_a_parent_stored_between_a_member_and_its_parent(self):
        db = InMemoryDb()
        _seed_team_session(
            db,
            "interleaved",
            [_team_run("A", 1), _member_run("B-member", "B", 2), _team_run("C", 3), _team_run("B", 4)],
        )
        client = _build_client(db)

        page = client.get("/sessions/interleaved/runs?type=team&user_id=user-1&limit=1").json()
        assert [r["run_id"] for r in page["data"]] == ["B-member", "B"]
        assert page["meta"]["oldest_run_index"] == 3

        older = client.get(
            f"/sessions/interleaved/runs?type=team&user_id=user-1&limit=1&before_run_index={page['meta']['oldest_run_index']}"
        ).json()
        assert [r["run_id"] for r in older["data"]] == ["C"]

    def test_member_without_its_parent_in_the_session_is_a_top_level_run(self):
        db = InMemoryDb()
        _seed_team_session(db, "orphans", [_team_run("p0", 1), _member_run("orphan", "gone", 2), _team_run("p1", 3)])
        client = _build_client(db)

        body = client.get("/sessions/orphans/runs?type=team&user_id=user-1&limit=10").json()
        assert [r["run_id"] for r in body["data"]] == ["p0", "orphan", "p1"]
        assert body["meta"]["total_count"] == 3

    def test_nested_descendants_come_with_the_top_level_run(self):
        db = InMemoryDb()
        _seed_team_session(
            db,
            "nested",
            [
                _team_run("old", 1),
                {"run_id": "sub-team", "team_id": "sub", "parent_run_id": "top", "created_at": 2},
                _member_run("sub-member", "sub-team", 3),
                _team_run("top", 4),
            ],
        )
        client = _build_client(db)

        body = client.get("/sessions/nested/runs?type=team&user_id=user-1&limit=1").json()
        assert [r["run_id"] for r in body["data"]] == ["sub-team", "sub-member", "top"]

    def test_filters_select_top_level_runs_and_keep_their_members(self):
        db = InMemoryDb()
        _seed_team_session(
            db,
            "filtered-groups",
            [
                _team_run("p0", 100, status="ERROR"),
                _member_run("m1", "p1", 150, status="COMPLETED"),
                _team_run("p1", 300, status="ERROR"),
                _team_run("p2", 400, status="COMPLETED"),
            ],
        )
        client = _build_client(db)

        body = client.get(
            "/sessions/filtered-groups/runs?type=team&user_id=user-1&limit=5&status=error&created_after=200"
        ).json()
        assert [r["run_id"] for r in body["data"]] == ["m1", "p1"]
        assert body["meta"]["total_count"] == 1

    def test_workflow_step_runs_come_with_their_workflow_run(self):
        db = InMemoryDb()
        _seed_session(
            db,
            {
                "session_id": "wf-groups",
                "workflow_id": "wf",
                "user_id": "user-1",
                "session_type": "workflow",
                "created_at": 1,
                "runs": [
                    {"run_id": "w0", "workflow_id": "wf", "created_at": 1},
                    {"run_id": "step", "agent_id": "a", "parent_run_id": "w1", "created_at": 2},
                    {"run_id": "w1", "workflow_id": "wf", "created_at": 3},
                ],
            },
        )
        client = _build_client(db)

        body = client.get("/sessions/wf-groups/runs?type=workflow&user_id=user-1&limit=1").json()
        assert [r["run_id"] for r in body["data"]] == ["step", "w1"]
        assert body["meta"]["total_count"] == 2

    def test_empty_page_has_no_cursors(self):
        db = InMemoryDb()
        _seed_agent_session_with_runs(db, "empty-page", count=2)
        client = _build_client(db)

        body = client.get("/sessions/empty-page/runs?user_id=user-1&limit=2&before_run_index=0").json()
        assert body["data"] == []
        assert "oldest_run_index" not in body["meta"]
        assert "newest_run_index" not in body["meta"]


class TestSessionRunPreviewsRunIndex:
    """GET /sessions/{id}/run-previews carries the same run_index as the runs endpoint."""

    def test_previews_match_runs_for_team_sessions(self):
        db = InMemoryDb()
        _seed_session(
            db,
            {
                "session_id": "team-previews",
                "team_id": "test-team",
                "user_id": "user-1",
                "session_type": "team",
                "created_at": 1_700_000_000,
                "runs": [
                    {"run_id": "member-run", "agent_id": "member", "parent_run_id": "team-run", "created_at": 1},
                    {"run_id": "unlisted-run", "created_at": 2},
                    {"run_id": "team-run", "team_id": "test-team", "created_at": 3},
                ],
            },
        )
        client = _build_client(db)

        runs = client.get("/sessions/team-previews/runs?type=team&user_id=user-1").json()
        previews = client.get("/sessions/team-previews/run-previews?type=team&user_id=user-1").json()
        assert [(r["run_id"], r["run_index"]) for r in runs] == [("member-run", 0), ("team-run", 2)]
        assert [(p["run_id"], p["run_index"]) for p in previews] == [("member-run", 0), ("team-run", 2)]


class TestTeamSessionRunsParsing:
    """Team session runs should correctly classify agent vs team runs."""

    def test_team_session_with_mixed_runs(self):
        db = InMemoryDb()
        now = int(time.time())
        uid = uuid.uuid4().hex[:8]

        # Insert raw session with mixed agent and team runs
        _seed_session(
            db,
            {
                "session_id": f"team-mixed-{uid}",
                "team_id": "test-team",
                "user_id": "user-1",
                "session_type": "team",
                "session_data": {"session_name": "Team Mixed Runs"},
                "created_at": now,
                "updated_at": now,
                "runs": [
                    {"run_id": "agent-run-1", "agent_id": "member-agent", "created_at": now},
                    {"run_id": "team-run-1", "team_id": "test-team", "created_at": now},
                ],
            },
        )

        client = _build_client(db)
        resp = client.get(f"/sessions/team-mixed-{uid}/runs?type=team&user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        # First run is agent run (has agent_id)
        agent_run = next(r for r in data if r["run_id"] == "agent-run-1")
        assert agent_run.get("agent_id") == "member-agent"

        # Second run is team run (has team_id)
        team_run = next(r for r in data if r["run_id"] == "team-run-1")
        assert team_run.get("team_id") == "test-team"


class TestWorkflowSessionRunsParsing:
    """Workflow session runs should correctly classify workflow vs team vs agent runs."""

    def test_workflow_session_with_mixed_runs(self):
        db = InMemoryDb()
        now = int(time.time())
        uid = uuid.uuid4().hex[:8]

        _seed_session(
            db,
            {
                "session_id": f"wf-mixed-{uid}",
                "workflow_id": "test-workflow",
                "user_id": "user-1",
                "session_type": "workflow",
                "session_data": {"session_name": "Workflow Mixed Runs"},
                "created_at": now,
                "updated_at": now,
                "runs": [
                    {"run_id": "wf-run-1", "workflow_id": "test-workflow", "created_at": now},
                    {"run_id": "team-run-1", "team_id": "sub-team", "created_at": now},
                    {"run_id": "agent-run-1", "agent_id": "sub-agent", "created_at": now},
                ],
            },
        )

        client = _build_client(db)
        resp = client.get(f"/sessions/wf-mixed-{uid}/runs?type=workflow&user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

        wf_run = next(r for r in data if r["run_id"] == "wf-run-1")
        assert wf_run.get("workflow_id") == "test-workflow"

        team_run = next(r for r in data if r["run_id"] == "team-run-1")
        assert team_run.get("team_id") == "sub-team"

        # Agent run in workflow session is returned as RunSchema (fallback)
        agent_run = next(r for r in data if r["run_id"] == "agent-run-1")
        assert agent_run.get("agent_id") == "sub-agent"


class TestRenameSessionAutoDetect:
    """POST /sessions/{id}/rename with session_type=None auto-detect."""

    def test_rename_without_type_param(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.post(
            f"/sessions/{agent_s.session_id}/rename?user_id=user-1",
            json={"session_name": "Renamed Agent Session"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_name"] == "Renamed Agent Session"

    def test_rename_team_session_without_type(self, db_with_sessions):
        db, _, team_s, _ = db_with_sessions
        client = _build_client(db)

        resp = client.post(
            f"/sessions/{team_s.session_id}/rename?user_id=user-1",
            json={"session_name": "Renamed Team Session"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_name"] == "Renamed Team Session"

    def test_rename_nonexistent_session_returns_404(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.post(
            "/sessions/nonexistent-id/rename?user_id=user-1",
            json={"session_name": "Nope"},
        )
        assert resp.status_code == 404


class TestUpdateSession:
    """PATCH /sessions/{id} endpoint tests."""

    def test_update_session_state(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.patch(
            f"/sessions/{agent_s.session_id}?type=agent&user_id=user-1",
            json={"session_state": {"key": "value"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_state"]["key"] == "value"

    def test_update_session_name(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.patch(
            f"/sessions/{agent_s.session_id}?type=agent&user_id=user-1",
            json={"session_name": "Updated Name"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_name"] == "Updated Name"

    def test_update_metadata(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.patch(
            f"/sessions/{agent_s.session_id}?type=agent&user_id=user-1",
            json={"metadata": {"tag": "important"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["tag"] == "important"

    def test_update_summary(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.patch(
            f"/sessions/{agent_s.session_id}?type=agent&user_id=user-1",
            json={"summary": {"summary": "A test conversation", "updated_at": "2025-01-01T00:00:00"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_summary"]["summary"] == "A test conversation"

    def test_update_with_auto_detect_type(self, db_with_sessions):
        db, _, team_s, _ = db_with_sessions
        client = _build_client(db)

        resp = client.patch(
            f"/sessions/{team_s.session_id}?user_id=user-1",
            json={"session_name": "Auto-Detected Update"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_name"] == "Auto-Detected Update"

    def test_update_nonexistent_session_returns_404(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.patch(
            "/sessions/nonexistent-id?user_id=user-1",
            json={"session_name": "Nope"},
        )
        assert resp.status_code == 404


class TestDeleteSessions:
    """DELETE /sessions (bulk) endpoint tests."""

    def test_bulk_delete_sessions(self):
        db = InMemoryDb()
        uid = uuid.uuid4().hex[:8]
        now = int(time.time())

        s1 = AgentSession(
            session_id=f"del-a-{uid}",
            agent_id="a1",
            user_id="user-1",
            session_data={"session_name": "Del 1"},
            created_at=now,
            updated_at=now,
        )
        s2 = TeamSession(
            session_id=f"del-t-{uid}",
            team_id="t1",
            user_id="user-1",
            session_data={"session_name": "Del 2"},
            created_at=now,
            updated_at=now,
        )
        db.upsert_session(s1)
        db.upsert_session(s2)

        client = _build_client(db)

        # Verify both exist
        resp = client.get("/sessions?user_id=user-1")
        data, _ = _get_data(resp)
        assert len(data) == 2

        # Bulk delete
        resp = client.request(
            "DELETE",
            "/sessions?user_id=user-1",
            json={
                "session_ids": [f"del-a-{uid}", f"del-t-{uid}"],
                "session_types": ["agent", "team"],
            },
        )
        assert resp.status_code == 204

        # Verify both gone
        resp = client.get("/sessions?user_id=user-1")
        data, _ = _get_data(resp)
        assert len(data) == 0

    def test_bulk_delete_mismatched_lengths_returns_400(self):
        db = InMemoryDb()
        client = _build_client(db)

        resp = client.request(
            "DELETE",
            "/sessions",
            json={
                "session_ids": ["s1", "s2"],
                "session_types": ["agent"],  # length mismatch
            },
        )
        assert resp.status_code == 400

    def test_delete_single_session(self, db_with_sessions):
        db, agent_s, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.delete(f"/sessions/{agent_s.session_id}?user_id=user-1")
        assert resp.status_code == 204

        resp = client.get(f"/sessions/{agent_s.session_id}?user_id=user-1")
        assert resp.status_code == 404


class TestCreateSessionTypes:
    """POST /sessions for all session types including workflow."""

    def test_create_workflow_session(self):
        db = InMemoryDb()
        client = _build_client(db)

        resp = client.post(
            "/sessions?type=workflow",
            json={"user_id": "user-1", "workflow_id": "wf-1", "session_name": "Workflow Session"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data.get("session_id")
        assert data.get("workflow_id") == "wf-1"
        assert data.get("session_name") == "Workflow Session"

    def test_create_session_default_type_is_agent(self):
        db = InMemoryDb()
        client = _build_client(db)

        resp = client.post(
            "/sessions",
            json={"user_id": "user-1", "agent_id": "a1"},
        )
        assert resp.status_code == 201
        data = resp.json()
        # Default type is agent
        assert "agent_session_id" in data or "agent_id" in data

    def test_create_session_with_initial_state(self):
        db = InMemoryDb()
        client = _build_client(db)

        resp = client.post(
            "/sessions?type=agent",
            json={
                "user_id": "user-1",
                "agent_id": "a1",
                "session_name": "Stateful Session",
                "session_state": {"step": 1, "config": {"debug": True}},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["session_state"]["step"] == 1
        assert data["session_state"]["config"]["debug"] is True

    def test_create_session_with_metadata(self):
        db = InMemoryDb()
        client = _build_client(db)

        resp = client.post(
            "/sessions?type=agent",
            json={
                "user_id": "user-1",
                "agent_id": "a1",
                "metadata": {"source": "test", "version": 2},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["metadata"]["source"] == "test"


class TestPaginationEdgeCases:
    """Edge cases for pagination parameters."""

    def test_page_zero_behavior(self, db_with_sessions):
        """page=0 is allowed (ge=0 in query param) and returns empty data due to negative offset."""
        db, *_ = db_with_sessions
        client = _build_client(db)

        # page=0 computes start_idx = (0-1)*limit = negative, resulting in empty slice
        resp = client.get("/sessions?user_id=user-1&page=0&limit=2")
        assert resp.status_code == 200
        data, meta = _get_data(resp)
        assert len(data) == 0
        assert meta.get("total_count", 0) >= 3

    def test_large_page_returns_empty(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?user_id=user-1&page=999&limit=20")
        assert resp.status_code == 200
        data, meta = _get_data(resp)
        assert len(data) == 0
        assert meta.get("total_count", 0) >= 3

    def test_sort_asc(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?user_id=user-1&sort_by=created_at&sort_order=asc")
        assert resp.status_code == 200
        data, _ = _get_data(resp)
        created_times = [s.get("created_at") for s in data if s.get("created_at")]
        if len(created_times) >= 2:
            assert created_times[0] <= created_times[-1]

    def test_session_name_filter(self, db_with_sessions):
        db, *_ = db_with_sessions
        client = _build_client(db)

        resp = client.get("/sessions?user_id=user-1&session_name=Agent")
        assert resp.status_code == 200
        data, _ = _get_data(resp)
        # Should match "Agent Chat" session
        assert len(data) >= 1
        assert any("Agent" in s.get("session_name", "") for s in data)


class TestDetectSessionType:
    """Unit tests for detect_session_type function."""

    def test_stored_session_type_takes_priority(self):
        from agno.db.utils import detect_session_type

        # Stored session_type is authoritative — it wins over component IDs
        record = {"agent_id": "a1", "session_type": "team"}
        assert detect_session_type(record) == "team"

    def test_team_id_over_workflow_id(self):
        from agno.db.utils import detect_session_type

        record = {"team_id": "t1", "workflow_id": "w1"}
        assert detect_session_type(record) == "team"

    def test_workflow_id_detection(self):
        from agno.db.utils import detect_session_type

        record = {"workflow_id": "w1"}
        assert detect_session_type(record) == "workflow"

    def test_falls_back_to_stored_session_type(self):
        from agno.db.utils import detect_session_type

        record = {"session_type": "team"}
        assert detect_session_type(record) == "team"

    def test_falls_back_to_agent_when_nothing_set(self):
        from agno.db.utils import detect_session_type

        # This is the "fallback to AGENT" concern
        record = {}
        assert detect_session_type(record) == "agent"

    def test_session_type_enum_value_extracted(self):
        from agno.db.base import SessionType
        from agno.db.utils import detect_session_type

        record = {"session_type": SessionType.WORKFLOW}
        assert detect_session_type(record) == "workflow"


class TestResolveSessionType:
    """Unit tests for resolve_session_type function."""

    def test_returns_provided_type_without_db_fetch(self):
        import asyncio

        from agno.db.base import SessionType
        from agno.db.utils import resolve_session_type

        db = InMemoryDb()
        result = asyncio.run(resolve_session_type(db, "any-id", SessionType.TEAM))
        assert result == (SessionType.TEAM, None)

    def test_auto_detects_from_db(self):
        import asyncio

        from agno.db.base import SessionType
        from agno.db.utils import resolve_session_type

        db = InMemoryDb()
        now = int(time.time())
        uid = uuid.uuid4().hex[:8]

        session = TeamSession(
            session_id=f"resolve-{uid}",
            team_id="t1",
            user_id="user-1",
            session_data={"session_name": "Resolve Test"},
            created_at=now,
            updated_at=now,
        )
        db.upsert_session(session)

        resolved_type, raw = asyncio.run(resolve_session_type(db, f"resolve-{uid}", None))
        assert resolved_type == SessionType.TEAM
        assert raw is not None
        assert raw["team_id"] == "t1"

    def test_returns_none_for_missing_session(self):
        import asyncio

        from agno.db.utils import resolve_session_type

        db = InMemoryDb()
        resolved_type, raw = asyncio.run(resolve_session_type(db, "nonexistent", None))
        assert resolved_type is None
        assert raw is None


class TestSessionRunsAutoDetectType:
    """GET /sessions/{id}/runs auto-detects session type for run classification."""

    def test_auto_detect_team_session_runs(self):
        """When no type param given, team session runs should be classified correctly."""
        db = InMemoryDb()
        now = int(time.time())
        uid = uuid.uuid4().hex[:8]

        _seed_session(
            db,
            {
                "session_id": f"auto-team-{uid}",
                "team_id": "t1",
                "user_id": "user-1",
                "session_type": "team",
                "session_data": {"session_name": "Auto Team"},
                "created_at": now,
                "updated_at": now,
                "runs": [
                    {"run_id": "tr-1", "team_id": "t1", "created_at": now},
                ],
            },
        )

        client = _build_client(db)
        # No type param -- should auto-detect
        resp = client.get(f"/sessions/auto-team-{uid}/runs?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["team_id"] == "t1"

    def test_auto_detect_workflow_session_runs(self):
        db = InMemoryDb()
        now = int(time.time())
        uid = uuid.uuid4().hex[:8]

        _seed_session(
            db,
            {
                "session_id": f"auto-wf-{uid}",
                "workflow_id": "w1",
                "user_id": "user-1",
                "session_type": "workflow",
                "session_data": {"session_name": "Auto Workflow"},
                "created_at": now,
                "updated_at": now,
                "runs": [
                    {"run_id": "wr-1", "workflow_id": "w1", "created_at": now},
                ],
            },
        )

        client = _build_client(db)
        resp = client.get(f"/sessions/auto-wf-{uid}/runs?user_id=user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["workflow_id"] == "w1"


class TestSessionRunsRemoteWithoutPagination:
    """A remote AgentOS that predates pagination ignores limit and answers with a plain list."""

    @staticmethod
    def _remote_returning_list():
        from unittest.mock import AsyncMock, MagicMock

        from agno.os.schema import RunSchema
        from agno.remote.base import RemoteDb

        remote = MagicMock(spec=RemoteDb)
        remote.session_table_name = "sessions"
        remote.get_session_runs = AsyncMock(
            return_value=[RunSchema(run_id="run-0", agent_id="agent-1", status="COMPLETED")]
        )
        return remote

    def test_paged_request_fails_clearly(self):
        resp = _build_client(self._remote_returning_list()).get("/sessions/s1/runs?limit=2")
        assert resp.status_code == 502
        assert "does not support paginated session runs" in resp.json()["detail"]

    def test_unpaged_request_passes_the_list_through(self):
        remote = self._remote_returning_list()
        resp = _build_client(remote).get("/sessions/s1/runs")
        assert resp.status_code == 200
        assert [r["run_id"] for r in resp.json()] == ["run-0"]
        assert "limit" not in remote.get_session_runs.call_args.kwargs

    def test_paged_request_through_the_real_client_fails_clearly(self):
        from unittest.mock import AsyncMock, patch

        from agno.client import AgentOSClient
        from agno.remote.base import RemoteDb

        client = AgentOSClient(base_url="http://remote:7777")
        remote = RemoteDb(id="remote", client=client, session_table_name="sessions")
        with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [{"run_id": "run-0", "agent_id": "agent-1"}]
            resp = _build_client(remote).get("/sessions/s1/runs?limit=2")
        assert resp.status_code == 502
        assert "does not support paginated session runs" in resp.json()["detail"]
