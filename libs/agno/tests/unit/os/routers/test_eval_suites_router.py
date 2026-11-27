"""Tests for the eval-suites REST API routes.

A suite registered on the OS is listed with its cases, and ``POST /eval-suites/{id}/runs``
persists one eval run of type ``suite`` whose ``eval_data`` is the ``SuiteResult`` payload,
so the pass rate shows up in ``GET /eval-runs`` like any other eval.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
from types import SimpleNamespace
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
from agno.exceptions import RunCancelledException
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.models.response import ToolExecution
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.job_queue import QueueWorker
from agno.os.routers.evals.utils import arun_queued_eval_suite
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.cancel import acleanup_run, ais_cancelled
from agno.session import AgentSession
from agno.team import Team


def _counts(summary: dict) -> dict:
    """The summary's counts and status, without its duration and metrics."""
    return {key: summary[key] for key in ("total", "passed", "failed", "status")}


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


async def _holds_lease() -> bool:
    return True


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


@pytest.fixture
def queued(db, suite):
    """A client whose app has a durable queue worker; the worker never runs, so a 202 means a ticket was
    enqueued and the tests call the queued runner themselves."""
    agent_os = AgentOS(id=TEST_OS_ID, agents=[suite.cases[0].agent], eval_suites=[suite], db=db)
    app = agent_os.get_app()
    store = InMemoryQueueStore()
    queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True))
    queue_worker.acancel_queued_eval_suite = partial(QueueWorker.acancel_queued_eval_suite, queue_worker)
    queue_worker._eval_suite_handles = lambda: (agent_os.dbs, None, None, None)
    app.state.queue_worker = queue_worker
    return SimpleNamespace(client=TestClient(app), store=store, dbs=agent_os.dbs, agents=[suite.cases[0].agent])


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
    assert _counts(body["eval_data"]["summary"]) == {"total": 2, "passed": 1, "failed": 1, "status": "FAIL"}
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
    assert _counts(body["eval_data"]["summary"]) == {"total": 2, "passed": 1, "failed": 1, "status": "FAIL"}
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
    assert _counts(finished["eval_data"]["summary"]) == {"total": 2, "passed": 1, "failed": 1, "status": "FAIL"}
    assert [case["name"] for case in finished["eval_data"]["cases"]] == ["multiplies", "adds"]
    rows, total = db.get_eval_runs(deserialize=False, eval_type=["suite"])
    assert total == 1
    assert client.get(f"/eval-runs/{body['id']}", headers=auth_header("bob")).status_code == 404


def test_run_eval_suite_in_background_stores_an_error_when_the_run_fails(client):
    """A failed background run leaves the row as ERROR, never RUNNING."""
    with patch("agno.os.routers.evals.utils.arun_cases", side_effect=RuntimeError("judge unavailable")):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    assert resp.status_code == 202
    finished = client.get(f"/eval-runs/{resp.json()['id']}", headers=auth_header("alice")).json()
    assert finished["eval_data"]["summary"]["status"] == "ERROR"
    assert finished["eval_data"]["error"] == "judge unavailable"


def test_run_eval_suite_in_background_cancelled_by_a_shutdown_is_cancelled(client):
    """A shutdown cancels the background run: the row is CANCELLED, as a cancelled background agent run is."""
    with patch("agno.os.routers.evals.utils.arun_cases", side_effect=asyncio.CancelledError()):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    assert resp.status_code == 202
    finished = client.get(f"/eval-runs/{resp.json()['id']}", headers=auth_header("alice")).json()
    assert finished["eval_data"]["summary"]["status"] == "CANCELLED"


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


@pytest.fixture
def cancelled_run_ids():
    """The run ids a test registers a cancellation for, cleaned up after it."""
    run_ids: list[str] = []
    yield run_ids
    for run_id in run_ids:
        asyncio.run(acleanup_run(run_id))


