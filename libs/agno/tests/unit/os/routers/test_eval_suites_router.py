"""Tests for the eval-suites REST API routes.

A suite registered on the OS is listed with its cases, and ``POST /eval-suites/{id}/runs``
persists one eval run of type ``suite`` whose ``eval_data`` is the ``SuiteResult`` payload,
so the pass rate shows up in ``GET /eval-runs`` like any other eval.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.base import BaseDb
from agno.db.in_memory import InMemoryDb
from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER
from agno.eval import Case, EvalSuite, SuiteResult
from agno.models.response import ToolExecution
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.cancel import acleanup_run, ais_cancelled
from agno.session import AgentSession
from agno.team import Team

JWT_SECRET = "test-secret-for-eval-suites-router"
TEST_OS_ID = "test-eval-suites-router-os"


def create_token(user_id: str, scopes: list[str] | None = None) -> str:
    payload = {
        "sub": user_id,
        "aud": TEST_OS_ID,
        # Running a suite executes the target agent, so the default token also holds run on it.
        "scopes": scopes or ["evals:read", "evals:write", "agents:assistant:read", "agents:assistant:run"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def auth_header(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_token(user_id)}"}


async def _tool_run(*args, **kwargs):
    """A run that cleanly executed the expected tool, so the reliability check needs no model."""
    yield RunOutput(
        content="50",
        status=RunStatus.completed,
        tools=[ToolExecution(tool_call_id="call_multiply", tool_name="multiply", tool_args={"a": 10, "b": 5})],
    )


@pytest.fixture
def db():
    return InMemoryDb()


@pytest.fixture
def suite(db):
    agent = Agent(id="assistant", name="Assistant", db=db)
    return EvalSuite(
        id="assistant-quality",
        name="Assistant quality",
        cases=(
            Case(
                name="multiplies", agent=agent, input="10 times 5", expected_tool_calls=("multiply",), tags=("smoke",)
            ),
            Case(name="adds", agent=agent, input="10 plus 5", expected_tool_calls=("add",)),
        ),
    )


@pytest.fixture
def client(db, suite):
    """Isolation-enabled client: the router stamps the caller as the run's owner."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[suite.cases[0].agent],
        eval_suites=[suite],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            user_isolation=True,
        ),
    )
    return TestClient(agent_os.get_app())


def test_eval_suites_are_listed_with_their_cases(client):
    resp = client.get("/eval-suites", headers=auth_header("alice"))
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "id": "assistant-quality",
            "name": "Assistant quality",
            "description": None,
            "cases": [
                {
                    "name": "multiplies",
                    "agent_id": "assistant",
                    "team_id": None,
                    "tags": ["smoke"],
                    "timeout_seconds": None,
                },
                {"name": "adds", "agent_id": "assistant", "team_id": None, "tags": [], "timeout_seconds": None},
            ],
        }
    ]
    assert client.get("/eval-suites/assistant-quality", headers=auth_header("alice")).json() == resp.json()[0]


def test_unknown_eval_suite_is_404(client):
    assert client.get("/eval-suites/nope", headers=auth_header("alice")).status_code == 404
    assert client.post("/eval-suites/nope/runs", json={}, headers=auth_header("alice")).status_code == 404


