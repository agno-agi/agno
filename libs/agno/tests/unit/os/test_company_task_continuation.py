"""Evidence read from the run, Task state for Super Agent, and continuing a Task from a reply."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company.evidence import MAX_ITEMS, NO_EVIDENCE, run_evidence
from agno.db.schemas.tasks import task_run_id
from agno.db.sqlite import SqliteDb
from agno.job_queue import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.job_queue import QueueWorker
from agno.os.manager.company_tasks import CompanyTaskTools
from agno.os.routers.company.runs import _task_state
from agno.registry import Registry
from agno.run import RunContext
from agno.run.authorization import RunAuthorization

SECRET = "company-continuation-tests-secret-at-least-32-bytes"
SCOPES = [
    "products:read",
    "products:write",
    "projects:write",
    "tasks:read",
    "tasks:write",
    "wiki:read",
    "agents:writer:run",
]


# ---------------------------------------------------------------------------
# Evidence read from the run
# ---------------------------------------------------------------------------
def test_evidence_records_what_the_run_did():
    run = {
        "tools": [
            {
                "tool_name": "Bash",
                "tool_args": {"command": "pytest -q"},
                "result": "3 passed",
                "tool_call_error": False,
            },
            {"tool_name": "shell", "tool_args": {"command": "git diff"}, "result": "x" * 5000},
            {"tool_name": "search_docs", "tool_args": {"query": "export"}, "result": "found", "tool_call_error": True},
        ],
        "member_responses": [{"agent_id": "tester", "tools": [{"tool_name": "Read", "tool_args": {"path": "a.py"}}]}],
        "step_results": [{"step_name": "Reproduce", "content": "fails on main", "success": False}],
        "files": [{"filename": "report.md"}],
        "metadata": {
            "sandbox": {"repository": {"url": "https://github.com/o/r", "branch": "main", "commit": "abc123"}}
        },
    }
    evidence, note = run_evidence(run)
    assert note is None
    assert [item["kind"] for item in evidence] == ["command", "command", "tool", "tool", "step", "file", "checkout"]
    # Outputs stay in the run; the summary has names, inputs and whether each failed.
    assert evidence[0] == {"kind": "command", "name": "Bash", "input": "pytest -q", "error": False}
    assert all("output" not in item for item in evidence)
    assert evidence[2]["error"] is True and json.loads(evidence[2]["input"]) == {"query": "export"}
    assert evidence[3]["member"] == "tester"
    assert run_evidence({"tools": [{"tool_name": "list_roles", "tool_args": {}}]})[0][0]["input"] is None
    assert evidence[4]["error"] is True and evidence[6]["input"] == "main@abc123"
    long_input = run_evidence({"tools": [{"tool_name": "write", "tool_args": {"text": "x" * 5000}}]})[0][0]["input"]
    assert long_input.endswith("more characters]") and len(long_input) < 400


def test_missing_and_excess_evidence_is_said_plainly():
    assert run_evidence({"content": "All good"}) == ([], NO_EVIDENCE)
    many = {"tools": [{"tool_name": "Bash", "tool_args": {"command": f"echo {i}"}} for i in range(MAX_ITEMS + 5)]}
    evidence, note = run_evidence(many)
    assert len(evidence) == MAX_ITEMS and note and str(MAX_ITEMS + 5) in note


# ---------------------------------------------------------------------------
# Task state for Super Agent
# ---------------------------------------------------------------------------
def task_row(**overrides):
    row = {
        "id": "t1",
        "title": "Investigate",
        "status": "in_progress",
        "executor_id": "writer",
        "job_id": "r2",
        "transitions": [
            {"attempt": 1, "started_by": "alice", "requested_from": {"session_id": "chat-1"}},
            {"attempt": 2, "started_by": "bob", "follow_up": {"message": "Go with A", "in_reply_to_attempt": 1}},
        ],
        "result": None,
    }
    return {**row, **overrides}


def test_state_reports_waiting_runs_and_recorded_results():
    paused = _task_state(task_row(), {"status": "paused"})
    assert paused["run_status"] == "PAUSED" and "approve" in paused["waiting_on"]
    assert paused["follow_up"]["message"] == "Go with A" and paused["attempt"] == 2

    finished = _task_state(
        task_row(status="in_review", result={"run_id": "r2", "status": "COMPLETED", "content": "Done"})
    )
    assert finished["meaning"] == "finished, waiting for review" and finished["run_status"] == "COMPLETED"
    assert finished["result"] == {"content": "Done"}


# ---------------------------------------------------------------------------
# continue_company_task
# ---------------------------------------------------------------------------
def headers():
    token = jwt.encode(
        {
            "sub": "alice",
            "aud": "company-continuation",
            "scopes": SCOPES,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def system(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    writer = Agent(id="writer", db=db)
    agent_os = AgentOS(
        id="company-continuation",
        db=db,
        registry=Registry(agents=[writer]),
        company=CompanyConfig(),
        telemetry=False,
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()
    queue = QueueWorker(InMemoryQueueStore(), lambda *a, **k: writer, QueueConfig(durable=True), authorization_app=app)
    queue._company_db = db
    app.state.queue_worker = queue
    agent_os._company_app = app
    yield TestClient(app), db, agent_os, queue
    db.close()


def reviewed_task(client, db, queue):
    product = client.post("/company/products", json={"name": "SDK"}, headers=headers()).json()
    project = client.post(
        "/company/projects", json={"product_id": product["id"], "name": "Release"}, headers=headers()
    ).json()
    client.post(
        f"/company/projects/{project['id']}/transitions",
        json={"target": "active", "reason": "Approved"},
        headers=headers(),
    )
    task = client.post(
        "/company/tasks",
        json={"product_id": product["id"], "project_id": project["id"], "title": "Investigate", "brief": "Find why"},
        headers=headers(),
    ).json()
    client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    ).raise_for_status()
    assert client.post(f"/company/tasks/{task['id']}/runs", headers=headers()).status_code == 202
    first = task_run_id(task["id"], 1)
    # Settle attempt 1 as a worker would: its ticket finishes and its result is saved.
    queue.store._jobs[first]["status"] = "completed"
    db.complete_task_run(
        task["id"],
        first,
        {"run_id": first, "status": "COMPLETED", "content": "Found it. Fix A or B?"},
        expected_transitions=db.get_task(task["id"])["transitions"],
    )
    return db.get_task(task["id"])


def context(scopes=SCOPES):
    authority = RunAuthorization(
        ScopeAuthorizationProvider(), AuthorizationContext(principal_id="alice", scopes=scopes, claims={"sub": "alice"})
    )
    return RunContext(run_id="chat-run", session_id="chat-1", user_id="alice", authorization=authority)


def test_super_agent_continues_a_task_with_the_persons_words(system):
    client, db, agent_os, queue = system
    task = reviewed_task(client, db, queue)
    assert task["status"] == "in_review"
    tools = CompanyTaskTools(agent_os)
    # Starting is not continuing: start refuses a Task waiting for review.
    assert "Continue it" in asyncio.run(tools.astart_company_task(task["id"], _agno_run_context=context()))
    reply = asyncio.run(tools.acontinue_company_task(task["id"], "Go with A", _agno_run_context=context()))
    second = task_run_id(task["id"], 2)
    assert reply.startswith("Continued 'Investigate'") and second in reply

    entry = db.get_task(task["id"])["transitions"][-1]
    assert entry["follow_up"] == {"message": "Go with A", "from": "alice", "in_reply_to_attempt": 1}
    assert entry["requested_from"]["session_id"] == "chat-1"
    payload = json.loads(asyncio.run(queue.store.get_job(second))["payload"]["input"])
    assert payload["previous_result"]["content"] == "Found it. Fix A or B?"

    functions = tools.get_async_functions()
    assert functions["continue_company_task"].stop_after_tool_call is True
    state = json.loads(asyncio.run(tools.aget_company_task_status(task["id"], _agno_run_context=context())))
    assert state["attempt"] == 2 and state["follow_up"]["message"] == "Go with A" and state["run_status"] == "PENDING"
    # Evidence is read from the run when asked; attempt 2 is queued and has recorded nothing yet.
    assert state["evidence"] == [] and state["evidence_note"] == NO_EVIDENCE


def test_status_reads_evidence_from_the_run(system, monkeypatch):
    from agno.os.routers.company.runs import _TaskStarter

    client, db, agent_os, queue = system
    task = reviewed_task(client, db, queue)
    run = {"run_data": {"tools": [{"tool_name": "list_roles", "tool_args": {"scope": "billing"}, "result": "secret"}]}}

    class RunStore:
        def get_run(self, run_id, deserialize=False):
            assert run_id == task["job_id"] and deserialize is False
            return run

    monkeypatch.setattr(_TaskStarter, "run_database", lambda self, value: RunStore())
    state = json.loads(
        asyncio.run(CompanyTaskTools(agent_os).aget_company_task_status(task["id"], _agno_run_context=context()))
    )
    assert state["evidence"] == [
        {"kind": "tool", "name": "list_roles", "input": '{"scope": "billing"}', "error": False}
    ]
    # Outputs never reach the model's context.
    assert "secret" not in json.dumps(state)


def test_a_cancelled_project_refuses_a_reply_before_queueing(system):
    client, db, agent_os, queue = system
    task = reviewed_task(client, db, queue)
    client.post(
        f"/company/projects/{task['project_id']}/transitions",
        json={"target": "cancelled", "reason": "Dropped"},
        headers=headers(),
    ).raise_for_status()

    response = client.post(f"/company/tasks/{task['id']}/continue", json={"message": "Go with A"}, headers=headers())
    assert response.status_code == 409 and response.json()["detail"] == "Cannot start Task work in a cancelled Project"
    reply = asyncio.run(
        CompanyTaskTools(agent_os).acontinue_company_task(task["id"], "Go", _agno_run_context=context())
    )
    assert reply == "Not continued: Cannot start Task work in a cancelled Project"
    assert asyncio.run(queue.store.get_job(task_run_id(task["id"], 2))) is None


@pytest.mark.parametrize("missing", ["tasks:write", "wiki:read", "agents:writer:run"])
def test_continuing_needs_the_start_routes_grants(system, missing):
    client, db, agent_os, queue = system
    task = reviewed_task(client, db, queue)
    scopes = [scope for scope in SCOPES if scope != missing]
    reply = asyncio.run(
        CompanyTaskTools(agent_os).acontinue_company_task(task["id"], "Go", _agno_run_context=context(scopes))
    )
    assert reply.startswith("Not continued:"), reply
    assert asyncio.run(queue.store.get_job(task_run_id(task["id"], 2))) is None