def test_cancel_eval_run_registers_the_cancellation_of_a_running_suite_run(client, db, cancelled_run_ids):
    run_id = _store_suite_run(db, "RUNNING")
    cancelled_run_ids.append(run_id)
    resp = client.post(f"/eval-runs/{run_id}/cancel", headers=auth_header("alice"))
    assert resp.status_code == 200
    assert resp.json() == {}
    assert asyncio.run(ais_cancelled(run_id))
    # The run is kept: the cases it stops write CANCELLED on it.
    assert db.get_eval_run(eval_run_id=run_id) is not None


def test_cancel_eval_run_of_a_finished_run_registers_nothing(client, db):
    run_id = _store_suite_run(db, "PASS")
    resp = client.post(f"/eval-runs/{run_id}/cancel", headers=auth_header("alice"))
    assert resp.status_code == 200
    assert not asyncio.run(ais_cancelled(run_id))


def test_cancel_eval_run_of_another_users_run_is_404(client, db):
    run_id = _store_suite_run(db, "RUNNING")
    assert client.post(f"/eval-runs/{run_id}/cancel", headers=auth_header("bob")).status_code == 404
    assert client.post("/eval-runs/missing/cancel", headers=auth_header("alice")).status_code == 404
    assert not asyncio.run(ais_cancelled(run_id))


def test_cancel_eval_run_is_gated_like_starting_the_run(client, db):
    """Cancelling needs evals:write, as starting the run does, and run on its agent, as the cancel routes need."""
    run_id = _store_suite_run(db, "RUNNING")
    read_only = {"Authorization": f"Bearer {create_token('alice', scopes=['evals:read', 'agents:assistant:run'])}"}
    assert client.post(f"/eval-runs/{run_id}/cancel", headers=read_only).status_code == 403
    no_run = {"Authorization": f"Bearer {create_token('alice', scopes=['evals:read', 'evals:write'])}"}
    assert client.post(f"/eval-runs/{run_id}/cancel", headers=no_run).status_code == 403
    assert not asyncio.run(ais_cancelled(run_id))


def test_run_eval_suite_in_background_cancelled_while_its_cases_run_is_cancelled(client):
    """A cancellation registered while the cases run stops them, and the row is kept as CANCELLED."""
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
    finished = client.get(f"/eval-runs/{resp.json()['id']}", headers=auth_header("alice")).json()
    assert finished["eval_data"]["summary"]["status"] == "CANCELLED"
    assert stopped == [True]
    # The run's cancellation is cleaned up when it ends.
    assert not asyncio.run(ais_cancelled(resp.json()["id"]))


def test_run_eval_suite_in_background_cancelled_before_it_starts_is_cancelled(client):
    """A cancellation stored before the run gets a slot stops it before any case runs."""
    with (
        patch.object(Agent, "arun", side_effect=_tool_run) as arun,
        patch("agno.run.cancel.ais_cancelled", return_value=True),
    ):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    assert resp.status_code == 202
    finished = client.get(f"/eval-runs/{resp.json()['id']}", headers=auth_header("alice")).json()
    assert finished["eval_data"]["summary"]["status"] == "CANCELLED"
    assert arun.call_count == 0


def _delete_header(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_token(user_id, scopes=['evals:read', 'evals:delete'])}"}


def test_deleting_a_running_suite_run_cancels_it(client, db, cancelled_run_ids):
    """A deleted background suite run is cancelled, so its cases stop making model calls."""
    running, finished = _store_suite_run(db, "RUNNING"), _store_suite_run(db, "PASS")
    cancelled_run_ids.append(running)
    resp = client.request(
        "DELETE", "/eval-runs", json={"eval_run_ids": [running, finished]}, headers=_delete_header("alice")
    )
    assert resp.status_code == 204
    assert asyncio.run(ais_cancelled(running))
    assert not asyncio.run(ais_cancelled(finished))


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