def test_run_eval_suite_persists_one_suite_run(client, db):
    """The response id is the persisted run_id, eval_data is the SuiteResult payload, and the
    run is stamped with the suite's agent so it is found under GET /eval-runs?agent_id=."""
    with patch.object(Agent, "arun", side_effect=_tool_run):
        resp = client.post("/eval-suites/assistant-quality/runs", json={}, headers=auth_header("alice"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["eval_type"] == "suite"
    assert body["agent_id"] == "assistant"
    assert body["name"] == "Assistant quality"
    assert body["user_id"] == "alice"
    assert body["eval_data"]["summary"] == {"total": 2, "passed": 1, "failed": 1, "status": "FAIL"}
    assert [(case["name"], case["passed"]) for case in body["eval_data"]["cases"]] == [
        ("multiplies", True),
        ("adds", False),
    ]
    assert body["eval_input"] == {
        "suite_id": "assistant-quality",
        "tag": None,
        "case_name": None,
        "default_timeout": 120,
    }

    rows, total = db.get_eval_runs(deserialize=False, eval_type=["suite"])
    assert total == 1
    assert rows[0]["run_id"] == body["id"]
    assert rows[0]["user_id"] == "alice"
    listed = client.get("/eval-runs?agent_id=assistant&eval_types=suite", headers=auth_header("alice")).json()["data"]
    assert [row["id"] for row in listed] == [body["id"]]
    assert client.get(f"/eval-runs/{body['id']}", headers=auth_header("alice")).json()["eval_data"] == body["eval_data"]
    # and it is not visible to another user
    assert client.get("/eval-runs", headers=auth_header("bob")).json()["data"] == []


def test_run_eval_suite_selects_by_tag_or_name(client, db):
    with patch.object(Agent, "arun", side_effect=_tool_run):
        by_tag = client.post("/eval-suites/assistant-quality/runs", json={"tag": "smoke"}, headers=auth_header("alice"))
        by_name = client.post(
            "/eval-suites/assistant-quality/runs", json={"case_name": "adds"}, headers=auth_header("alice")
        )
        none = client.post("/eval-suites/assistant-quality/runs", json={"tag": "nightly"}, headers=auth_header("alice"))
    assert [case["name"] for case in by_tag.json()["eval_data"]["cases"]] == ["multiplies"]
    assert by_tag.json()["eval_data"]["summary"]["status"] == "PASS"
    assert [case["name"] for case in by_name.json()["eval_data"]["cases"]] == ["adds"]
    assert none.status_code == 400
    _, total = db.get_eval_runs(deserialize=False)
    assert total == 2


def test_run_eval_suite_requires_run_access_on_the_target(client, db):
    """Same gate as a single eval: evals:write alone does not let the caller execute the agent."""
    headers = {"Authorization": f"Bearer {create_token('alice', scopes=['evals:read', 'evals:write'])}"}
    with patch.object(Agent, "arun", side_effect=_tool_run) as arun:
        resp = client.post("/eval-suites/assistant-quality/runs", json={}, headers=headers)
    assert resp.status_code == 403
    assert arun.call_count == 0
    _, total = db.get_eval_runs(deserialize=False)
    assert total == 0


def test_post_eval_runs_refuses_the_suite_type(client):
    body = {"eval_type": "suite", "agent_id": "assistant", "input": "10 times 5"}
    headers = {"Authorization": f"Bearer {create_token('alice', scopes=['evals:write', 'agents:assistant:run'])}"}
    resp = client.post("/eval-runs", json=body, headers=headers)
    assert resp.status_code == 400
    assert "POST /eval-suites/{suite_id}/runs" in resp.json()["detail"]


def test_eval_suite_without_an_id_or_cases_is_dropped(db, suite):
    """A suite never stops the OS: one with no id or no cases is not served, the rest still are."""
    agent = suite.cases[0].agent
    no_id = EvalSuite(id="", cases=suite.cases)
    no_cases = EvalSuite(id="empty", cases=())
    agent_os = AgentOS(id=TEST_OS_ID, agents=[agent], eval_suites=[no_id, no_cases, suite], db=db, telemetry=False)
    assert [eval_suite.id for eval_suite in agent_os._eval_suites] == ["assistant-quality"]


def test_eval_suite_targeting_an_unregistered_agent_is_dropped(db, suite):
    agent_os = AgentOS(id=TEST_OS_ID, agents=[Agent(id="other", db=db)], eval_suites=[suite], db=db, telemetry=False)
    client = TestClient(agent_os.get_app())
    assert agent_os._eval_suites is None
    assert client.get("/eval-suites").json() == []


def test_eval_suite_routes_need_the_evals_scopes(client):
    headers = {"Authorization": f"Bearer {create_token('alice', scopes=['agents:assistant:run'])}"}
    assert client.get("/eval-suites", headers=headers).status_code == 403
    assert client.post("/eval-suites/assistant-quality/runs", json={}, headers=headers).status_code == 403


def test_eval_suite_over_an_agent_and_a_team_is_dropped(db):
    """A suite runs one agent or team; a mixed one is not served and the OS still starts."""
    agent = Agent(id="assistant", name="Assistant", db=db)
    team = Team(id="helpers", name="Helpers", members=[agent], db=db)
    mixed = EvalSuite(
        id="mixed",
        cases=(
            Case(name="agent-case", agent=agent, input="10 times 5", expected_tool_calls=("multiply",)),
            Case(name="team-case", team=team, input="10 times 5", expected_tool_calls=("multiply",)),
        ),
    )
    agent_os = AgentOS(id=TEST_OS_ID, agents=[agent], teams=[team], eval_suites=[mixed], db=db, telemetry=False)
    assert agent_os._eval_suites is None
    assert TestClient(agent_os.get_app()).get("/eval-suites").json() == []


def _posted_suite(**overrides):
    body = {
        "name": "Posted suite",
        "cases": [
            {"name": "multiplies", "agent_id": "assistant", "input": "10 times 5", "expected_tool_calls": ["multiply"]},
            {"name": "adds", "agent_id": "assistant", "input": "10 plus 5", "expected_tool_calls": ["add"]},
        ],
    }
    body.update(overrides)
    return body


def test_run_eval_suite_from_body_persists_one_suite_run(client, db):
    """The posted cases run like a registered suite and the body is saved as eval_input for reruns."""
    with patch.object(Agent, "arun", side_effect=_tool_run):
        resp = client.post("/eval-suites", json=_posted_suite(), headers=auth_header("alice"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["eval_type"] == "suite"
    assert body["name"] == "Posted suite"
    assert body["agent_id"] == "assistant"
    assert body["user_id"] == "alice"
    assert body["eval_data"]["summary"] == {"total": 2, "passed": 1, "failed": 1, "status": "FAIL"}
    assert body["eval_input"]["cases"][0]["name"] == "multiplies"
    rows, total = db.get_eval_runs(deserialize=False, eval_type=["suite"])
    assert total == 1
    assert rows[0]["run_id"] == body["id"]


def test_run_eval_suite_from_body_rejects_a_bad_body(client):
    no_checks = _posted_suite(cases=[{"name": "x", "agent_id": "assistant", "input": "q"}])
    assert client.post("/eval-suites", json=no_checks, headers=auth_header("alice")).status_code == 422
    typo = _posted_suite(cases=[{**_posted_suite()["cases"][0], "criterias": "k"}])
    assert client.post("/eval-suites", json=typo, headers=auth_header("alice")).status_code == 422
    selector_typo = {"name": "adds"}
    assert (
        client.post("/eval-suites/assistant-quality/runs", json=selector_typo, headers=auth_header("alice")).status_code
        == 422
    )


def test_run_eval_suite_from_body_unknown_agent_is_404(client):
    body = _posted_suite(cases=[{"name": "x", "agent_id": "ghost", "input": "q", "criteria": "k"}])
    headers = {"Authorization": f"Bearer {create_token('alice', scopes=['evals:write', 'agents:ghost:run'])}"}
    resp = client.post("/eval-suites", json=body, headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Agent with id 'ghost' not found"


def test_run_eval_suite_from_body_requires_run_access_on_the_target(client, db):
    headers = {"Authorization": f"Bearer {create_token('alice', scopes=['evals:read', 'evals:write'])}"}
    with patch.object(Agent, "arun", side_effect=_tool_run) as arun:
        resp = client.post("/eval-suites", json=_posted_suite(), headers=headers)
    assert resp.status_code == 403
    assert arun.call_count == 0
    _, total = db.get_eval_runs(deserialize=False)
    assert total == 0


def test_run_eval_suite_from_body_rejects_more_than_one_target(client):
    cases = [
        {"name": "a", "agent_id": "assistant", "input": "q", "criteria": "k"},
        {"name": "b", "team_id": "assistant", "input": "q", "criteria": "k"},
    ]
    resp = client.post("/eval-suites", json=_posted_suite(cases=cases), headers=auth_header("alice"))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "All cases in a suite must run the same agent or team"


def test_run_eval_suite_runs_every_case_as_the_caller(db):
    """A user_id set on a case does not let a caller run as someone else, as on the run routes."""
    agent = Agent(id="assistant", name="Assistant", db=db)
    eval_suite = EvalSuite(
        id="as-ceo",
        cases=(Case(name="c", agent=agent, input="10 times 5", expected_tool_calls=("multiply",), user_id="ceo"),),
    )
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[agent],
        eval_suites=[eval_suite],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET], algorithm="HS256", user_isolation=True
        ),
        telemetry=False,
    )
    seen = []

    async def _record_user(*args, **kwargs):
        seen.append(kwargs.get("user_id"))
        async for event in _tool_run():
            yield event

    with patch.object(Agent, "arun", side_effect=_record_user):
        resp = TestClient(agent_os.get_app()).post("/eval-suites/as-ceo/runs", json={}, headers=auth_header("alice"))
    assert resp.status_code == 200
    assert seen == ["alice"]


def test_scheduled_eval_suite_runs_as_the_schedule_owner(db):
    """With isolation off, a scheduled suite still runs and is stored as the schedule's owner."""
    agent = Agent(id="assistant", name="Assistant", db=db)
    eval_suite = EvalSuite(
        id="nightly", cases=(Case(name="c", agent=agent, input="10 times 5", expected_tool_calls=("multiply",)),)
    )
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[agent],
        eval_suites=[eval_suite],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())
    client.app.state.internal_service_token = "internal"
    seen = []

    async def _record_user(*args, **kwargs):
        seen.append(kwargs.get("user_id"))
        async for event in _tool_run():
            yield event

    with patch.object(Agent, "arun", side_effect=_record_user):
        resp = client.post(
            "/eval-suites/nightly/runs",
            json={},
            headers={"Authorization": "Bearer internal", SCHEDULE_OWNER_HEADER: "bob"},
        )
    assert resp.status_code == 200
    assert seen == ["bob"]
    assert resp.json()["user_id"] == "bob"


def test_eval_suite_dropped_at_startup_is_served_after_resync(db, suite):
    """A suite dropped because its agent was not registered is served once the agent is added and the OS resyncs."""
    agent_os = AgentOS(id=TEST_OS_ID, eval_suites=[suite], db=db, telemetry=False)
    app = agent_os.get_app()
    assert TestClient(app).get("/eval-suites").json() == []

    agent_os.agents = [suite.cases[0].agent]
    agent_os.resync(app)

    assert [eval_suite["id"] for eval_suite in TestClient(app).get("/eval-suites").json()] == ["assistant-quality"]
    assert app.state.eval_suites == [suite]


def test_eval_suites_are_listed_only_for_readable_targets(db):
    """A caller sees a suite only if it may read the suite's agent, as GET /agents filters."""
    sales = Agent(id="sales", name="Sales", db=db)
    hr = Agent(id="hr", name="HR", db=db)
    sales_suite = EvalSuite(id="sales-quality", cases=(Case(name="c", agent=sales, input="q", criteria="k"),))
    hr_suite = EvalSuite(id="hr-quality", cases=(Case(name="c", agent=hr, input="q", criteria="k"),))
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[sales, hr],
        eval_suites=[sales_suite, hr_suite],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())
    headers = {"Authorization": f"Bearer {create_token('alice', scopes=['evals:read', 'agents:sales:read'])}"}
    assert [suite["id"] for suite in client.get("/eval-suites", headers=headers).json()] == ["sales-quality"]
    assert client.get("/eval-suites/sales-quality", headers=headers).status_code == 200
    assert client.get("/eval-suites/hr-quality", headers=headers).status_code == 404


