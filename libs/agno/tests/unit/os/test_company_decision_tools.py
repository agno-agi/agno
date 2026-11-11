"""Super Agent records a person's Company decisions from chat, after that person confirms each one."""

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


def approve(agent_os, run_context, project):
    return call(
        agent_os, "approve_company_project", run_context, project_name=project["name"], project_id=project["id"]
    )


def accept(agent_os, run_context, *tasks, executor=("agent", "writer")):
    named = [{"title": task["title"], "task_id": task["id"]} for task in tasks]
    return call(
        agent_os, "accept_company_task", run_context, tasks=named, executor_type=executor[0], executor_id=executor[1]
    )


def review(agent_os, run_context, task, outcome, reason):
    return call(
        agent_os,
        "review_company_task",
        run_context,
        task_title=task["title"],
        outcome=outcome,
        reason=reason,
        task_id=task["id"],
        reviewed_run_id=(agent_os._company_db.get_task(task["id"]) or {}).get("job_id") or "missing-run",
    )


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
    assert accept(agent_os, context(), task).startswith("Not done")
    assert db.get_task(task["id"])["status"] == "backlog"

    reply = approve(agent_os, context(), project)
    assert reply.startswith("Approved Project 'Release'"), reply
    approved = db.get_project(project["id"])
    assert approved["status"] == "active"
    assert approved["transitions"][-1]["user_id"] == "alice" and approved["transitions"][-1]["target"] == "active"

    reply = accept(agent_os, context(), task)
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
    reply = review(agent_os, context(), task, "complete", "Reads well")
    assert reply.startswith("Completed 'Draft'"), reply
    done = db.get_task(task["id"])
    assert done["status"] == "done"
    assert (done["transitions"][-1]["user_id"], done["transitions"][-1]["reason"]) == ("alice", "Reads well")


def test_accept_with_no_executor_names_mini_agent(system):
    client, db, agent_os, queue = system
    _, task = records(client)
    reply = accept(agent_os, context(), task, executor=(None, None))
    assert f"agent {MINI_AGENT_ID}" in reply, reply
    accepted = db.get_task(task["id"])
    assert (accepted["status"], accepted["executor_type"], accepted["executor_id"]) == ("ready", "agent", MINI_AGENT_ID)


def test_accept_on_mini_agent_needs_its_run_grant(system):
    client, db, agent_os, queue = system
    _, task = records(client)
    without = [scope for scope in SCOPES if scope != f"agents:{MINI_AGENT_ID}:run"]
    before = state(db)
    for executor in ((None, None), ("agent", MINI_AGENT_ID)):
        assert accept(agent_os, context(scopes=without), task, executor=executor).startswith("Not done")
    assert state(db) == before


@pytest.mark.parametrize("half", [("agent", None), (None, "writer")])
def test_accept_names_both_executor_fields_or_neither(system, half):
    client, db, agent_os, queue = system
    _, task = records(client)
    reply = accept(agent_os, context(), task, executor=half)
    assert "leave both out to use Mini Agent" in reply and db.get_task(task["id"])["status"] == "backlog"


@pytest.mark.parametrize("executor", [("team", MANAGER_TEAM_ID), ("agent", BUILDER_ID), ("agent", "missing")])
def test_accept_refuses_framework_and_unknown_executors(system, executor):
    client, db, agent_os, queue = system
    _, task = records(client)
    scopes = [*SCOPES, "agents:*:run", "teams:*:run"]
    before = state(db)
    reply = accept(agent_os, context(scopes=scopes), task, executor=executor)
    assert reply.startswith("Not done"), reply
    assert state(db) == before


def test_send_back_returns_the_task_to_ready_with_the_reason(system):
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before = state(db)
    assert "needs the person's reason" in review(agent_os, context(), task, "send_back", " ")
    assert "complete or send_back" in review(agent_os, context(), task, "approve", "ok")
    assert state(db) == before

    reply = review(agent_os, context(), task, "send_back", "Add the changelog")
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
    "approve_company_project": (lambda ids, ctx, os: approve(os, ctx, ids["proposed"]), ["projects:write"]),
    "accept_company_task": (
        lambda ids, ctx, os: accept(os, ctx, ids["backlog"]),
        ["tasks:write", "agents:writer:run"],
    ),
    "review_company_task:complete": (
        lambda ids, ctx, os: review(os, ctx, ids["review"], "complete", "Good"),
        ["tasks:write"],
    ),
    "review_company_task:send_back": (
        lambda ids, ctx, os: review(os, ctx, ids["review"], "send_back", "Again"),
        ["tasks:write", "agents:writer:run"],
    ),
}