def test_run_eval_suite_in_background_cancelled_keeps_the_cases_that_finished(client):
    """A cancelled run keeps its finished cases, as a cancelled agent run keeps its output, and the rest are skipped."""
    started_slow = []

    async def run(*args, **kwargs):
        if kwargs.get("input") == "10 plus 5":
            started_slow.append(True)
            await asyncio.sleep(5)
        async for output in _tool_run():
            yield output

    async def cancelled_once_the_second_case_runs(run_id):
        return bool(started_slow)

    with (
        patch.object(Agent, "arun", side_effect=run),
        patch("agno.os.routers.evals.utils.ais_cancelled", side_effect=cancelled_once_the_second_case_runs),
    ):
        resp = client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=auth_header("alice"))
    finished = client.get(f"/eval-runs/{resp.json()['id']}", headers=auth_header("alice")).json()
    assert _counts(finished["eval_data"]["summary"]) == {"total": 2, "passed": 1, "failed": 1, "status": "CANCELLED"}
    first, second = finished["eval_data"]["cases"]
    assert (first["name"], first["passed"]) == ("multiplies", True)
    assert (second["name"], second["skipped"], second["error"]) == (
        "adds",
        True,
        "skipped: suite aborted after cancelled run",
    )


def test_run_eval_suite_whose_case_run_is_cancelled_is_cancelled(client):
    """Cancelling a case's own agent run aborts the suite, so the run reads as cancelled, not failed."""

    async def cancelled_run(*args, **kwargs):
        yield RunOutput(content="", status=RunStatus.cancelled)

    with patch.object(Agent, "arun", side_effect=cancelled_run):
        resp = client.post("/eval-suites/assistant-quality/runs", json={}, headers=auth_header("alice"))
    assert resp.status_code == 200
    eval_data = resp.json()["eval_data"]
    assert eval_data["summary"]["status"] == "CANCELLED"
    assert eval_data["cases"][1]["skipped"] is True


def _remote_client():
    """An eval router over a RemoteDb only, as on an AgentOS whose evals live on a remote AgentOS."""
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import FastAPI

    from agno.os.routers.evals import get_eval_router
    from agno.os.routers.evals.schemas import EvalSchema
    from agno.remote.base import RemoteDb

    remote_db = MagicMock(spec=RemoteDb)
    remote_db.id = "remote-db"
    remote_run = EvalSchema.model_validate(
        {"id": "remote-run", "eval_type": "suite", "eval_data": {"summary": {"status": "PASS"}, "cases": []}}
    )
    remote_db.run_eval_suite = AsyncMock(return_value=remote_run)
    remote_db.run_eval_suite_from_body = AsyncMock(return_value=remote_run)
    remote_db.cancel_eval_run = AsyncMock(return_value=None)
    app = FastAPI()
    app.include_router(get_eval_router(dbs={"remote-db": [remote_db]}))
    return TestClient(app), remote_db


def test_run_eval_suite_on_a_remote_db_is_forwarded_to_the_remote_os():
    """A suite on a RemoteDb runs on the remote AgentOS, as POST /eval-runs forwards a single eval."""
    client, remote_db = _remote_client()
    resp = client.post(
        "/eval-suites/nightly/runs?db_id=remote-db&background=true",
        json={"tag": "smoke"},
        headers={"Authorization": "Bearer token-1"},
    )
    assert resp.status_code == 202
    assert resp.json()["id"] == "remote-run"
    assert remote_db.run_eval_suite.call_args.args == ("nightly",)
    forwarded = remote_db.run_eval_suite.call_args.kwargs
    assert (forwarded["tag"], forwarded["background"], forwarded["db_id"]) == ("smoke", True, "remote-db")
    assert forwarded["headers"] == {"Authorization": "Bearer token-1"}

    body = _posted_suite()
    resp = client.post("/eval-suites?db_id=remote-db", json=body)
    assert resp.status_code == 200
    assert remote_db.run_eval_suite_from_body.call_args.kwargs["cases"][0].agent_id == "assistant"


def test_cancel_on_a_remote_db_is_forwarded_to_the_remote_os():
    client, remote_db = _remote_client()
    assert client.post("/eval-runs/remote-run/cancel?db_id=remote-db").status_code == 200
    assert remote_db.cancel_eval_run.call_args.args == ("remote-run",)


