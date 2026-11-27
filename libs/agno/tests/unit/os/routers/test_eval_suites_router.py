"""Suite routes execute authorized targets and persist a scoped aggregate report."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.eval.suite import CaseResult, SuiteResult
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.team import Team

SECRET = "suite-router-tests"


def headers(user="alice", scopes=None):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": user,
                "aud": "suite-os",
                "exp": datetime.now(UTC) + timedelta(hours=1),
                "scopes": scopes
                if scopes is not None
                else ["evals:read", "evals:write", "evals:delete", "agents:helper:run", "teams:helpers:run"],
            },
            SECRET,
            algorithm="HS256",
        )
    }


@pytest.fixture(params=["memory", "sqlite", "async_sqlite"])
def setup(request, tmp_path):
    if request.param == "memory":
        db = InMemoryDb()
    elif request.param == "sqlite":
        db = SqliteDb(db_file=str(tmp_path / "suite.db"))
    else:
        db = AsyncSqliteDb(db_file=str(tmp_path / "suite.db"))
    agent = Agent(id="helper", name="Helper", db=db)
    team = Team(id="helpers", members=[agent], db=db)
    os = AgentOS(
        id="suite-os",
        agents=[agent],
        teams=[team],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256", user_isolation=True),
    )
    with TestClient(os.get_app()) as client:
        yield client, agent


def body():
    return {
        "name": "Smoke suite",
        "cases": [
            {"name": "answer", "agent_id": "helper", "input": "hi", "criteria": "Says hello", "tags": ["smoke"]},
            {"name": "tools", "team_id": "helpers", "input": "compute", "expected_tool_calls": ["add"]},
        ],
    }


async def fake_runner(cases, **kwargs):
    return SuiteResult(
        results=[
            CaseResult(
                name=case.name,
                tags=case.tags,
                agent_id=case.agent.id if case.agent else None,
                team_id=case.team.id if case.team else None,
                judge_passed=True if case.criteria else None,
                reliability_passed=True if case.expected_tool_calls else None,
                output="hello",
            )
            for case in cases
        ]
    )


def test_suite_round_trip_and_isolation(setup):
    client, agent = setup
    with patch("agno.os.routers.evals.evals.arun_cases", side_effect=fake_runner) as runner:
        response = client.post("/eval-suites", json=body(), headers=headers())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["eval_type"] == "suite"
    assert result["eval_data"]["summary"] == {"total": 2, "passed": 2, "failed": 0, "status": "PASS"}
    assert result["eval_input"]["cases"][0]["tags"] == ["smoke"]
    cases = runner.call_args.args[0]
    assert cases[0].agent is not agent
    assert all(case.user_id == "alice" for case in cases)
    run_id = result["id"]
    for route in ("/eval-suites", "/eval-runs"):
        assert client.get(route, headers=headers()).json()["meta"]["total_count"] == 1
        assert client.get(route, headers=headers("bob")).json()["meta"]["total_count"] == 0
        assert client.get(f"{route}/{run_id}", headers=headers()).status_code == 200
        assert client.get(f"{route}/{run_id}", headers=headers("bob")).status_code == 404
    assert client.patch(f"/eval-runs/{run_id}", json={"name": "Renamed"}, headers=headers()).json()["name"] == "Renamed"
    assert client.request("DELETE", "/eval-runs", json={"eval_run_ids": [run_id]}, headers=headers()).status_code == 204
    assert client.get(f"/eval-suites/{run_id}", headers=headers()).status_code == 404


def test_all_targets_authorized_before_execution(setup):
    client, _ = setup
    with patch("agno.os.routers.evals.evals.arun_cases") as runner:
        response = client.post(
            "/eval-suites", json=body(), headers=headers(scopes=["evals:write", "agents:helper:run"])
        )
    assert response.status_code == 403
    runner.assert_not_called()


def test_route_requires_eval_write(setup):
    client, _ = setup
    response = client.post(
        "/eval-suites", json=body(), headers=headers(scopes=["agents:helper:run", "teams:helpers:run"])
    )
    assert response.status_code == 403


def test_selection_and_empty_selection(setup):
    client, _ = setup
    with patch("agno.os.routers.evals.evals.arun_cases", side_effect=fake_runner) as runner:
        response = client.post("/eval-suites", json={**body(), "tag": "smoke"}, headers=headers())
        assert response.status_code == 200, response.text
        assert len(runner.call_args.args[0]) == 1
        response = client.post("/eval-suites", json={**body(), "tag": "missing"}, headers=headers())
    assert response.json()["eval_data"]["summary"] == {"total": 0, "passed": 0, "failed": 0, "status": "FAIL"}


def test_reuses_target_copy(setup):
    client, _ = setup
    payload = body()
    payload["cases"] = [payload["cases"][0], {**payload["cases"][0], "name": "second"}]
    with patch("agno.os.routers.evals.evals.arun_cases", side_effect=fake_runner) as runner:
        assert client.post("/eval-suites", json=payload, headers=headers()).status_code == 200
    cases = runner.call_args.args[0]
    assert cases[0].agent is cases[1].agent


@pytest.mark.parametrize(
    "change",
    [
        {"agent_id": "helper", "team_id": "helpers"},
        {"agent_id": None},
        {"criteria": None},
        {"timeout_seconds": 0},
        {"judge_threshold": 11},
        {"scorer": "arbitrary code"},
    ],
)
def test_invalid_case_rejected_before_running(setup, change):
    client, _ = setup
    payload = body()
    payload["cases"] = [{**payload["cases"][0], **change}]
    with patch("agno.os.routers.evals.evals.arun_cases") as runner:
        assert client.post("/eval-suites", json=payload, headers=headers()).status_code == 422
    runner.assert_not_called()


def test_duplicate_names_rejected(setup):
    client, _ = setup
    payload = body()
    payload["cases"][1]["name"] = payload["cases"][0]["name"]
    assert client.post("/eval-suites", json=payload, headers=headers()).status_code == 422


def test_suite_not_accepted_as_standalone_eval(setup):
    client, _ = setup
    response = client.post(
        "/eval-runs", json={"eval_type": "suite", "agent_id": "helper", "input": "hi"}, headers=headers()
    )
    assert response.status_code == 422


def test_real_runner_persists_failure_evidence(setup):
    from agno.models.response import ToolExecution
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus

    client, _ = setup

    async def run_agent(self, **kwargs):
        yield RunOutput(
            status=RunStatus.completed, content="Used search", tools=[ToolExecution(tool_name="search", tool_args={})]
        )

    payload = {
        "name": "Tool checks",
        "cases": [
            {"name": "passes", "agent_id": "helper", "input": "hi", "expected_tool_calls": ["search"]},
            {"name": "fails", "agent_id": "helper", "input": "hi", "expected_tool_calls": ["lookup"]},
        ],
    }
    with patch.object(Agent, "arun", run_agent):
        response = client.post("/eval-suites", json=payload, headers=headers())
    assert response.status_code == 200, response.text
    report = response.json()["eval_data"]
    assert report["summary"] == {"total": 2, "passed": 1, "failed": 1, "status": "FAIL"}
    assert report["cases"][1]["tools_called"] == ["search"]
    assert report["cases"][1]["output"] == "Used search"
    assert report["cases"][1]["session_id"].startswith("eval-")