def test_run_eval_suite_from_body_uses_each_case_judge_model(client):
    """A posted case can name its judge, as Case(judge_model=...) does in Python."""
    cases = [
        {
            "name": "a",
            "agent_id": "assistant",
            "input": "q",
            "criteria": "k",
            "judge_model_id": "claude-sonnet-5-5",
            "judge_model_provider": "anthropic",
        },
        {"name": "b", "agent_id": "assistant", "input": "q", "criteria": "k"},
    ]
    seen = {}

    async def _capture(selected, **kwargs):
        seen.update({case.name: case.judge_model for case in selected})
        return SuiteResult(results=[])

    with patch("agno.os.routers.evals.evals.arun_cases", side_effect=_capture):
        resp = client.post("/eval-suites", json=_posted_suite(cases=cases), headers=auth_header("alice"))
    assert resp.status_code == 200
    assert seen["a"].id == "claude-sonnet-5-5"
    assert seen["b"] is None
    half = [{"name": "c", "agent_id": "assistant", "input": "q", "criteria": "k", "judge_model_id": "x"}]
    assert client.post("/eval-suites", json=_posted_suite(cases=half), headers=auth_header("alice")).status_code == 422


def test_run_eval_suite_from_body_forwards_session_fields(client):
    """A posted case carries the same run arguments a Python Case does."""
    case = {
        **_posted_suite()["cases"][0],
        "session_id": "chat-1",
        "session_state": {"plan": "pro"},
        "metadata": {"k": 1},
    }
    seen = []

    async def _capture(selected, **kwargs):
        seen.extend(selected)
        return SuiteResult(results=[])

    with patch("agno.os.routers.evals.evals.arun_cases", side_effect=_capture):
        resp = client.post("/eval-suites", json=_posted_suite(cases=[case]), headers=auth_header("alice"))
    assert resp.status_code == 200
    assert seen[0].session_id == "chat-1"
    assert seen[0].session_state == {"plan": "pro"}
    assert seen[0].metadata == {"k": 1}