def test_cancel_on_a_remote_db_passes_the_remote_status_through():
    """A remote AgentOS that refuses the cancel is answered with its status, as every remote forward is."""
    import httpx

    client, remote_db = _remote_client()
    remote_response = httpx.Response(
        404,
        json={"detail": "Eval run with id 'nope' not found"},
        request=httpx.Request("POST", "http://remote-os/eval-runs/nope/cancel"),
    )
    remote_db.cancel_eval_run.side_effect = lambda *args, **kwargs: remote_response.raise_for_status()
    os_app = AgentOS(agents=[Agent(id="assistant")]).get_app()
    client.app.add_exception_handler(httpx.HTTPStatusError, os_app.exception_handlers[httpx.HTTPStatusError])
    assert client.post("/eval-runs/nope/cancel?db_id=remote-db").status_code == 404


def test_run_eval_suite_in_background_rides_the_durable_queue(queued, suite):
    """With a durable queue the background run is a ticket a worker finishes, not an in-process task.
    The ticket keeps the posted dependencies so the worker can rerun the cases; the stored eval_input does not."""
    case = {
        "name": "multiplies",
        "agent_id": "assistant",
        "input": "10 times 5",
        "expected_tool_calls": ["multiply"],
        "dependencies": {"api_key": "SECRET-123"},
    }
    resp = queued.client.post("/eval-suites?background=true", json=_posted_suite(cases=[case]))
    assert resp.status_code == 202
    run_id = resp.json()["id"]
    job = asyncio.run(queued.store.get_job(run_id))
    assert job["job_type"] == "eval_suite"
    assert job["payload"]["suite"]["cases"][0]["dependencies"] == {"api_key": "SECRET-123"}
    stored = queued.client.get(f"/eval-runs/{run_id}").json()
    assert stored["eval_data"]["summary"]["status"] == "RUNNING"
    assert "dependencies" not in stored["eval_input"]["cases"][0]

    with patch.object(Agent, "arun", side_effect=_tool_run):
        assert asyncio.run(arun_queued_eval_suite(queued.dbs, queued.agents, None, [suite], job, _holds_lease)) is True
    assert queued.client.get(f"/eval-runs/{run_id}").json()["eval_data"]["summary"]["status"] == "PASS"


def test_run_eval_suite_in_background_keeps_a_result_an_earlier_attempt_stored(queued, db, suite):
    """A ticket reclaimed after its row already holds PASS or FAIL settles without running the cases again."""
    resp = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={})
    assert resp.status_code == 202
    run_id = resp.json()["id"]
    job = asyncio.run(queued.store.get_job(run_id))
    finished = {"summary": {"total": 1, "passed": 1, "failed": 0, "status": "PASS"}, "cases": []}
    db.update_eval_run_data(eval_run_id=run_id, eval_data=finished)

    with patch("agno.os.routers.evals.utils.arun_cases") as run_cases:
        assert asyncio.run(arun_queued_eval_suite(queued.dbs, queued.agents, None, [suite], job, _holds_lease)) is True
    assert run_cases.call_count == 0
    assert queued.client.get(f"/eval-runs/{run_id}").json()["eval_data"] == finished


def test_run_eval_suite_in_background_with_a_reused_idempotency_key_returns_the_original_run(queued, db):
    """A retried background submission with the same Idempotency-Key gets the original run, not a second one."""
    headers = {"Idempotency-Key": "suite-retry-1"}
    first = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=headers)
    second = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert len(queued.store._jobs) == 1
    assert db.get_eval_runs(deserialize=False, eval_type=["suite"])[1] == 1


def test_run_eval_suite_in_background_replay_before_the_prepare_answers_from_the_ticket(queued):
    """A replay that lands before the original prepare wrote the row is answered from the ticket, not a 409."""
    headers = {"Idempotency-Key": "suite-retry-2"}
    with patch.object(InMemoryDb, "create_eval_run", return_value=None):
        first = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=headers)
    assert first.status_code == 500
    job = next(iter(queued.store._jobs.values()))
    job["status"] = "queued"
    second = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=headers)
    assert second.status_code == 202
    assert second.json()["id"] == job["id"]
    assert second.json()["eval_data"]["summary"]["status"] == "RUNNING"


