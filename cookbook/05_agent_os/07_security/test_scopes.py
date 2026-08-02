"""
Executable and pytest RBAC enforcement test
===========================================

Exercise JWT authentication, audience validation, default agent/team/workflow
scope mappings, component protection, admin bypass, and a fully local workflow
run. The same checks run as a script or through pytest.

Prerequisites: none
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/test_scopes.py
Try: pytest -q cookbook/05_agent_os/07_security/test_scopes.py
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.team import Team
from agno.workflow import Workflow
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create the local test application
# ---------------------------------------------------------------------------

OS_ID = "scope-test-os"
JWT_SECRET = "scope-test-secret-at-least-256-bits-long"


def make_token(subject: str, scopes: list[str], *, audience: str = OS_ID) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "aud": audience,
            "scopes": scopes,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def build_test_app(db_file: str) -> Any:
    db = SqliteDb(db_file=db_file)
    test_agent = Agent(
        id="test-agent",
        name="Test Agent",
        model=OpenAIResponses(id="gpt-5.5"),
        db=db,
    )
    test_team = Team(
        id="test-team",
        name="Test Team",
        model=OpenAIResponses(id="gpt-5.5"),
        members=[test_agent],
        db=db,
    )

    def local_step(session_state: dict | None = None) -> str:
        state = session_state or {}
        return str(state.get("message", "done"))

    test_workflow = Workflow(
        id="test-workflow",
        name="Test Workflow",
        steps=local_step,
        db=db,
    )
    agent_os = AgentOS(
        id=OS_ID,
        agents=[test_agent],
        teams=[test_team],
        workflows=[test_workflow],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            verify_audience=True,
        ),
    )
    return agent_os.get_app()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Run the enforcement matrix
# ---------------------------------------------------------------------------


def exercise_scope_enforcement(db_file: str) -> dict[str, int]:
    app = build_test_app(db_file)
    reader = make_token(
        "reader",
        ["agents:read", "teams:read", "workflows:read"],
    )
    workflow_runner = make_token(
        "workflow-runner",
        ["workflows:read", "workflows:run"],
    )
    admin = make_token("admin", ["agent_os:admin"])
    wrong_audience = make_token(
        "reader",
        ["agents:read"],
        audience="another-agent-os",
    )

    with TestClient(app) as client:
        statuses = {
            "anonymous_agents": client.get("/agents").status_code,
            "reader_agents": client.get("/agents", headers=_auth(reader)).status_code,
            "reader_teams": client.get("/teams", headers=_auth(reader)).status_code,
            "reader_workflows": client.get(
                "/workflows", headers=_auth(reader)
            ).status_code,
            "reader_agent_run": client.post(
                "/agents/test-agent/runs",
                data={"message": "blocked", "stream": "false"},
                headers=_auth(reader),
            ).status_code,
            "reader_team_run": client.post(
                "/teams/test-team/runs",
                data={"message": "blocked", "stream": "false"},
                headers=_auth(reader),
            ).status_code,
            "reader_workflow_run": client.post(
                "/workflows/test-workflow/runs",
                data={"message": "blocked", "stream": "false"},
                headers=_auth(reader),
            ).status_code,
            "workflow_runner": client.post(
                "/workflows/test-workflow/runs",
                data={"message": "local workflow", "stream": "false"},
                headers=_auth(workflow_runner),
            ).status_code,
            "component_write": client.post(
                "/components",
                json={"name": "blocked", "component_type": "agent"},
                headers=_auth(reader),
            ).status_code,
            "admin_config": client.get("/config", headers=_auth(admin)).status_code,
            "wrong_audience": client.get(
                "/agents", headers=_auth(wrong_audience)
            ).status_code,
        }

    expected = {
        "anonymous_agents": 401,
        "reader_agents": 200,
        "reader_teams": 200,
        "reader_workflows": 200,
        "reader_agent_run": 403,
        "reader_team_run": 403,
        "reader_workflow_run": 403,
        "workflow_runner": 200,
        "component_write": 403,
        "admin_config": 200,
        "wrong_audience": 401,
    }
    assert statuses == expected, statuses
    return statuses


def test_scope_enforcement(tmp_path: Path) -> None:
    exercise_scope_enforcement(str(tmp_path / "scope_test.db"))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp_dir:
        observed_statuses = exercise_scope_enforcement(
            str(Path(temp_dir) / "scope_test.db")
        )
    print("RBAC enforcement smoke passed:")
    for check_name, status_code in observed_statuses.items():
        print(f"  {check_name}: {status_code}")
