"""Super Agent records a person's Company decisions from chat, and nobody else's."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company.execution import _automatic_task, _ExecutorAuthorization, _task_input
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.company.routines import _RoutineAuthorization
from agno.db.schemas.tasks import task_run_id
from agno.db.sqlite import SqliteDb
from agno.job_queue import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig
from agno.os.auth import INTERNAL_SCHEDULER_USER_ID
from agno.os.authz import Authorization
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.job_queue import QueueWorker
from agno.os.manager.company_tasks import CompanyTaskTools
from agno.registry import Registry
from agno.registry._reserved import BUILDER_ID, MANAGER_TEAM_ID, MINI_AGENT_ID
from agno.run import RunContext
from agno.run.authorization import AUTHORIZATION_KEY, RunAuthorization, authorization_scope

SECRET = "company-decision-tools-tests-secret-at-least-32-bytes"
SCOPES = [
    "products:read",
    "products:write",
    "projects:read",
    "projects:write",
    "tasks:read",
    "tasks:write",
    "wiki:read",
    "agents:writer:run",
    f"agents:{MINI_AGENT_ID}:run",
]


def headers(scopes=None, user="alice"):
    token = jwt.encode(
        {
            "sub": user,
            "aud": "company-decision-tools",
            "scopes": SCOPES if scopes is None else scopes,
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
        id="company-decision-tools",
        db=db,
        registry=Registry(agents=[writer]),
        company=CompanyConfig(model=OpenAIResponses(id="gpt-5.6-luna")),
        telemetry=False,
        user_isolation=request.param,
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()
    queue = QueueWorker(InMemoryQueueStore(), lambda *a, **k: writer, QueueConfig(durable=True), authorization_app=app)
    queue._company_db = db
    app.state.queue_worker = queue
    agent_os._company_app = app
    yield TestClient(app), db, agent_os, queue
    db.close()


def records(client, approve=True):
    """A Product with one Project and one Backlog Task in it."""
    product = client.post("/company/products", json={"name": "SDK"}, headers=headers()).json()
    project = client.post(
        "/company/projects", json={"product_id": product["id"], "name": "Release"}, headers=headers()
    ).json()
    if approve:
        client.post(
            f"/company/projects/{project['id']}/transitions",
            json={"target": "active", "reason": "Approved"},
            headers=headers(),
        )
    task = client.post(
        "/company/tasks",
        json={"product_id": product["id"], "project_id": project["id"], "title": "Draft", "brief": "Write"},
        headers=headers(),
    ).json()
    return project, task


def finish(db, queue, task_id, attempt=1):
    """Settle the Task's queued run as completed, as the queue worker does."""
    run_id = task_run_id(task_id, attempt)

    async def settle():
        job = await queue.store.claim_job(queue.worker_id, queue.config.lock_grace_seconds)
        assert job is not None and job["id"] == run_id
        assert await queue.store.complete_job(run_id, queue.worker_id, job["attempt"], "completed")

    asyncio.run(settle())
    db.complete_task_run(
        task_id,
        run_id,
        {"run_id": run_id, "status": "COMPLETED", "content": "Draft written"},
        expected_transitions=db.get_task(task_id)["transitions"],
    )
    assert db.get_task(task_id)["status"] == "in_review"


def in_review(client, db, queue, task_id, executor_id="writer"):
    """Accept, start and finish a Task so it waits for review."""
    accepted = client.post(
        f"/company/tasks/{task_id}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": executor_id},
        headers=headers(),
    )
    assert accepted.status_code == 200, accepted.text
    assert client.post(f"/company/tasks/{task_id}/runs", headers=headers()).status_code == 202
    finish(db, queue, task_id)


def context(scopes=None, user="alice", **authority_fields):
    authority = RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id=user, scopes=SCOPES if scopes is None else scopes, claims={"sub": user}),
        **authority_fields,
    )
    return RunContext(run_id="chat-run", session_id="chat-session", user_id=user, authorization=authority)