def test_run_eval_suite_in_background_claim_rereads_a_row_the_accepting_request_wrote(queued, db, suite):
    """A claim-time create that loses to the accepting request's own write re-reads the row and runs the suite."""
    resp = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={"tag": "smoke"})
    run_id = resp.json()["id"]
    job = asyncio.run(queued.store.get_job(run_id))
    db.delete_eval_runs(eval_run_ids=[run_id])
    real_create = db.create_eval_run

    def create_after_the_request(eval_run):
        real_create(eval_run)
        return None

    with (
        patch.object(db, "create_eval_run", side_effect=create_after_the_request),
        patch.object(Agent, "arun", side_effect=_tool_run),
    ):
        assert asyncio.run(arun_queued_eval_suite(queued.dbs, queued.agents, None, [suite], job, _holds_lease)) is True
    assert queued.client.get(f"/eval-runs/{run_id}").json()["eval_data"]["summary"]["status"] == "PASS"


def test_run_eval_suite_in_background_replay_after_a_delete_answers_the_ticket_status(queued, db):
    """A replay of a run whose ticket was cancelled and whose row is gone is CANCELLED, never RUNNING."""
    headers = {"Idempotency-Key": "suite-retry-3"}
    first = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=headers)
    run_id = first.json()["id"]
    queued.store._jobs[run_id]["status"] = "cancelled"
    db.delete_eval_runs(eval_run_ids=[run_id])
    second = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}, headers=headers)
    assert second.status_code == 202
    assert second.json()["eval_data"]["summary"]["status"] == "CANCELLED"
    assert "error" not in second.json()["eval_data"]


def test_deleting_a_background_eval_suite_run_cancels_its_ticket(queued):
    """Deleting a queued suite run tombstones its waiting ticket and registers its cancellation."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    try:
        assert queued.client.request("DELETE", "/eval-runs", json={"eval_run_ids": [run_id]}).status_code == 204
        assert asyncio.run(queued.store.get_job(run_id))["status"] == "cancelled"
        assert asyncio.run(ais_cancelled(run_id))
    finally:
        asyncio.run(acleanup_run(run_id))


def test_deleting_a_background_eval_suite_run_that_fails_leaves_its_ticket(queued):
    """A delete that fails leaves the waiting ticket, so no cancelled ticket sits over a RUNNING row."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    try:
        with patch.object(InMemoryDb, "delete_eval_runs", side_effect=RuntimeError("db down")):
            resp = queued.client.request("DELETE", "/eval-runs", json={"eval_run_ids": [run_id]})
        assert resp.status_code == 500
        assert asyncio.run(queued.store.get_job(run_id))["status"] == "queued"
        assert not asyncio.run(ais_cancelled(run_id)), "a failed delete withdraws the cancellation"
        assert queued.client.get(f"/eval-runs/{run_id}").json()["eval_data"]["summary"]["status"] == "RUNNING"
    finally:
        asyncio.run(acleanup_run(run_id))


def test_eval_run_response_leaves_out_the_queue_attempt(queued, db):
    """The queue fence's attempt stays stored but is left out of the response, as RunSchema leaves it out."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    eval_data = db.get_eval_run(run_id, deserialize=False)["eval_data"]
    db.update_eval_run_data(eval_run_id=run_id, eval_data={**eval_data, "queue_attempt": 2})
    assert "queue_attempt" not in queued.client.get(f"/eval-runs/{run_id}").json()["eval_data"]
    assert all("queue_attempt" not in run["eval_data"] for run in queued.client.get("/eval-runs").json()["data"])
    assert db.get_eval_run(run_id, deserialize=False)["eval_data"]["queue_attempt"] == 2


def test_deleting_a_finished_eval_suite_run_registers_no_cancellation(queued, db):
    """A finished suite run has nothing to cancel: deleting it registers no cancellation."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    try:
        eval_data = db.get_eval_run(run_id, deserialize=False)["eval_data"]
        db.update_eval_run_data(
            eval_run_id=run_id, eval_data={**eval_data, "summary": {**eval_data["summary"], "status": "PASS"}}
        )
        assert queued.client.request("DELETE", "/eval-runs", json={"eval_run_ids": [run_id]}).status_code == 204
        assert not asyncio.run(ais_cancelled(run_id))
    finally:
        asyncio.run(acleanup_run(run_id))