def test_run_eval_suite_from_body_checks_run_access_before_the_lookup(client):
    """A caller without run rights gets 403 before the target is looked up, so ids cannot be probed."""
    headers = {"Authorization": f"Bearer {create_token('alice', scopes=['evals:write'])}"}
    with patch("agno.os.routers.evals.utils.get_agent_by_id") as lookup:
        resp = client.post("/eval-suites", json=_posted_suite(), headers=headers)
    assert resp.status_code == 403
    assert lookup.call_count == 0


def test_run_eval_suite_refuses_another_users_pinned_session(db):
    """A case pinned to a session owned by someone else is refused before any model call."""
    agent = Agent(id="assistant", name="Assistant", db=db)
    pinned = EvalSuite(
        id="pinned",
        cases=(Case(name="c", agent=agent, input="q", expected_tool_calls=("multiply",), session_id="conv-1"),),
    )
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[agent],
        eval_suites=[pinned],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET], algorithm="HS256", user_isolation=True
        ),
    )
    client = TestClient(agent_os.get_app())
    db.upsert_session(AgentSession(session_id="conv-1", agent_id="assistant", user_id="alice"))
    with patch.object(Agent, "arun", side_effect=_tool_run) as arun:
        resp = client.post("/eval-suites/pinned/runs", json={}, headers=auth_header("bob"))
    assert resp.status_code == 404
    assert arun.call_count == 0