def seeded(client, db, queue):
    """One record waiting for each decision."""
    _, review_task = records(client)
    in_review(client, db, queue, review_task["id"])
    _, backlog = records(client)
    proposed, _ = records(client, approve=False)
    return {"review": review_task, "backlog": backlog, "proposed": proposed}


@pytest.mark.parametrize(
    "decision,missing", [(name, scope) for name, (_, scopes) in DECISIONS.items() for scope in scopes]
)
def test_each_decision_needs_the_persons_grant(system, decision, missing):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    decide = DECISIONS[decision][0]
    before = state(db)
    without = [scope for scope in SCOPES if scope != missing]
    reply = decide(ids, context(scopes=without), agent_os)
    assert reply.startswith("Not done"), reply
    assert state(db) == before
    # The same call with the grant decides.
    assert not decide(ids, context(), agent_os).startswith("Not done")
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
        reply = DECISIONS[decision][0](ids, automated_callers()[caller], agent_os)
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
    reply = DECISIONS[decision][0](ids, anonymous, agent_os)
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
    assert "only a proposed Project" in approve(agent_os, context(), active)
    assert "only a proposal" in accept(agent_os, context(), ready)
    for task in (ids["backlog"], ready):
        assert "only a Task in review" in review(agent_os, context(), task, "complete", "ok")
    missing = {"id": "missing", "name": "Release", "title": "Draft"}
    assert "not found" in approve(agent_os, context(), missing).lower()
    assert "not found" in accept(agent_os, context(), missing).lower()
    assert "not found" in review(agent_os, context(), missing, "complete", "ok").lower()
    assert "name at least one Task" in accept(agent_os, context())
    assert state(db) == before


def test_a_decision_applies_only_to_the_record_the_person_confirmed_by_name(system):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    before = state(db)
    wrong_project = {**ids["proposed"], "name": "Another Project"}
    assert "is named 'Release'" in approve(agent_os, context(), wrong_project)
    wrong_task = {**ids["backlog"], "title": "Another Task"}
    assert "is titled 'Draft'" in accept(agent_os, context(), wrong_task)
    assert "is titled 'Draft'" in review(agent_os, context(), {**ids["review"], "title": "Other"}, "complete", "ok")
    assert state(db) == before
    # Case and spacing do not matter.
    assert approve(agent_os, context(), {**ids["proposed"], "name": "  release "}).startswith("Approved")


def test_one_call_accepts_several_tasks_or_none(system):
    client, db, agent_os, queue = system
    project, first = records(client)
    second = client.post(
        "/company/tasks",
        json={"product_id": first["product_id"], "project_id": project["id"], "title": "Second", "brief": "Write"},
        headers=headers(),
    ).json()
    before = state(db)
    # One Task that is not the confirmed one stops the whole call.
    assert "is titled 'Second'" in accept(agent_os, context(), first, {**second, "title": "Third"})
    assert state(db) == before
    reply = accept(agent_os, context(), first, second)
    assert reply.count("Accepted '") == 2 and "Not done" not in reply, reply
    for task in (first, second):
        saved = db.get_task(task["id"])
        assert (saved["status"], saved["executor_id"], saved["accepted_by"]) == ("ready", "writer", "alice")


def test_the_sync_tools_decide_nothing(system):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    before = state(db)
    tools = CompanyTaskTools(agent_os)
    replies = [
        tools.approve_company_project("Release", ids["proposed"]["id"], _agno_run_context=context()),
        tools.accept_company_task(
            [{"title": "Draft", "task_id": ids["backlog"]["id"]}], "agent", "writer", _agno_run_context=context()
        ),
        tools.review_company_task("Draft", "complete", "Good", ids["review"]["id"], "run", _agno_run_context=context()),
    ]
    assert all("asynchronous run" in reply for reply in replies)
    assert state(db) == before


# ----------------------------------------------------------------- a run that executes work decides nothing


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("kind", ["task-run", "routine-run"])
def test_task_and_routine_runs_cannot_move_work_through_the_manager(system, kind, use_async):
    client, db, agent_os, queue = system
    ids = seeded(client, db, queue)
    authority = (
        _ExecutorAuthorization(context().authorization, task_id=ids["review"]["id"])
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
            (ids["backlog"]["id"], "ready", executor),
            (ids["review"]["id"], "done", {}),
            (ids["review"]["id"], "ready", executor),
            (ids["review"]["id"], "backlog", {}),
            (ids["backlog"]["id"], "cancelled", {}),
        ):
            with pytest.raises(PermissionError, match="Routine and Task runs cannot"):
                move("transition_task", task_id=task_id, target=target, **extra)
        for target in ("active", "cancelled"):
            with pytest.raises(PermissionError, match="Routine and Task runs cannot"):
                move("transition_project", project_id=ids["proposed"]["id"], target=target)
    assert state(db) == before


