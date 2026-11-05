"""POST /eval-runs executes its target, so it is gated per agent/team like the run routes.

The route scope (``evals:write``) says nothing about WHICH agents the caller may execute;
the target is named in the body. Without a per-resource decision, ``evals:write`` alone ran
any agent or team on the OS, including ones the caller was explicitly denied.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.routers.evals.schemas import EvalSchema
from agno.team import Team

JWT_SECRET = "eval-gate-secret"
OS_ID = "eval-gate-os"


def _token(user_id: str, scopes: list[str]) -> str:
    payload = {
        "sub": user_id,
        "aud": OS_ID,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _headers(scopes: list[str], user_id: str = "user-a") -> dict:
    return {"Authorization": f"Bearer {_token(user_id, scopes)}"}


@pytest.fixture
def client():
    db = InMemoryDb()
    allowed = Agent(id="allowed-agent", name="Allowed", db=db)
    secret = Agent(id="secret-agent", name="Secret", db=db)
    team = Team(id="secret-team", name="Secret Team", members=[allowed], db=db)
    agent_os = AgentOS(
        id=OS_ID,
        db=db,
        agents=[allowed, secret],
        teams=[team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    return TestClient(agent_os.get_app())


_STUB_RESULT = EvalSchema(id="stub-run", eval_type="accuracy", eval_data={"eval_status": "PASSED"})


def _body(**target) -> dict:
    return {"eval_type": "accuracy", "input": "hi", "expected_output": "hi", **target}


def test_evals_write_alone_cannot_run_an_ungranted_agent(client):
    """evals:write plus run on ONE agent does not let the caller eval a different agent."""
    resp = client.post(
        "/eval-runs",
        json=_body(agent_id="secret-agent"),
        headers=_headers(["evals:write", "agents:allowed-agent:run"]),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Access denied to run this agent"


def test_evals_write_alone_cannot_run_an_ungranted_team(client):
    resp = client.post(
        "/eval-runs",
        json=_body(team_id="secret-team"),
        headers=_headers(["evals:write"]),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Access denied to run this team"


def test_gate_runs_before_the_target_is_resolved(client):
    """An unknown target is refused as a 403 for an ungranted caller, not a 404 that would
    confirm which ids exist."""
    resp = client.post(
        "/eval-runs",
        json=_body(agent_id="does-not-exist"),
        headers=_headers(["evals:write"]),
    )
    assert resp.status_code == 403


def test_granted_caller_passes_the_gate(client):
    """A caller holding run on the target reaches the eval itself (stubbed: no model call)."""
    with patch("agno.os.routers.evals.evals.run_accuracy_eval", return_value=_STUB_RESULT) as run_eval:
        resp = client.post(
            "/eval-runs",
            json=_body(agent_id="secret-agent"),
            headers=_headers(["evals:write", "agents:secret-agent:run"]),
        )
    assert resp.status_code == 200, resp.text
    assert run_eval.await_count == 1


def test_admin_passes_the_gate(client):
    with patch("agno.os.routers.evals.evals.run_accuracy_eval", return_value=_STUB_RESULT):
        resp = client.post(
            "/eval-runs",
            json=_body(agent_id="secret-agent"),
            headers=_headers(["agent_os:admin"]),
        )
    assert resp.status_code == 200, resp.text