def test_deleting_a_background_eval_suite_run_whose_row_is_kept_leaves_its_ticket(queued):
    """A database that swallows a failed delete keeps the row: its ticket and run are left alone."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    try:
        with patch.object(InMemoryDb, "delete_eval_runs", return_value=None):
            assert queued.client.request("DELETE", "/eval-runs", json={"eval_run_ids": [run_id]}).status_code == 204
        assert asyncio.run(queued.store.get_job(run_id))["status"] == "queued"
        assert not asyncio.run(ais_cancelled(run_id))
    finally:
        asyncio.run(acleanup_run(run_id))


def test_deleting_a_background_eval_suite_run_whose_read_fails_deletes_nothing(queued):
    """A delete whose suite-run read fails answers 500 before any row is gone, so the run is never left uncancelled."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    with patch("agno.os.routers.evals.evals.aread_eval_suite_run", side_effect=RuntimeError("db down")):
        resp = queued.client.request("DELETE", "/eval-runs", json={"eval_run_ids": [run_id]})
    assert resp.status_code == 500
    assert asyncio.run(queued.store.get_job(run_id))["status"] == "queued"
    assert queued.client.get(f"/eval-runs/{run_id}").json()["eval_data"]["summary"]["status"] == "RUNNING"


def test_deleting_a_claimed_background_eval_suite_run_cancels_it(queued, suite):
    """Deleting a suite run a worker has claimed cancels it there: no case runs and the row is not recreated."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    worker = QueueWorker(
        store=queued.store,
        resolve_component=lambda ctype, cid: None,
        config=QueueConfig(durable=True),
        worker_id="live-worker",
    )
    worker._resolve_eval_suite_handles = lambda: (queued.dbs, queued.agents, None, [suite])
    try:
        claimed = asyncio.run(queued.store.claim_job(worker.worker_id))
        assert queued.client.request("DELETE", "/eval-runs", json={"eval_run_ids": [run_id]}).status_code == 204
        with patch.object(Agent, "arun", side_effect=_tool_run) as arun:
            asyncio.run(worker._execute_claimed(claimed))
        arun.assert_not_called()
        assert asyncio.run(queued.store.get_job(run_id))["status"] == "cancelled"
        assert queued.client.get(f"/eval-runs/{run_id}").status_code == 404
    finally:
        asyncio.run(acleanup_run(run_id))


def test_run_eval_suite_in_background_does_not_recreate_a_row_deleted_after_attempt_1(queued, db, suite):
    """Attempt 1 ensured the row, so a later attempt that finds none treats the run as deleted and runs nothing."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    job = {**asyncio.run(queued.store.get_job(run_id)), "attempt": 2}
    db.delete_eval_runs(eval_run_ids=[run_id])
    with patch.object(Agent, "arun", side_effect=_tool_run) as arun:
        with pytest.raises(RunCancelledException):
            asyncio.run(arun_queued_eval_suite(queued.dbs, queued.agents, None, [suite], job, _holds_lease))
    arun.assert_not_called()
    assert queued.client.get(f"/eval-runs/{run_id}").status_code == 404