# ----------------------------------------------------------------- nothing is decided without a confirmation


def test_the_decision_tools_pause_and_the_run_tools_do_not(system):
    client, db, agent_os, queue = system
    functions = CompanyTaskTools(agent_os).get_async_functions()
    for name in ("approve_company_project", "accept_company_task", "review_company_task"):
        assert functions[name].requires_confirmation is True, name
    for name in ("start_company_task", "get_company_task_status"):
        assert not functions[name].requires_confirmation, name


@pytest.fixture
def chat(tmp_path):
    from tests.unit.os.test_mini_agent_tasks import System

    value = System(tmp_path)
    yield value
    value.db.close()


def chat_records(chat):
    """One record waiting for each decision, on an AgentOS that serves Super Agent."""
    from tests.unit.os.test_mini_agent_tasks import headers as chat_headers

    review_task = chat.proposal()
    chat.accept(review_task["id"])
    chat.execute(review_task["id"])
    review_task = chat.db.get_task(review_task["id"])
    assert review_task["status"] == "in_review"
    backlog = chat.proposal()
    proposed = chat.client.post(
        "/company/projects", json={"product_id": backlog["product_id"], "name": "Proposed"}, headers=chat_headers()
    ).json()
    return {"review": review_task, "backlog": backlog, "proposed": proposed}


def tool_calls(ids):
    """Each decision as the model calls it, with what the confirmation must show."""
    backlog, review_task, proposed = ids["backlog"], ids["review"], ids["proposed"]
    return {
        "approve": ("approve_company_project", {"project_name": proposed["name"], "project_id": proposed["id"]}),
        "accept": (
            "accept_company_task",
            {
                "tasks": [{"title": backlog["title"], "task_id": backlog["id"]}],
                "executor_type": "agent",
                "executor_id": "writer",
            },
        ),
        "complete": (
            "review_company_task",
            {
                "task_title": review_task["title"],
                "outcome": "complete",
                "reason": "Good",
                "task_id": review_task["id"],
                "reviewed_run_id": review_task["job_id"],
            },
        ),
        "send_back": (
            "review_company_task",
            {
                "task_title": review_task["title"],
                "outcome": "send_back",
                "reason": "Redo",
                "task_id": review_task["id"],
                "reviewed_run_id": review_task["job_id"],
            },
        ),
    }


def person(scopes=None):
    from tests.unit.os.test_mini_agent_tasks import SCOPES as CHAT_SCOPES

    return RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(
            principal_id="alice", scopes=CHAT_SCOPES if scopes is None else scopes, claims={"sub": "alice"}
        ),
        enforce_tools=False,
    )


def ask(chat, tool, arguments, session="chat"):
    from tests.unit.os.test_mini_agent_tasks import ScriptedModel

    chat.os.manager.model = ScriptedModel([(tool, arguments)])
    with authorization_scope(person):
        return asyncio.run(chat.os.manager.arun("Decide", user_id="alice", session_id=session))


@pytest.mark.parametrize("decision", ["approve", "accept", "complete", "send_back"])
@pytest.mark.parametrize("answer", ["unanswered", "rejected", "confirmed"])
def test_no_decision_is_recorded_without_a_confirmation(chat, decision, answer):
    from tests.unit.os.test_mini_agent_tasks import ScriptedModel

    ids = chat_records(chat)
    tool, arguments = tool_calls(ids)[decision]
    before = state(chat.db)
    paused = ask(chat, tool, arguments)
    assert paused.is_paused and state(chat.db) == before
    # The confirmation shows the record's name, its ID and what will change.
    assert len(paused.requirements) == 1
    shown = paused.requirements[0].tool_execution
    assert shown.tool_name == tool and shown.tool_args == arguments

    if answer == "unanswered":
        # The person says something else instead. The paused decision stays undecided.
        chat.os.manager.model = ScriptedModel()
        with authorization_scope(person):
            asyncio.run(chat.os.manager.arun("What is the status?", user_id="alice", session_id="chat"))
        assert state(chat.db) == before
        return
    if answer == "rejected":
        paused.requirements[0].reject("Not now")
    else:
        paused.requirements[0].confirm()
    with authorization_scope(person):
        result = asyncio.run(chat.os.manager.acontinue_run(run_response=paused, user_id="alice"))
    if answer == "rejected":
        assert state(chat.db) == before, result.content
        return
    assert state(chat.db) != before, result.content
    record = (
        chat.db.get_project(ids["proposed"]["id"])
        if decision == "approve"
        else chat.db.get_task(ids["backlog" if decision == "accept" else "review"]["id"])
    )
    assert record["transitions"][-1]["user_id"] == "alice"
    assert (
        record["status"] == {"approve": "active", "accept": "ready", "complete": "done", "send_back": "ready"}[decision]
    )