def test_run_eval_suite_from_body_strips_runtime_metadata_keys(client):
    """A posted case cannot forge the version stamp or dispatch lineage, as on the run routes."""
    forged = {"agno_component_version": 99, "agno_dispatch_depth": 0, "team": "ok"}
    case = {**_posted_suite()["cases"][0], "metadata": forged}
    seen = []

    async def _capture(selected, **kwargs):
        seen.extend(selected)
        return SuiteResult(results=[])

    with patch("agno.os.routers.evals.evals.arun_cases", side_effect=_capture):
        resp = client.post("/eval-suites", json=_posted_suite(cases=[case]), headers=auth_header("alice"))
    assert resp.status_code == 200
    assert seen[0].metadata == {"team": "ok"}


def test_run_eval_suite_in_background_stores_a_running_row_then_the_result(client, db):
    """With background=true the run is answered 202 as RUNNING and owned by the caller; the cases run
    after the response and the same row then holds the result."""
    with patch.object(Agent, "arun", side_effect=_tool_run):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    assert resp.status_code == 202
    body = resp.json()
    assert body["eval_data"] == {"summary": {"total": 2, "passed": 0, "failed": 0, "status": "RUNNING"}, "cases": []}
    assert body["user_id"] == "alice"

    # TestClient runs the background task before returning, so the row already holds the result.
    finished = client.get(f"/eval-runs/{body['id']}", headers=auth_header("alice")).json()
    assert finished["eval_data"]["summary"] == {"total": 2, "passed": 1, "failed": 1, "status": "FAIL"}
    assert [case["name"] for case in finished["eval_data"]["cases"]] == ["multiplies", "adds"]
    rows, total = db.get_eval_runs(deserialize=False, eval_type=["suite"])
    assert total == 1
    assert client.get(f"/eval-runs/{body['id']}", headers=auth_header("bob")).status_code == 404