def call(agent_os, tool, run_context, **arguments):
    return asyncio.run(getattr(CompanyTaskTools(agent_os), "a" + tool)(**arguments, _agno_run_context=run_context))


def state(db):
    return (
        [(row["id"], row["status"], row["executor_id"], len(row["transitions"])) for row in db.get_tasks(limit=100)[0]],
        [(row["id"], row["status"], len(row.get("transitions") or [])) for row in db.get_projects(limit=100)[0]],
    )


# ----------------------------------------------------------------- a person decides in chat


def test_a_person_takes_a_proposal_to_done_in_chat(system):
    client, db, agent_os, queue = system
    project, task = records(client, approve=False)

    # A Task in a proposed Project waits for the Project.
    assert call(agent_os, "accept_company_task", context(), task_id=task["id"]).startswith("Not done")
    assert db.get_task(task["id"])["status"] == "backlog"

    reply = call(agent_os, "approve_company_project", context(), project_id=project["id"])
    assert reply.startswith("Approved Project 'Release'"), reply
    approved = db.get_project(project["id"])
    assert approved["status"] == "active"
    assert approved["transitions"][-1]["user_id"] == "alice" and approved["transitions"][-1]["target"] == "active"

    reply = call(
        agent_os, "accept_company_task", context(), task_id=task["id"], executor_type="agent", executor_id="writer"
    )
    assert reply.startswith("Accepted 'Draft'") and "agent writer" in reply, reply
    accepted = db.get_task(task["id"])
    entry = accepted["transitions"][-1]
    assert accepted["status"] == "ready" and accepted["accepted_by"] == "alice" and entry["user_id"] == "alice"
    assert (accepted["executor_type"], accepted["executor_id"]) == ("agent", "writer")
    # The saved authority is the person's own, as the transition route saves it.
    saved = entry[AUTHORIZATION_KEY]
    assert saved["context"]["principal_id"] == "alice" and saved["enforce_tools"] is False
    assert not saved.get("company_executor") and not saved.get("service_account")

    assert "Queued" in call(agent_os, "start_company_task", context(), task_id=task["id"])
    finish(db, queue, task["id"])
    reply = call(
        agent_os, "review_company_task", context(), task_id=task["id"], outcome="complete", reason="Reads well"
    )
    assert reply.startswith("Completed 'Draft'"), reply
    done = db.get_task(task["id"])
    assert done["status"] == "done"
    assert (done["transitions"][-1]["user_id"], done["transitions"][-1]["reason"]) == ("alice", "Reads well")


def test_accept_with_no_executor_names_mini_agent(system):
    client, db, agent_os, queue = system
    _, task = records(client)
    reply = call(agent_os, "accept_company_task", context(), task_id=task["id"])
    assert f"agent {MINI_AGENT_ID}" in reply, reply
    accepted = db.get_task(task["id"])
    assert (accepted["status"], accepted["executor_type"], accepted["executor_id"]) == ("ready", "agent", MINI_AGENT_ID)


def test_accept_on_mini_agent_needs_its_run_grant(system):
    client, db, agent_os, queue = system
    _, task = records(client)
    without = [scope for scope in SCOPES if scope != f"agents:{MINI_AGENT_ID}:run"]
    before = state(db)
    assert call(agent_os, "accept_company_task", context(scopes=without), task_id=task["id"]).startswith("Not done")
    assert state(db) == before


@pytest.mark.parametrize("half", [{"executor_type": "agent"}, {"executor_id": "writer"}])
def test_accept_names_both_executor_fields_or_neither(system, half):
    client, db, agent_os, queue = system
    _, task = records(client)
    reply = call(agent_os, "accept_company_task", context(), task_id=task["id"], **half)
    assert "leave both out to use Mini Agent" in reply and db.get_task(task["id"])["status"] == "backlog"


@pytest.mark.parametrize("executor", [("team", MANAGER_TEAM_ID), ("agent", BUILDER_ID), ("agent", "missing")])
def test_accept_refuses_framework_and_unknown_executors(system, executor):
    client, db, agent_os, queue = system
    _, task = records(client)
    scopes = [*SCOPES, "agents:*:run", "teams:*:run"]
    before = state(db)
    reply = call(
        agent_os,
        "accept_company_task",
        context(scopes=scopes),
        task_id=task["id"],
        executor_type=executor[0],
        executor_id=executor[1],
    )
    assert reply.startswith("Not done"), reply
    assert state(db) == before