def test_run_eval_suite_in_background_fenced_out_result_is_dropped(queued, db, suite):
    """A database with a fenced eval-row write drops a stale attempt's result, as a fenced run save is dropped."""
    from agno.run.status_persist import RunPersistOutcome

    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={"tag": "smoke"}).json()[
        "id"
    ]
    job = asyncio.run(queued.store.get_job(run_id))
    fenced = []

    def update_eval_run_data_in_attempt(eval_run_id, eval_data, expected_attempt):
        fenced.append(expected_attempt)
        return RunPersistOutcome.UPDATED if len(fenced) == 1 else RunPersistOutcome.STALE_ATTEMPT

    db.update_eval_run_data_in_attempt = update_eval_run_data_in_attempt
    try:
        with patch.object(Agent, "arun", side_effect=_tool_run):
            assert (
                asyncio.run(arun_queued_eval_suite(queued.dbs, queued.agents, None, [suite], job, _holds_lease)) is None
            )
    finally:
        del db.update_eval_run_data_in_attempt
    assert fenced == [job["attempt"], job["attempt"]], "the claim stamps the attempt, then the result write is fenced"
    assert queued.client.get(f"/eval-runs/{run_id}").json()["eval_data"]["summary"]["status"] == "RUNNING"


def _live_worker(queued, suite):
    worker = QueueWorker(
        store=queued.store,
        resolve_component=lambda ctype, cid: None,
        config=QueueConfig(durable=True),
        worker_id="live-worker",
    )
    worker._resolve_eval_suite_handles = lambda: (queued.dbs, queued.agents, None, [suite])
    return worker


def test_cancelling_a_queued_eval_suite_run_tombstones_its_ticket(queued):
    """A cancel tombstones a ticket no worker claimed yet, row first, as the run cancel routes do."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    try:
        assert queued.client.post(f"/eval-runs/{run_id}/cancel").status_code == 200
        assert asyncio.run(queued.store.get_job(run_id))["status"] == "cancelled"
        assert queued.client.get(f"/eval-runs/{run_id}").json()["eval_data"]["summary"]["status"] == "CANCELLED"
    finally:
        asyncio.run(acleanup_run(run_id))


def test_queued_eval_suite_run_cancelled_while_its_cases_run_keeps_the_cases_that_finished(queued, suite):
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    worker = _live_worker(queued, suite)
    started_slow = []

    async def run(*args, **kwargs):
        if kwargs.get("input") == "10 plus 5":
            started_slow.append(True)
            await asyncio.sleep(5)
        async for output in _tool_run():
            yield output

    async def cancelled_once_the_second_case_runs(run_id):
        return bool(started_slow)

    claimed = asyncio.run(queued.store.claim_job(worker.worker_id))
    with (
        patch.object(Agent, "arun", side_effect=run),
        patch("agno.os.routers.evals.utils.ais_cancelled", side_effect=cancelled_once_the_second_case_runs),
    ):
        asyncio.run(worker._execute_claimed(claimed))
    eval_data = queued.client.get(f"/eval-runs/{run_id}").json()["eval_data"]
    assert eval_data["summary"]["status"] == "CANCELLED"
    assert [(case["name"], case["skipped"]) for case in eval_data["cases"]] == [("multiplies", False), ("adds", True)]
    assert asyncio.run(queued.store.get_job(run_id))["status"] == "cancelled"


def test_claimed_eval_suite_run_whose_row_is_cancelled_is_not_run(queued, db, suite):
    """A row CANCELLED before the claim ran it is honoured: no case runs and the ticket tombstones."""
    run_id = queued.client.post("/eval-suites/assistant-quality/runs?background=true", json={}).json()["id"]
    row = db.get_eval_run(eval_run_id=run_id, deserialize=False)
    db.update_eval_run_data(
        eval_run_id=run_id,
        eval_data={**row["eval_data"], "summary": {**row["eval_data"]["summary"], "status": "CANCELLED"}},
    )
    worker = _live_worker(queued, suite)
    claimed = asyncio.run(queued.store.claim_job(worker.worker_id))
    with patch.object(Agent, "arun", side_effect=_tool_run) as arun:
        asyncio.run(worker._execute_claimed(claimed))
    arun.assert_not_called()
    assert asyncio.run(queued.store.get_job(run_id))["status"] == "cancelled"