@pytest.mark.parametrize(
    "failure,error", [(RuntimeError("judge unavailable"), "judge unavailable"), (asyncio.CancelledError(), "cancelled")]
)
def test_run_eval_suite_in_background_stores_an_error_when_the_run_fails(client, failure, error):
    """A failed or cancelled background run leaves the row as ERROR, never RUNNING."""
    with patch("agno.os.routers.evals.utils.arun_cases", side_effect=failure):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    assert resp.status_code == 202
    finished = client.get(f"/eval-runs/{resp.json()['id']}", headers=auth_header("alice")).json()
    assert finished["eval_data"]["summary"]["status"] == "ERROR"
    assert finished["eval_data"]["error"] == error


def test_run_eval_suite_from_body_in_background_is_answered_202(client):
    case = {"name": "multiplies", "agent_id": "assistant", "input": "10 times 5", "expected_tool_calls": ["multiply"]}
    with patch.object(Agent, "arun", side_effect=_tool_run):
        resp = client.post(
            "/eval-suites?background=true", json=_posted_suite(cases=[case]), headers=auth_header("alice")
        )
    assert resp.status_code == 202
    assert resp.json()["eval_data"]["summary"]["status"] == "RUNNING"
    finished = client.get(f"/eval-runs/{resp.json()['id']}", headers=auth_header("alice")).json()
    assert finished["eval_data"]["summary"]["status"] == "PASS"


def test_run_eval_suite_in_background_still_refuses_an_unknown_tag(client, db):
    resp = client.post(
        "/eval-suites/assistant-quality/runs?background=true", json={"tag": "nope"}, headers=auth_header("alice")
    )
    assert resp.status_code == 400
    assert db.get_eval_runs(deserialize=False, eval_type=["suite"])[1] == 0


def test_registered_eval_suite_runs_on_a_copy_of_the_agent(client, suite):
    """The cases run on a per-request copy, as every other run route does, never on the shared instance."""
    with patch.object(Agent, "arun", autospec=True, side_effect=_tool_run) as arun:
        resp = client.post("/eval-suites/assistant-quality/runs", json={}, headers=auth_header("alice"))
    assert resp.status_code == 200
    ran_on = {id(call.args[0]) for call in arun.call_args_list}
    assert ran_on and id(suite.cases[0].agent) not in ran_on


def test_run_eval_suite_from_body_does_not_store_case_dependencies(client, db):
    """A run's dependencies are never stored, so they stay out of the eval_input GET /eval-runs returns."""
    case = {
        "name": "multiplies",
        "agent_id": "assistant",
        "input": "10 times 5",
        "expected_tool_calls": ["multiply"],
        "dependencies": {"api_key": "secret"},
        "session_state": {"step": 1},
    }
    with patch.object(Agent, "arun", side_effect=_tool_run):
        resp = client.post("/eval-suites", json=_posted_suite(cases=[case]), headers=auth_header("alice"))
    assert resp.status_code == 200
    stored_case = resp.json()["eval_input"]["cases"][0]
    assert "dependencies" not in stored_case
    assert stored_case["session_state"] == {"step": 1}


