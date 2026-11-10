"""Super Agent starts accepted Tasks through the Company start path and reads their state without waiting."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
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
from agno.registry import Registry
from agno.run import RunContext
from agno.run.authorization import RunAuthorization

SECRET = "company-task-tools-tests-secret-at-least-32-bytes"
SCOPES = ["products:read", "products:write", "projects:write", "tasks:read", "tasks:write", "wiki:read"]
RUN_SCOPES = [*SCOPES, "agents:writer:run"]


def headers(scopes=None, user="alice"):
    token = jwt.encode(
        {
            "sub": user,
            "aud": "company-task-tools",
            "scopes": RUN_SCOPES if scopes is None else scopes,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


@pytest.fixture(params=[False, True], ids=["shared", "isolated"])
def system(request, tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    writer = Agent(id="writer", db=db)
    agent_os = AgentOS(
        id="company-task-tools",
        db=db,
        registry=Registry(agents=[writer]),
        company=CompanyConfig(),
        telemetry=False,
        user_isolation=request.param,
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()
    queue = QueueWorker(InMemoryQueueStore(), lambda *a, **k: writer, QueueConfig(durable=True), authorization_app=app)
    queue._company_db = db
    app.state.queue_worker = queue
    # The Company lifespan publishes the app to Super Agent tools; these tests drive it without a lifespan.
    agent_os._company_app = app
    yield TestClient(app), db, agent_os, queue
    db.close()


def task(client, accept=True):
    product = client.post("/company/products", json={"name": "SDK"}, headers=headers()).json()
    project = client.post(
        "/company/projects", json={"product_id": product["id"], "name": "Release"}, headers=headers()
    ).json()
    client.post(
        f"/company/projects/{project['id']}/transitions",
        json={"target": "active", "reason": "Approved"},
        headers=headers(),
    )
    created = client.post(
        "/company/tasks",
        json={"product_id": product["id"], "project_id": project["id"], "title": "Draft", "brief": "Write"},
        headers=headers(),
    ).json()
    if not accept:
        return created
    response = client.post(
        f"/company/tasks/{created['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    return response.json()


def context(scopes=None, user="alice", authority_class=RunAuthorization):
    authority = authority_class(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id=user, scopes=RUN_SCOPES if scopes is None else scopes, claims={"sub": user}),
    )
    return RunContext(run_id="coordinator-run", session_id="coordinator-session", user_id=user, authorization=authority)


def start(agent_os, task_id, run_context):
    return asyncio.run(CompanyTaskTools(agent_os).astart_company_task(task_id, _agno_run_context=run_context))


def status(agent_os, task_id, run_context):
    return json.loads(
        asyncio.run(CompanyTaskTools(agent_os).aget_company_task_status(task_id, _agno_run_context=run_context))
    )


def test_start_queues_one_attempt_and_records_the_conversation(system):
    client, db, agent_os, queue = system
    accepted = task(client)
    reply = start(agent_os, accepted["id"], context())
    run_id = task_run_id(accepted["id"], 1)
    assert reply.startswith("Queued 'Draft'") and run_id in reply

    job = asyncio.run(queue.store.get_job(run_id))
    assert job is not None and job["session_id"] == accepted["session_id"] != "coordinator-session"
    assert job["payload"]["company_requested_from"] == {
        "session_id": "coordinator-session",
        "run_id": "coordinator-run",
        "team_id": "superagent",
    }
    started = db.get_task(accepted["id"])
    entry = started["transitions"][-1]
    assert started["status"] == "in_progress" and entry["attempt"] == 1 and entry["started_by"] == "alice"
    assert entry["requested_from"]["session_id"] == "coordinator-session"

    # A repeated start, from the tool or the API, joins the same attempt.
    assert run_id in start(agent_os, accepted["id"], context())
    again = client.post(f"/company/tasks/{accepted['id']}/runs", headers=headers())
    assert again.status_code == 202 and again.json()["run_id"] == run_id
    attempts = [entry for entry in db.get_task(accepted["id"])["transitions"] if entry.get("attempt")]
    assert len(attempts) == 1


def test_status_reads_saved_state_without_waiting(system):
    client, db, agent_os, queue = system
    accepted = task(client)
    assert status(agent_os, accepted["id"], context())["status"] == "ready"
    start(agent_os, accepted["id"], context())
    state = status(agent_os, accepted["id"], context())
    assert state["status"] == "in_progress" and state["run_status"] == "PENDING"
    assert state["attempt"] == 1 and state["requested_from"]["run_id"] == "coordinator-run"
    assert "Cannot read" in json.dumps(
        asyncio.run(
            CompanyTaskTools(agent_os).aget_company_task_status(accepted["id"], _agno_run_context=context(scopes=[]))
        )
    )


@pytest.mark.parametrize(
    "scopes",
    [[s for s in RUN_SCOPES if s != "agents:writer:run"], [s for s in RUN_SCOPES if s != "tasks:write"]],
    ids=["no-executor-run", "no-task-write"],
)
def test_start_refuses_callers_without_the_routes_grants(system, scopes):
    client, db, agent_os, queue = system
    accepted = task(client)
    reply = start(agent_os, accepted["id"], context(scopes=scopes))
    assert reply.startswith("Not started")
    assert asyncio.run(queue.store.get_job(task_run_id(accepted["id"], 1))) is None
    assert db.get_task(accepted["id"])["status"] == "ready"


def test_start_never_accepts_or_revises_work(system):
    client, db, agent_os, queue = system
    proposal = task(client, accept=False)
    assert "still a proposal" in start(agent_os, proposal["id"], context())
    assert db.get_task(proposal["id"])["status"] == "backlog"

    accepted = task(client)
    first = task_run_id(accepted["id"], 1)
    assert client.post(f"/company/tasks/{accepted['id']}/runs", headers=headers()).status_code == 202
    running = db.get_task(accepted["id"])
    db.complete_task_run(
        accepted["id"],
        first,
        {"run_id": first, "status": "COMPLETED", "content": "Draft written"},
        expected_transitions=running["transitions"],
    )
    assert db.get_task(accepted["id"])["status"] == "in_review"
    # A revision is a person's decision; the tool does not start attempt 2.
    assert "waiting for review" in start(agent_os, accepted["id"], context())
    assert asyncio.run(queue.store.get_job(task_run_id(accepted["id"], 2))) is None


def test_automated_and_anonymous_callers_are_refused(system):
    from agno.company.execution import _ExecutorAuthorization

    client, db, agent_os, queue = system
    accepted = task(client)
    automated = context()
    automated.authorization = _ExecutorAuthorization(automated.authorization)
    assert "started by people" in start(agent_os, accepted["id"], automated)
    if agent_os.user_isolation:
        anonymous = RunContext(run_id="r", session_id="s", user_id=None, authorization=None)
        assert "signed-in person" in start(agent_os, accepted["id"], anonymous)
    assert asyncio.run(queue.store.get_job(task_run_id(accepted["id"], 1))) is None


def test_start_ends_the_coordinator_turn_with_its_receipt(tmp_path):
    from agno.models.openai import OpenAIResponses
    from agno.os import OSManager
    from agno.tools.function import Function

    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    model = OpenAIResponses(id="gpt-5.6-luna")
    with_company = AgentOS(
        db=db, company=CompanyConfig(model=model), manager=OSManager(model=model, access_docs=False), telemetry=False
    )
    tools = [tool for tool in with_company.manager.tools if isinstance(tool, CompanyTaskTools)]
    assert len(tools) == 1
    functions = tools[0].get_async_functions()
    start_tool: Function = functions["start_company_task"]
    assert start_tool.stop_after_tool_call is True and start_tool.show_result is True
    assert not functions["get_company_task_status"].stop_after_tool_call

    without_company = AgentOS(db=db, manager=OSManager(model=model, access_docs=False), telemetry=False)
    assert not any(isinstance(tool, CompanyTaskTools) for tool in without_company.manager.tools)