def test_send_back_returns_the_task_to_ready_with_the_reason(system):
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before = state(db)
    assert "needs the person's reason" in call(
        agent_os, "review_company_task", context(), task_id=task["id"], outcome="send_back", reason=" "
    )
    assert "complete or send_back" in call(
        agent_os, "review_company_task", context(), task_id=task["id"], outcome="approve", reason="ok"
    )
    assert state(db) == before

    reply = call(
        agent_os, "review_company_task", context(), task_id=task["id"], outcome="send_back", reason="Add the changelog"
    )
    assert reply.startswith("Sent 'Draft'") and "agent writer" in reply, reply
    returned = db.get_task(task["id"])
    entry = returned["transitions"][-1]
    assert (returned["status"], returned["executor_id"], returned["accepted_by"]) == ("ready", "writer", "alice")
    assert (entry["from"], entry["reason"], entry["user_id"]) == ("in_review", "Add the changelog", "alice")
    assert AUTHORIZATION_KEY in entry

    # The executor's next attempt is told why the last one came back.
    manager = CompanyManager(db, agent_os.registry)
    message = json.loads(asyncio.run(_task_input(manager, returned, accepted_execution=True)))
    assert message["review_feedback"] == "Add the changelog"
    assert "Queued" in call(agent_os, "start_company_task", context(), task_id=task["id"])
    assert db.get_task(task["id"])["transitions"][-1]["attempt"] == 2


def test_a_first_attempt_carries_no_review_feedback(system):
    client, db, agent_os, queue = system
    _, task = records(client)
    manager = CompanyManager(db, agent_os.registry)
    message = json.loads(asyncio.run(_task_input(manager, db.get_task(task["id"]), accepted_execution=True)))
    assert "review_feedback" not in message


# ----------------------------------------------------------------- each decision needs the person's grants

DECISIONS = {
    "approve_company_project": (lambda ids: {"project_id": ids["proposed"]}, ["projects:write"]),
    "accept_company_task": (
        lambda ids: {"task_id": ids["backlog"], "executor_type": "agent", "executor_id": "writer"},
        ["tasks:write", "agents:writer:run"],
    ),
    "review_company_task:complete": (
        lambda ids: {"task_id": ids["review"], "outcome": "complete", "reason": "Good"},
        ["tasks:write"],
    ),
    "review_company_task:send_back": (
        lambda ids: {"task_id": ids["review"], "outcome": "send_back", "reason": "Again"},
        ["tasks:write", "agents:writer:run"],
    ),
}


def seeded(client, db, queue):
    """One record waiting for each decision."""
    _, review = records(client)
    in_review(client, db, queue, review["id"])
    _, backlog = records(client)
    proposed, _ = records(client, approve=False)
    return {"review": review["id"], "backlog": backlog["id"], "proposed": proposed["id"]}


@pytest.mark.parametrize(
    "decision,missing", [(name, scope) for name, (_, scopes) in DECISIONS.items() for scope in scopes]
)
def test_each_decision_needs_the_persons_grant(system, decision, missing):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    arguments = DECISIONS[decision][0](ids)
    before = state(db)
    without = [scope for scope in SCOPES if scope != missing]
    reply = call(agent_os, decision.split(":")[0], context(scopes=without), **arguments)
    assert reply.startswith("Not done"), reply
    assert state(db) == before
    # The same call with the grant decides.
    assert not call(agent_os, decision.split(":")[0], context(), **arguments).startswith("Not done")
    assert state(db) != before


def automated_callers():
    routine = context()
    routine.authorization = _RoutineAuthorization(routine.authorization, routine_id="routine", product_id=None)
    task_run = context()
    task_run.authorization = _ExecutorAuthorization(task_run.authorization, task_id="task")
    return {
        "routine-run": routine,
        "task-run": task_run,
        "service-account": context(service_account=True),
        "scheduler": context(user=INTERNAL_SCHEDULER_USER_ID),
        "automation-tick": context(),
    }