def test_one_confirmation_covers_several_tasks(chat):
    from tests.unit.os.test_mini_agent_tasks import headers as chat_headers

    first = chat.proposal()
    second = chat.client.post(
        "/company/tasks",
        json={"product_id": first["product_id"], "project_id": first["project_id"], "title": "Second"},
        headers=chat_headers(),
    ).json()
    named = [{"title": task["title"], "task_id": task["id"]} for task in (first, second)]
    paused = ask(chat, "accept_company_task", {"tasks": named, "executor_type": "agent", "executor_id": "writer"})
    assert paused.is_paused and len(paused.requirements) == 1
    assert paused.requirements[0].tool_execution.tool_args["tasks"] == named
    assert {chat.db.get_task(task["id"])["status"] for task in (first, second)} == {"backlog"}
    paused.requirements[0].confirm()
    with authorization_scope(person):
        asyncio.run(chat.os.manager.acontinue_run(run_response=paused, user_id="alice"))
    for task in (first, second):
        saved = chat.db.get_task(task["id"])
        assert (saved["status"], saved["executor_id"], saved["accepted_by"]) == ("ready", "writer", "alice")


@pytest.mark.parametrize("outcome", ["complete", "send_back"])
def test_review_confirmation_cannot_decide_a_newer_attempt(chat, outcome):
    from tests.unit.os.test_mini_agent_tasks import headers as chat_headers

    ids = chat_records(chat)
    task = ids["review"]
    tool, arguments = tool_calls(ids)["complete" if outcome == "complete" else "send_back"]
    paused = ask(chat, tool, arguments)
    assert paused.is_paused
    returned = chat.client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={"target": "ready", "reason": "Revise", "executor_type": "agent", "executor_id": MINI_AGENT_ID},
        headers=chat_headers(user="bob"),
    )
    assert returned.status_code == 200, returned.text
    revised = chat.execute(task["id"], [("list_agents", {})])
    assert revised["status"] == "in_review" and revised["job_id"] != task["job_id"]
    before = state(chat.db)
    paused.requirements[0].confirm()
    with authorization_scope(person):
        result = asyncio.run(chat.os.manager.acontinue_run(run_response=paused, user_id="alice"))
    assert state(chat.db) == before
    assert "attempt changed" in result.content

    fresh = ask(chat, tool, {**arguments, "reviewed_run_id": revised["job_id"]}, session="fresh-review")
    assert fresh.is_paused
    fresh.requirements[0].confirm()
    with authorization_scope(person):
        asyncio.run(chat.os.manager.acontinue_run(run_response=fresh, user_id="alice"))
    assert chat.db.get_task(task["id"])["status"] == ("done" if outcome == "complete" else "ready")


@pytest.mark.parametrize("decision", ["approve", "accept", "complete", "send_back"])
def test_a_scheduled_run_on_super_agent_pauses_and_decides_nothing(chat, decision):
    from agno.registry._reserved import MANAGER_TEAM_ID
    from agno.run.authorization import AUTHORIZATION_HEADER
    from agno.scheduler.executor import terminal_run_status
    from tests.unit.os.test_mini_agent_tasks import SCOPES as CHAT_SCOPES
    from tests.unit.os.test_mini_agent_tasks import ScriptedModel

    ids = chat_records(chat)
    tool, arguments = tool_calls(ids)[decision]
    before = state(chat.db)
    chat.os.manager.model = ScriptedModel([(tool, arguments)])
    # A schedule fires its target with the scheduler's token and the saved authority of its creator.
    scopes = [*CHAT_SCOPES, f"teams:{MANAGER_TEAM_ID}:run"]
    snapshot = {"context": {"principal_id": "alice", "scopes": scopes}, "service_account": False}
    response = chat.client.post(
        f"/teams/{MANAGER_TEAM_ID}/runs",
        data={"message": "Decide everything that is waiting", "stream": "false", "user_id": "alice"},
        headers={
            "Authorization": "Bearer " + chat.os._internal_service_token,
            AUTHORIZATION_HEADER: json.dumps(snapshot),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "PAUSED" and body["requirements"][0]["tool_execution"]["tool_name"] == tool
    # The scheduler records the run as paused and does not retry or resume it.
    assert terminal_run_status(body, company_routine=False) == ("paused", None)
    assert state(chat.db) == before