def test_run_eval_suite_in_background_needs_a_db_that_can_update_the_run(client, db):
    """A db without update_eval_run_data could never replace the running row, so background is refused."""
    with patch.object(InMemoryDb, "update_eval_run_data", BaseDb.update_eval_run_data):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    assert resp.status_code == 501
    assert db.get_eval_runs(deserialize=False, eval_type=["suite"])[1] == 0


def test_run_eval_suite_in_background_fails_when_the_running_row_is_not_stored(client):
    with patch.object(InMemoryDb, "create_eval_run", return_value=None):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    assert resp.status_code == 500


def test_run_eval_suite_in_background_fails_when_the_owner_is_not_stored(client, db):
    """The poll is scoped to the owner, so a background run whose owner was not stored is removed and refused."""
    with patch.object(InMemoryDb, "update_eval_run_user_id", side_effect=RuntimeError("db down")):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    assert resp.status_code == 500
    assert db.get_eval_runs(deserialize=False, eval_type=["suite"])[1] == 0


def _store_suite_run(db, status: str, user_id: str = "alice") -> str:
    """Store a suite run as the background route does, with the given summary status."""
    record = EvalRunRecord(
        run_id=f"suite-run-{status.lower()}",
        eval_type=EvalType.SUITE,
        eval_data={"summary": {"total": 2, "passed": 0, "failed": 0, "status": status}, "cases": []},
        eval_input={"suite_id": "assistant-quality"},
        agent_id="assistant",
        name="Assistant quality",
    )
    db.create_eval_run(record)
    db.update_eval_run_user_id(eval_run_id=record.run_id, user_id=user_id)
    return record.run_id


def _delete_header(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_token(user_id, scopes=['evals:read', 'evals:delete'])}"}


def test_deleting_a_running_suite_run_cancels_it(client, db):
    """A deleted background suite run is cancelled, so its cases stop making model calls."""
    running, finished = _store_suite_run(db, "RUNNING"), _store_suite_run(db, "PASS")
    try:
        resp = client.request(
            "DELETE", "/eval-runs", json={"eval_run_ids": [running, finished]}, headers=_delete_header("alice")
        )
        assert resp.status_code == 204
        assert asyncio.run(ais_cancelled(running))
        assert not asyncio.run(ais_cancelled(finished))
    finally:
        asyncio.run(acleanup_run(running))


def test_deleting_a_running_suite_run_that_fails_keeps_it_running(client, db):
    """A failed delete withdraws the cancellation, so a run whose row is kept goes on."""
    run_id = _store_suite_run(db, "RUNNING")
    with patch.object(InMemoryDb, "delete_eval_runs", side_effect=RuntimeError("db down")):
        resp = client.request("DELETE", "/eval-runs", json={"eval_run_ids": [run_id]}, headers=_delete_header("alice"))
    assert resp.status_code == 500
    assert not asyncio.run(ais_cancelled(run_id))


def test_deleting_a_running_suite_run_whose_row_is_kept_keeps_it_running(client, db):
    """A database that swallows a failed delete keeps the row, so the run goes on."""
    run_id = _store_suite_run(db, "RUNNING")
    with patch.object(InMemoryDb, "delete_eval_runs", return_value=None):
        resp = client.request("DELETE", "/eval-runs", json={"eval_run_ids": [run_id]}, headers=_delete_header("alice"))
    assert resp.status_code == 204
    assert not asyncio.run(ais_cancelled(run_id))


def test_run_eval_suite_in_background_deleted_while_its_cases_run_stops_them(client):
    """A cancellation registered by a delete while the cases run stops them."""
    stopped = []

    async def slow_run(*args, **kwargs):
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            stopped.append(True)
            raise
        yield RunOutput(content="50", status=RunStatus.completed)

    with (
        patch.object(Agent, "arun", side_effect=slow_run),
        patch("agno.os.routers.evals.utils.ais_cancelled", return_value=True),
    ):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    assert resp.status_code == 202
    assert stopped == [True]
    # The run's cancellation is cleaned up when it ends.
    assert not asyncio.run(ais_cancelled(resp.json()["id"]))