@pytest.mark.parametrize("decision", sorted(DECISIONS))
@pytest.mark.parametrize("caller", ["routine-run", "task-run", "service-account", "scheduler", "automation-tick"])
def test_only_a_person_decides(system, decision, caller):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    before = state(db)
    token = _automatic_task.set({"id": "task"}) if caller == "automation-tick" else None
    try:
        reply = call(agent_os, decision.split(":")[0], automated_callers()[caller], **DECISIONS[decision][0](ids))
    finally:
        if token is not None:
            _automatic_task.reset(token)
    assert reply.startswith("Not done") and "human" in reply, reply
    assert state(db) == before


@pytest.mark.parametrize("decision", sorted(DECISIONS))
def test_an_anonymous_caller_decides_only_without_user_isolation(system, decision):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    before = state(db)
    anonymous = RunContext(run_id="r", session_id="s", user_id=None, authorization=None)
    reply = call(agent_os, decision.split(":")[0], anonymous, **DECISIONS[decision][0](ids))
    if agent_os.user_isolation:
        assert reply.startswith("Not done") and "signed-in person" in reply, reply
        assert state(db) == before
    else:
        # With no caller authority the deployment trusts its callers, as the Company API does.
        assert not reply.startswith("Not done") and state(db) != before, reply


def test_decisions_refuse_a_record_in_the_wrong_stage(system):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    active, ready = records(client)
    client.post(
        f"/company/tasks/{ready['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    )
    before = state(db)
    assert "only a proposed Project" in call(agent_os, "approve_company_project", context(), project_id=active["id"])
    assert "only a proposal" in call(agent_os, "accept_company_task", context(), task_id=ready["id"])
    for task_id in (ids["backlog"], ready["id"]):
        reply = call(agent_os, "review_company_task", context(), task_id=task_id, outcome="complete", reason="ok")
        assert "only a Task in review" in reply
    assert "not found" in call(agent_os, "approve_company_project", context(), project_id="missing").lower()
    assert "not found" in call(agent_os, "accept_company_task", context(), task_id="missing").lower()
    assert state(db) == before


def test_the_sync_tools_decide_nothing(system):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    before = state(db)
    tools = CompanyTaskTools(agent_os)
    for name, (arguments, _) in DECISIONS.items():
        reply = getattr(tools, name.split(":")[0])(**arguments(ids), _agno_run_context=context())
        assert "asynchronous run" in reply
    assert state(db) == before


# ----------------------------------------------------------------- a run that executes work decides nothing


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("kind", ["task-run", "routine-run"])
def test_task_and_routine_runs_cannot_move_work_through_the_manager(system, kind, use_async):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    authority = (
        _ExecutorAuthorization(context().authorization, task_id=ids["review"])
        if kind == "task-run"
        else _RoutineAuthorization(context().authorization, routine_id="routine", product_id=None)
    )
    manager = AsyncCompanyManager(db, agent_os.registry) if use_async else CompanyManager(db, agent_os.registry)

    def move(method, **arguments):
        result = getattr(manager, method)(reason="Injected", **arguments)
        return asyncio.run(result) if use_async else result

    before = state(db)
    executor = {"executor_type": "agent", "executor_id": "writer"}
    with authorization_scope(lambda: authority):
        for task_id, target, extra in (
            (ids["backlog"], "ready", executor),
            (ids["review"], "done", {}),
            (ids["review"], "ready", executor),
            (ids["review"], "backlog", {}),
            (ids["backlog"], "cancelled", {}),
        ):
            with pytest.raises(PermissionError, match="Routine and Task runs cannot"):
                move("transition_task", task_id=task_id, target=target, **extra)
        for target in ("active", "cancelled"):
            with pytest.raises(PermissionError, match="Routine and Task runs cannot"):
                move("transition_project", project_id=ids["proposed"], target=target)
    assert state(db) == before
