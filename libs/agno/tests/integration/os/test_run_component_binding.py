"""A per-resource run grant is per-resource for cancel, continue, resume and fork too.

The gate on ``/agents/{agent_id}/runs/{run_id}/cancel`` decides on the path's agent id; the
handler then acts on the run and session the client named. The owner check bound those to
the component, but only for an isolation-scoped caller, so with RBAC on and isolation off
(the default) a token granted run on one agent could cancel or continue another agent's
run through that agent's route. Now the component half of the check always runs.
"""

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

JWT_SECRET = "run-binding-secret-at-least-32-bytes!!"
OS_ID = "run-binding-os"


def _headers(scopes: list[str], user_id: str = "someone") -> dict:
    payload = {"sub": user_id, "aud": OS_ID, "scopes": scopes, "exp": datetime.now(UTC) + timedelta(hours=1)}
    return {"Authorization": f"Bearer {jwt.encode(payload, JWT_SECRET, algorithm='HS256')}"}


@pytest.fixture
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "binding.db"))
    agent_a = Agent(id="agent-a", name="A", db=db)
    agent_b = Agent(id="agent-b", name="B", db=db)
    # A completed run of agent-b in agent-b's session, seeded at the storage layer.
    now = int(time.time())
    run = RunOutput(
        run_id="run-b", agent_id="agent-b", session_id="session-b", status=RunStatus.completed, created_at=now
    )
    session = AgentSession(session_id="session-b", agent_id="agent-b", runs=[run], created_at=now, updated_at=now)
    db.upsert_session(session)
    db.upsert_run(run=run, session_id="session-b", run_index=0)

    agent_os = AgentOS(
        id=OS_ID,
        db=db,
        agents=[agent_a, agent_b],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    return TestClient(agent_os.get_app())


def test_cancel_through_a_different_agent_is_refused(harness):
    only_a = _headers(["agents:agent-a:run"])
    resp = harness.post("/agents/agent-a/runs/run-b/cancel", headers=only_a)
    assert resp.status_code == 404
    resp = harness.post("/agents/agent-a/runs/run-b/cancel?session_id=session-b", headers=only_a)
    assert resp.status_code == 404


def test_continue_through_a_different_agent_is_refused(harness):
    only_a = _headers(["agents:agent-a:run"])
    resp = harness.post(
        "/agents/agent-a/runs/run-b/continue", data={"session_id": "session-b", "tools": "[]"}, headers=only_a
    )
    assert resp.status_code == 404


def test_fork_of_a_different_agents_session_is_refused(harness):
    only_a = _headers(["agents:agent-a:run"])
    resp = harness.post("/agents/agent-a/sessions/session-b/fork", headers=only_a)
    assert resp.status_code == 404


def test_the_owning_agent_route_still_works(harness):
    """Same run, same session, through agent-b's own route: the binding passes and the
    request proceeds to the handler (cancel of a completed run is a 200 no-op)."""
    only_b = _headers(["agents:agent-b:run"])
    resp = harness.post("/agents/agent-b/runs/run-b/cancel?session_id=session-b", headers=only_b)
    assert resp.status_code == 200, resp.text


def test_cancel_before_start_is_still_allowed(harness):
    """A run with no row yet (cancel-before-start) has nothing to bind and is not refused."""
    only_a = _headers(["agents:agent-a:run"])
    resp = harness.post("/agents/agent-a/runs/not-yet-registered/cancel", headers=only_a)
    assert resp.status_code == 200, resp.text
