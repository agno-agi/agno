"""An accepted Task changes Project, and a run the scheduler fired acts for no person."""

import asyncio
import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import Agent
from agno.company.execution import _automatic_task, _ExecutorAuthorization
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.company.routines import _RoutineAuthorization
from agno.db.schemas.projects import DEFAULT_PROJECT_ID
from agno.db.schemas.scheduler import SCHEDULED_RUN_METADATA_KEY, Schedule
from agno.db.schemas.tasks import TASK_MOVE_REFUSAL, task_run_id
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os.manager import company_tasks
from agno.os.manager.company_tasks import CompanyTaskTools
from agno.registry import Registry
from agno.run import RunContext
from agno.run.authorization import authorization_scope
from agno.scheduler.executor import ScheduleExecutor
from tests.unit.os.test_company_decision_tools import (
    SCOPES,
    automated_callers,
    build,
    call,
    context,
    headers,
    in_review,
    records,
    state,
    system,  # noqa: F401
)
from tests.unit.os.test_company_policy_path import SCOPES as POLICY_SCOPES
from tests.unit.os.test_company_policy_path import PolicySystem, company_tools, receipts
from tests.unit.os.test_mini_agent_tasks import ScriptedModel, System
from tests.unit.os.test_mini_agent_tasks import headers as policy_headers

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

STATUSES = ["backlog", "ready", "in_progress", "in_review", "done", "cancelled"]
MOVABLE = {"backlog", "ready", "in_review", "done"}


@pytest.fixture(autouse=True)
def fresh_run_counts():
    company_tasks._accepted_in_run.clear()
    yield
    company_tasks._accepted_in_run.clear()


async def do(value):
    return await value if inspect.isawaitable(value) else value


async def company(tmp_path, use_async):
    """A manager on a sync or an async database, with two active Projects under one Goal."""
    db = (AsyncSqliteDb if use_async else SqliteDb)(db_file=str(tmp_path / "move.db"))
    registry = Registry(agents=[Agent(id="writer")])
    manager = (AsyncCompanyManager if use_async else CompanyManager)(db, registry=registry)
    goal = await do(manager.create(name="SDK"))
    projects = []
    for name in ("Release", "Launch"):
        project = await do(manager.create_project(goal_id=goal["id"], name=name))
        await do(manager.transition_project(project_id=project["id"], target="active", reason="Approved"))
        projects.append(project)
    return db, manager, goal, projects


async def task_at(db, manager, goal, project, status):
    """A Task taken to a stage the way the product takes it there."""
    task = await do(manager.create_task(goal_id=goal["id"], project_id=project["id"], title="Draft", brief="Write"))
    if status == "backlog":
        return task
    accept = dict(executor_type="agent", executor_id="writer", accepted_by="alice")
    task = await do(manager.transition_task(task_id=task["id"], target="ready", reason="Accepted", **accept))
    if status == "ready":
        return task
    if status == "cancelled":
        return await do(manager.transition_task(task_id=task["id"], target="cancelled", reason="Dropped"))
    task = await do(db.start_task_run(task["id"], 1, task["transitions"], user_id="alice", run_db_id="runs"))
    if status == "in_progress":
        return task
    run_id = task_run_id(task["id"], 1)
    result = {"run_id": run_id, "status": "COMPLETED", "content": "Done"}
    task = await do(db.complete_task_run(task["id"], run_id, result, expected_transitions=task["transitions"]))
    if status == "in_review":
        return task
    return await do(manager.transition_task(task_id=task["id"], target="done", reason="Good", accepted_by="alice"))


# ----------------------------------------------------------------- which stages move


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("status", STATUSES)
async def test_a_task_changes_project_in_the_stages_where_nothing_holds_it(tmp_path, use_async, status):
    db, manager, goal, (release, launch) = await company(tmp_path, use_async)
    task = await task_at(db, manager, goal, release, status)
    assert task["status"] == status
    if status not in MOVABLE:
        with pytest.raises(ValueError) as refused:
            await do(manager.update_task(task["id"], moved_by="alice", project_id=launch["id"]))
        assert str(refused.value) == TASK_MOVE_REFUSAL[status]
        assert await do(db.get_task(task["id"])) == task
        return
    moved = await do(manager.update_task(task["id"], moved_by="alice", project_id=launch["id"]))
    assert moved["project_id"] == launch["id"]
    # Who moved it, from where to where, is on the Task's history. Nothing else changed.
    entry = moved["transitions"][-1]
    assert (entry["action"], entry["user_id"]) == ("move", "alice")
    assert entry["project"] == {"from": release["id"], "to": launch["id"]}
    assert "target" not in entry and "from" not in entry and entry["created_at"]
    assert moved["transitions"][:-1] == task["transitions"]
    kept = ("status", "brief", "title", "executor_type", "executor_id", "accepted_by", "goal_id", "job_id", "result")
    assert {key: moved[key] for key in kept} == {key: task[key] for key in kept}
    # Moving it to the Project it is in records nothing.
    again = await do(manager.update_task(task["id"], moved_by="alice", project_id=launch["id"]))
    assert again["transitions"] == moved["transitions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_the_rest_of_an_accepted_task_stays_frozen(tmp_path, use_async):
    db, manager, goal, (release, launch) = await company(tmp_path, use_async)
    task = await task_at(db, manager, goal, release, "ready")
    for change in (
        {"brief": "Other"},
        {"executor_id": "other"},
        {"evidence": []},
        {"brief": "Other", "project_id": launch["id"]},
    ):
        with pytest.raises(ValueError, match="Accepted task scope requires a return to Backlog"):
            await do(manager.update_task(task["id"], moved_by="alice", **change))
    assert await do(db.get_task(task["id"])) == task
    # The storage layer holds the same line when it is called directly.
    assert await do(db.update_task(task["id"], executor_id="other", project_id=launch["id"])) is None
    assert await do(db.get_task(task["id"])) == task


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_an_accepted_task_moves_only_into_an_active_project(tmp_path, use_async):
    db, manager, goal, (release, launch) = await company(tmp_path, use_async)
    proposed = await do(manager.create_project(goal_id=goal["id"], name="Later"))
    finished = await do(manager.create_project(goal_id=goal["id"], name="Finished"))
    await do(manager.transition_project(project_id=finished["id"], target="active", reason="Approved"))
    await do(manager.transition_project(project_id=finished["id"], target="done", reason="Shipped"))
    ready = await task_at(db, manager, goal, release, "ready")
    done = await task_at(db, manager, goal, release, "done")
    for task in (ready, done):
        for target in (proposed, finished):
            with pytest.raises(ValueError):
                await do(manager.update_task(task["id"], moved_by="alice", project_id=target["id"]))
        assert (await do(db.get_task(task["id"])))["project_id"] == release["id"]
    with pytest.raises(ValueError) as refused:
        await do(manager.update_task(ready["id"], moved_by="alice", project_id=proposed["id"]))
    assert str(refused.value) == TASK_MOVE_REFUSAL["inactive"]
    # A Backlog draft may still sit in a proposed Project, and the Default Project is always active.
    draft = await task_at(db, manager, goal, release, "backlog")
    assert (await do(manager.update_task(draft["id"], project_id=proposed["id"])))["project_id"] == proposed["id"]
    moved = await do(manager.update_task(ready["id"], moved_by="alice", project_id=None))
    assert moved["project_id"] == DEFAULT_PROJECT_ID and moved["goal_id"] == goal["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_an_accepted_task_follows_the_goal_rule_of_a_move(tmp_path, use_async):
    db, manager, goal, (release, launch) = await company(tmp_path, use_async)
    other = await do(manager.create(name="Docs"))
    elsewhere = await do(manager.create_project(goal_id=other["id"], name="Guide"))
    await do(manager.transition_project(project_id=elsewhere["id"], target="active", reason="Approved"))
    ready = await task_at(db, manager, goal, release, "ready")
    with pytest.raises(ValueError, match="same Goal"):
        await do(manager.update_task(ready["id"], moved_by="alice", project_id=elsewhere["id"]))
    # A Task with no Goal takes the Goal of the Project it moves into, accepted or not.
    loose = await do(manager.create_task(title="Loose", brief="Write"))
    accept = dict(executor_type="agent", executor_id="writer", accepted_by="alice")
    loose = await do(manager.transition_task(task_id=loose["id"], target="ready", reason="Accepted", **accept))
    assert (loose["project_id"], loose["goal_id"]) == (DEFAULT_PROJECT_ID, None)
    moved = await do(manager.update_task(loose["id"], moved_by="alice", project_id=launch["id"]))
    assert (moved["project_id"], moved["goal_id"], moved["status"]) == (launch["id"], goal["id"], "ready")


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("kind", ["routine", "task"])
async def test_a_routine_or_task_run_cannot_move_an_accepted_task(tmp_path, use_async, kind):
    db, manager, goal, (release, launch) = await company(tmp_path, use_async)
    ready = await task_at(db, manager, goal, release, "ready")
    authority = (
        _RoutineAuthorization(None, routine_id="routine", goal_id=goal["id"])
        if kind == "routine"
        else _ExecutorAuthorization(None, task_id=ready["id"])
    )
    with authorization_scope(lambda: authority):
        with pytest.raises(PermissionError) as refused:
            await do(manager.update_task(ready["id"], moved_by="alice", project_id=launch["id"]))
    assert str(refused.value) == TASK_MOVE_REFUSAL["automated"]
    assert await do(db.get_task(ready["id"])) == ready


def test_a_task_a_policy_holds_ready_is_not_moved_out_of_what_the_policy_accepted(tmp_path):
    policy = PolicySystem(tmp_path)
    try:
        goal_id = policy.client.post("/company/goals", json={"name": "Docs"}, headers=policy_headers(POLICY_SCOPES))
        goal_id = goal_id.json()["id"]
        routine_id = policy.api_routine(goal_id).json()["id"]
        _, task = policy.proposes(goal_id, routine_id)
        policy.tick()
        accepted = policy.db.get_task(task["id"])
        # The tick accepted and queued it. Before its run is reserved it is Ready under the policy.
        assert receipts(accepted)
        if accepted["status"] == "ready":
            moved = policy.client.patch(
                f"/company/tasks/{task['id']}", json={"project_id": None}, headers=policy_headers(POLICY_SCOPES)
            )
            assert moved.status_code == 409 and moved.json()["detail"] == TASK_MOVE_REFUSAL["policy"], moved.text
        ready = {**accepted, "status": "ready"}
        other = policy.manager.create_project(goal_id=goal_id, name="Other")
        policy.manager.transition_project(project_id=other["id"], target="active", reason="Approved")
        from agno.db.sql.company import require_move

        with pytest.raises(ValueError) as refused:
            with policy.db.Session() as sess:
                projects = policy.db._get_table(table_type="projects")
                goals = policy.db._get_table(table_type="goals")
                require_move(sess, goals, projects, ready, other["id"], "alice")
        assert str(refused.value) == TASK_MOVE_REFUSAL["policy"]
    finally:
        policy.db.close()


# ----------------------------------------------------------------- the route and the chat tool


def second_project(client, goal_id, name="Launch", approve=True):
    project = client.post("/company/projects", json={"goal_id": goal_id, "name": name}, headers=headers()).json()
    if approve:
        approved = client.post(
            f"/company/projects/{project['id']}/transitions",
            json={"target": "active", "reason": "Approved"},
            headers=headers(),
        )
        assert approved.status_code == 200, approved.text
    return project


def accepted(client, task):
    done = client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    )
    assert done.status_code == 200, done.text
    return done.json()


def test_the_route_moves_an_accepted_task_and_records_the_caller(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, task = records(client)
    launch = second_project(client, project["goal_id"])
    accepted(client, task)
    moved = client.patch(f"/company/tasks/{task['id']}", json={"project_id": launch["id"]}, headers=headers())
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert (body["project_id"], body["status"], body["executor_id"]) == (launch["id"], "ready", "writer")
    assert body["transitions"][-1]["action"] == "move" and body["transitions"][-1]["user_id"] == "alice"
    # The rest of the frozen scope still answers as it did.
    frozen = client.patch(f"/company/tasks/{task['id']}", json={"brief": "Other"}, headers=headers())
    assert frozen.status_code == 409 and frozen.json()["detail"] == "Accepted task scope requires a return to Backlog"
    # A Task with a run in flight stays where it is.
    assert client.post(f"/company/tasks/{task['id']}/runs", headers=headers()).status_code == 202
    held = client.patch(f"/company/tasks/{task['id']}", json={"project_id": project["id"]}, headers=headers())
    assert held.status_code == 409 and held.json()["detail"] == TASK_MOVE_REFUSAL["in_progress"], held.text
    assert db.get_task(task["id"])["project_id"] == launch["id"]
    # The moved Task still starts and finishes: its acceptance was not touched.
    assert db.get_task(task["id"])["status"] == "in_progress"


def test_a_moved_task_still_runs_and_reviews(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, task = records(client)
    launch = second_project(client, project["goal_id"])
    accepted(client, task)
    assert (
        client.patch(f"/company/tasks/{task['id']}", json={"project_id": launch["id"]}, headers=headers()).status_code
        == 200
    )
    assert client.post(f"/company/tasks/{task['id']}/runs", headers=headers()).status_code == 202
    from tests.unit.os.test_company_decision_tools import finish, review

    finish(db, queue, task["id"])
    # In review it moves again, and the review that follows is still the person's.
    back = client.patch(f"/company/tasks/{task['id']}", json={"project_id": project["id"]}, headers=headers())
    assert back.status_code == 200, back.text
    reply = review(agent_os, context(), db.get_task(task["id"]), "complete", "Good")
    assert reply.startswith("Completed"), reply
    done = db.get_task(task["id"])
    assert (done["status"], done["project_id"]) == ("done", project["id"])
    assert [entry.get("action") for entry in done["transitions"]].count("move") == 2


def move(agent_os, run_context, task_id, project_id):
    return call(agent_os, "move_company_task", run_context, task_id=task_id, project_id=project_id)


def test_super_agent_moves_a_task_for_the_person_without_a_pause(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, _ = records(client)
    functions = CompanyTaskTools(agent_os).get_async_functions()
    assert not functions["move_company_task"].requires_confirmation
    added = call(agent_os, "add_company_task", context(), title="Typo", brief="Fix it.", start=False)
    assert added.startswith("Added"), added
    task = next(row for row in db.get_tasks(limit=100)[0] if row["title"] == "Typo")
    assert task["project_id"] == DEFAULT_PROJECT_ID and task["status"] == "ready"
    reply = move(agent_os, context(), task["id"], project["id"])
    assert reply == f"Moved 'Typo' (Task {task['id']}) into Project 'Release'. Nothing else about it changed."
    moved = db.get_task(task["id"])
    assert (moved["project_id"], moved["goal_id"], moved["status"]) == (project["id"], project["goal_id"], "ready")
    assert (moved["accepted_by"], moved["executor_id"]) == ("alice", task["executor_id"])
    assert moved["transitions"][-1]["action"] == "move" and moved["transitions"][-1]["user_id"] == "alice"
    assert "already in that Project" in move(agent_os, context(), task["id"], project["id"])
    # Null moves it back to the Default Project. It keeps the Goal it took.
    assert move(agent_os, context(), task["id"], None).startswith("Moved")
    assert db.get_task(task["id"])["project_id"] == DEFAULT_PROJECT_ID


def test_the_sync_move_tool_moves_nothing(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, task = records(client)
    before = state(db)
    reply = CompanyTaskTools(agent_os).move_company_task(task["id"], None, _agno_run_context=context())
    assert "asynchronous run" in reply and state(db) == before


@pytest.mark.parametrize("caller", ["routine-run", "task-run", "service-account", "scheduler", "automation-tick"])
def test_only_a_person_moves_a_task_from_chat(system, caller):  # noqa: F811
    client, db, agent_os, queue = system
    project, task = records(client)
    accepted(client, task)
    before = db.get_task(task["id"])
    token = _automatic_task.set({"id": "task"}) if caller == "automation-tick" else None
    try:
        reply = move(agent_os, automated_callers()[caller], task["id"], None)
    finally:
        if token is not None:
            _automatic_task.reset(token)
    assert reply.startswith("Not done") and "human" in reply, reply
    assert db.get_task(task["id"]) == before


def test_moving_a_task_from_chat_needs_the_persons_grant_and_a_stage_that_moves(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, task = records(client)
    launch = second_project(client, project["goal_id"])
    later = second_project(client, project["goal_id"], name="Later", approve=False)
    accepted(client, task)
    before = db.get_task(task["id"])
    without = [scope for scope in SCOPES if scope != "tasks:write"]
    assert move(agent_os, context(scopes=without), task["id"], launch["id"]).startswith("Not done")
    assert move(agent_os, context(), task["id"], later["id"]) == "Not done: " + TASK_MOVE_REFUSAL["inactive"]
    assert move(agent_os, context(), "missing", launch["id"]) == "Not done: Task not found"
    assert db.get_task(task["id"]) == before
    in_review(client, db, queue, records(client)[1]["id"])
    assert client.post(f"/company/tasks/{task['id']}/runs", headers=headers()).status_code == 202
    assert move(agent_os, context(), task["id"], launch["id"]) == "Not done: " + TASK_MOVE_REFUSAL["in_progress"]


# ----------------------------------------------------------------- a run the scheduler fired


def scheduled(user="alice"):
    """A run a schedule fired where authorization is off: no authority, the owner's id, and the mark."""
    return RunContext(run_id="tick", session_id="s", user_id=user, metadata={SCHEDULED_RUN_METADATA_KEY: True})


async def forwarded(payload):
    """What the scheduler sends to a run endpoint for a schedule with this payload."""
    executor = ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok", poll_interval=0)
    captured = {}

    async def capture(client, url, sent_headers, form, resource_type, resource_id, timeout_seconds):
        captured.update(form=form, headers=sent_headers)
        return {"status": "success"}

    schedule = Schedule(
        id="sched-1", name="s", endpoint="/teams/superagent/runs", method="POST", cron_expr="* * * * *", payload=payload
    )
    with patch.object(executor, "_get_client", AsyncMock(return_value=MagicMock())):
        with patch.object(executor, "_background_run", side_effect=capture):
            await executor._call_endpoint(schedule)
    return captured


@pytest.mark.asyncio
async def test_the_scheduler_marks_a_run_that_has_no_authority_to_carry_it():
    from agno.run.authorization import AUTHORIZATION_HEADER, AUTHORIZATION_KEY

    # No saved authority, or one saved empty where authorization is off: the run's metadata says so.
    for payload in ({"message": "hi"}, {"message": "hi", AUTHORIZATION_KEY: None}):
        sent = await forwarded(payload)
        assert json.loads(sent["form"]["metadata"]) == {SCHEDULED_RUN_METADATA_KEY: True}
    # The schedule's own metadata is kept, and it cannot switch the mark off.
    sent = await forwarded({"message": "hi", "metadata": {"team": "docs", SCHEDULED_RUN_METADATA_KEY: False}})
    assert json.loads(sent["form"]["metadata"]) == {"team": "docs", SCHEDULED_RUN_METADATA_KEY: True}
    # A saved authority carries the fact itself, and the run's metadata is left as it was.
    snapshot = {"context": {"principal_id": "alice", "scopes": []}, "service_account": False}
    sent = await forwarded({"message": "hi", AUTHORIZATION_KEY: snapshot})
    assert "metadata" not in sent["form"]
    assert json.loads(sent["headers"][AUTHORIZATION_HEADER])["scheduled"] is True


@pytest.mark.parametrize("authorization", [False, True], ids=["authorization-off", "authorization-on"])
def test_a_scheduled_run_adds_and_moves_no_work_with_or_without_authorization(tmp_path, authorization):
    client, db, agent_os, queue = build(tmp_path, **({} if authorization else {"authorization": None}))
    try:
        project, task = records(client)
        accepted(client, task)
        before = state(db)
        callers = [scheduled()] if not authorization else [context(scheduled=True), context()]
        if authorization:
            # The mark refuses even a run that carries a person's authority.
            callers[1].metadata = {SCHEDULED_RUN_METADATA_KEY: True}
        for caller in callers:
            for start in (False, True):
                reply = call(agent_os, "add_company_task", caller, title="Later", brief="Do it.", start=start)
                assert reply == (
                    "Not done: Only a calling human may add accepted Company work from chat; "
                    "a scheduled run has no person present"
                )
            reply = move(agent_os, caller, task["id"], None)
            assert reply.startswith("Not done") and "a scheduled run has no person present" in reply
        assert state(db) == before
        if not authorization:
            # A person chatting on the same deployment is still trusted, as before.
            person = RunContext(run_id="chat", session_id="s", user_id="alice", authorization=None)
            assert call(agent_os, "add_company_task", person, title="Now", brief="Do it.", start=False).startswith(
                "Added"
            )
            assert move(agent_os, person, task["id"], None).startswith("Moved")
    finally:
        db.close()


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
def test_a_scheduled_run_creates_no_routine_and_no_policy_where_authorization_is_off(tmp_path, use_async):
    policy = PolicySystem(tmp_path, authorization=False)
    try:
        goal_id = policy.client.post("/company/goals", json={"name": "Docs"}).json()["id"]
        tools = company_tools(policy)
        arguments = dict(instructions="Read and propose.", _agno_run_context=scheduled())
        with pytest.raises(PermissionError, match="a scheduled run has no person present"):
            if use_async:
                asyncio.run(tools.acreate_goal_routine(goal_id, "intake", **arguments))
            else:
                tools.create_goal_routine(goal_id, "intake", **arguments)
        with pytest.raises(PermissionError, match="a scheduled run has no person present"):
            if use_async:
                asyncio.run(tools.acreate_company_goal("Other", _agno_run_context=scheduled()))
            else:
                tools.create_company_goal("Other", _agno_run_context=scheduled())
        assert policy.db.get_goal(goal_id)["metadata"].get("routine_ids") in (None, [])
        assert policy.db.get_goals(limit=10)[1] == 1
        # A person on the same deployment creates the Routine, and it gets the default policy.
        person = RunContext(run_id="chat", session_id="s", user_id="alice", authorization=None)
        created = json.loads(
            asyncio.run(
                tools.acreate_goal_routine(
                    goal_id, "intake", instructions="Read and propose.", _agno_run_context=person
                )
            )
        )
        assert created["auto_accept"].startswith("Auto-accept is on"), created
    finally:
        policy.db.close()


def test_a_schedule_aimed_at_super_agent_adds_nothing_where_authorization_is_off(tmp_path):
    chat = System(tmp_path, authorization=None)
    try:
        arguments = {"title": "Nightly", "brief": "Do it.", "start": True}
        chat.os.manager.model = ScriptedModel([("add_company_task", arguments)])
        sent = asyncio.run(forwarded({"message": "Add and start a task to do it."}))
        # The request the scheduler sends: its own token, no authority, the mark in the metadata.
        response = chat.client.post(
            "/teams/superagent/runs",
            data={**sent["form"], "background": "false", "user_id": "alice"},
            headers={"Authorization": "Bearer " + chat.os._internal_service_token},
        )
        assert response.status_code == 200, response.text
        assert "a scheduled run has no person present" in response.json()["content"]
        assert chat.db.get_tasks(limit=10)[1] == 0
        # The same message from a person chatting creates and starts the Task.
        chat.os.manager.model = ScriptedModel([("add_company_task", arguments)])
        response = chat.client.post(
            "/teams/superagent/runs",
            data={"message": "Add and start a task to do it.", "stream": "false", "user_id": "alice"},
        )
        assert response.status_code == 200, response.text
        (task,) = chat.db.get_tasks(limit=10)[0]
        assert task["accepted_by"] == "alice" and task["status"] in ("ready", "in_progress")
    finally:
        chat.db.close()


def test_only_its_accepter_gives_a_ready_task_a_goal(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, _ = records(client)
    loose = client.post("/company/tasks", json={"title": "Loose", "brief": "Write"}, headers=headers()).json()
    task = accepted(client, loose)
    assert (task["goal_id"], task["accepted_by"]) == (None, "alice")
    path = f"/company/tasks/{task['id']}"
    # Its run would act for the Goal under alice's acceptance, so bob cannot make that move.
    refused = client.patch(path, json={"project_id": project["id"]}, headers=headers(user="bob"))
    assert refused.status_code == 403 and refused.json()["detail"] == TASK_MOVE_REFUSAL["goal"], refused.text
    assert move(agent_os, context(user="bob"), task["id"], project["id"]) == "Not done: " + TASK_MOVE_REFUSAL["goal"]
    assert db.get_task(task["id"])["project_id"] == DEFAULT_PROJECT_ID
    # alice can, from the API or from chat.
    moved = client.patch(path, json={"project_id": project["id"]}, headers=headers())
    assert moved.status_code == 200 and moved.json()["goal_id"] == project["goal_id"], moved.text
    # A move that changes no Goal is anyone's with tasks:write, as is a move of finished work.
    launch = second_project(client, project["goal_id"])
    assert client.patch(path, json={"project_id": launch["id"]}, headers=headers(user="bob")).status_code == 200
    other = accepted(
        client, client.post("/company/tasks", json={"title": "Two", "brief": "W"}, headers=headers()).json()
    )
    in_review(client, db, queue, records(client)[1]["id"])
    assert client.post(f"/company/tasks/{other['id']}/runs", headers=headers()).status_code == 202
    from tests.unit.os.test_company_decision_tools import finish

    finish(db, queue, other["id"])
    reviewed = client.patch(
        f"/company/tasks/{other['id']}", json={"project_id": project["id"]}, headers=headers(user="bob")
    )
    assert reviewed.status_code == 200 and reviewed.json()["goal_id"] == project["goal_id"], reviewed.text


def test_where_authorization_is_off_anyone_gives_a_ready_task_a_goal(tmp_path):
    client, db, agent_os, queue = build(tmp_path, authorization=None)
    try:
        project, _ = records(client)
        person = RunContext(run_id="chat", session_id="s", user_id="sam", authorization=None)
        assert call(agent_os, "add_company_task", person, title="Typo", brief="Fix.", start=False).startswith("Added")
        task = next(row for row in db.get_tasks(limit=100)[0] if row["title"] == "Typo")
        moved = client.patch(f"/company/tasks/{task['id']}", json={"project_id": project["id"]})
        assert moved.status_code == 200 and moved.json()["goal_id"] == project["goal_id"], moved.text
    finally:
        db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_a_move_that_gives_a_goal_does_not_carry_an_acceptance_that_landed_meanwhile(tmp_path, use_async):
    db, manager, goal, (release, launch) = await company(tmp_path, use_async)
    draft = await do(manager.create_task(title="Loose", brief="Write"))
    assert (draft["status"], draft["goal_id"], draft["project_id"]) == ("backlog", None, DEFAULT_PROJECT_ID)
    write = db.update_task

    async def accepted_first(*args, **kwargs):
        # Another person accepts the Task after the move was checked and before it is written.
        accept = dict(executor_type="agent", executor_id="writer", accepted_by="alice")
        await do(db.transition_task(draft["id"], "ready", "Accepted", **accept))
        return await do(write(*args, **kwargs))

    def accepted_first_sync(*args, **kwargs):
        db.transition_task(
            draft["id"], "ready", "Accepted", executor_type="agent", executor_id="writer", accepted_by="alice"
        )
        return write(*args, **kwargs)

    with patch.object(db, "update_task", accepted_first if use_async else accepted_first_sync):
        moved = await do(manager.update_task(draft["id"], moved_by="bob", project_id=launch["id"]))
    # The move changes nothing, which the route answers with 409 "Task changed while updating".
    assert moved is None
    now = await do(db.get_task(draft["id"]))
    assert (now["status"], now["accepted_by"], now["goal_id"], now["project_id"]) == (
        "ready",
        "alice",
        None,
        DEFAULT_PROJECT_ID,
    )
    assert [entry.get("action") for entry in now["transitions"]] == [None]
    # A move that gives no Goal is not tied to the stage: it is allowed in each stage that moves.
    await do(manager.update_task(draft["id"], moved_by="bob", project_id=None))


# ----------------------------------------------------------------- a Task with no Goal is filed under one


async def loose_task_at(db, manager, status):
    """A Task with no Goal in the Default Project, taken to a stage the way the product takes it there."""
    task = await do(manager.create_task(title="Check upgrades", brief="Check"))
    assert (task["goal_id"], task["project_id"]) == (None, DEFAULT_PROJECT_ID)
    if status == "backlog":
        return task
    accept = dict(executor_type="agent", executor_id="writer", accepted_by="alice")
    task = await do(manager.transition_task(task_id=task["id"], target="ready", reason="Accepted", **accept))
    if status == "ready":
        return task
    if status == "cancelled":
        return await do(manager.transition_task(task_id=task["id"], target="cancelled", reason="Dropped"))
    task = await do(db.start_task_run(task["id"], 1, task["transitions"], user_id="alice", run_db_id="runs"))
    if status == "in_progress":
        return task
    run_id = task_run_id(task["id"], 1)
    result = {"run_id": run_id, "status": "COMPLETED", "content": "Done"}
    task = await do(db.complete_task_run(task["id"], run_id, result, expected_transitions=task["transitions"]))
    if status == "in_review":
        return task
    return await do(manager.transition_task(task_id=task["id"], target="done", reason="Good", accepted_by="alice"))


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("status", STATUSES)
async def test_a_task_with_no_goal_is_filed_under_a_goal_where_it_is(tmp_path, use_async, status):
    db, manager, goal, _ = await company(tmp_path, use_async)
    task = await loose_task_at(db, manager, status)
    if status not in MOVABLE:
        with pytest.raises(ValueError) as refused:
            await do(manager.update_task(task["id"], moved_by="alice", project_id=None, goal_id=goal["id"]))
        assert str(refused.value) == TASK_MOVE_REFUSAL[status]
        assert await do(db.get_task(task["id"])) == task
        return
    filed = await do(manager.update_task(task["id"], moved_by="alice", project_id=None, goal_id=goal["id"]))
    # It stays in the Default Project and carries the Goal, so its run reads that Goal's Sources.
    assert (filed["goal_id"], filed["project_id"], filed["status"]) == (goal["id"], DEFAULT_PROJECT_ID, status)
    entry = filed["transitions"][-1]
    assert (entry["action"], entry["user_id"], entry["reason"]) == ("move", "alice", "Filed under a Goal")
    assert entry["goal"] == {"from": None, "to": goal["id"]}
    assert entry["project"] == {"from": DEFAULT_PROJECT_ID, "to": DEFAULT_PROJECT_ID}
    assert filed["transitions"][:-1] == task["transitions"]
    kept = ("brief", "title", "executor_type", "executor_id", "accepted_by", "job_id", "result")
    assert {key: filed[key] for key in kept} == {key: task[key] for key in kept}
    # Filing it again records nothing, and it now keeps that Goal.
    again = await do(manager.update_task(task["id"], moved_by="alice", project_id=None, goal_id=goal["id"]))
    assert again["transitions"] == filed["transitions"]
    other = await do(manager.create(name="Docs"))
    with pytest.raises(ValueError, match="A Task keeps its Goal"):
        await do(manager.update_task(task["id"], moved_by="alice", project_id=None, goal_id=other["id"]))
    assert (await do(db.get_task(task["id"])))["goal_id"] == goal["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_a_task_is_filed_only_under_a_goal_that_exists_and_fits_its_project(tmp_path, use_async):
    db, manager, goal, (release, _) = await company(tmp_path, use_async)
    task = await loose_task_at(db, manager, "ready")
    with pytest.raises(LookupError, match="Goal not found"):
        await do(manager.update_task(task["id"], moved_by="alice", project_id=None, goal_id="missing"))
    other = await do(manager.create(name="Docs"))
    # A Project carries its own Goal: another one named beside it is refused.
    with pytest.raises(ValueError, match="Task and Project must belong to the same Goal"):
        await do(manager.update_task(task["id"], moved_by="alice", project_id=release["id"], goal_id=other["id"]))
    # A Goal is given with the Project it is filed in, never alone.
    with pytest.raises(ValueError, match="filed under a Goal together with its Project"):
        await do(manager.update_task(task["id"], moved_by="alice", goal_id=goal["id"]))
    assert await do(db.get_task(task["id"])) == task
    # An archived Goal takes no Task.
    await do(manager.delete(other["id"]))
    with pytest.raises((LookupError, ValueError)):
        await do(manager.update_task(task["id"], moved_by="alice", project_id=None, goal_id=other["id"]))
    assert await do(db.get_task(task["id"])) == task
    # Named beside a Project of the same Goal, the move gives the Goal as before.
    moved = await do(manager.update_task(task["id"], moved_by="alice", project_id=release["id"], goal_id=goal["id"]))
    assert (moved["goal_id"], moved["project_id"]) == (goal["id"], release["id"])
    assert "goal" not in moved["transitions"][-1]


def test_super_agent_files_a_task_under_a_goal_that_has_no_project_for_it(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, _ = records(client)
    added = call(agent_os, "add_company_task", context(), title="Check upgrades", brief="Check.", start=False)
    assert added.startswith("Added"), added
    task = next(row for row in db.get_tasks(limit=100)[0] if row["title"] == "Check upgrades")
    assert (task["goal_id"], task["project_id"], task["status"]) == (None, DEFAULT_PROJECT_ID, "ready")
    goal = db.get_goal(project["goal_id"])
    file = dict(task_id=task["id"], project_id=None, goal_id=goal["id"])
    # While it is Ready its run would act for the Goal under alice's acceptance, so only alice files it.
    refused = call(agent_os, "move_company_task", context(user="bob"), **file)
    assert refused == "Not done: " + TASK_MOVE_REFUSAL["goal"]
    assert db.get_task(task["id"])["goal_id"] is None
    reply = call(agent_os, "move_company_task", context(), **file)
    assert reply == (
        f"Filed 'Check upgrades' (Task {task['id']}) under Goal '{goal['name']}', in Project 'Default'. "
        "Nothing else about it changed."
    )
    filed = db.get_task(task["id"])
    assert (filed["goal_id"], filed["project_id"], filed["status"]) == (goal["id"], DEFAULT_PROJECT_ID, "ready")
    assert (filed["accepted_by"], filed["executor_id"]) == ("alice", task["executor_id"])
    again = call(agent_os, "move_company_task", context(), **file)
    assert (
        again == f"'Check upgrades' (Task {task['id']}) is already under Goal '{goal['name']}', in Project 'Default'."
    )
    assert db.get_task(task["id"]) == filed


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_the_goal_a_task_takes_in_the_default_project_is_on_its_history(tmp_path, use_async):
    db, manager, goal, _ = await company(tmp_path, use_async)
    loose = await do(manager.create_project(name="Odd jobs"))
    task = await do(manager.create_task(title="Check upgrades", brief="Check", project_id=loose["id"]))
    assert (task["goal_id"], task["project_id"]) == (None, loose["id"])
    # A Project with no Goal cannot hold a Goal's Task, so filing it takes it to the Default Project.
    filed = await do(manager.update_task(task["id"], moved_by="alice", project_id=None, goal_id=goal["id"]))
    assert (filed["goal_id"], filed["project_id"]) == (goal["id"], DEFAULT_PROJECT_ID)
    entry = filed["transitions"][-1]
    assert (entry["action"], entry["reason"], entry["user_id"]) == ("move", "Moved to another Project", "alice")
    assert entry["project"] == {"from": loose["id"], "to": DEFAULT_PROJECT_ID}
    # The Default Project says nothing about the Goal, so the entry does.
    assert entry["goal"] == {"from": None, "to": goal["id"]}


def test_super_agent_names_the_goal_a_task_takes_when_it_also_leaves_its_project(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, _ = records(client)
    loose = client.post("/company/projects", json={"name": "Odd jobs"}, headers=headers())
    assert loose.status_code == 201, loose.text
    created = client.post(
        "/company/tasks",
        json={"project_id": loose.json()["id"], "title": "Check upgrades", "brief": "Check"},
        headers=headers(),
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert (task["goal_id"], task["project_id"]) == (None, loose.json()["id"])
    filing = dict(task_id=task["id"], project_id=None, goal_id=project["goal_id"])
    reply = call(agent_os, "move_company_task", context(), **filing)
    assert reply == (
        f"Moved 'Check upgrades' (Task {task['id']}) into Project 'Default' and filed it under Goal 'SDK'. "
        "Nothing else about it changed."
    )
    filed = db.get_task(task["id"])
    assert (filed["goal_id"], filed["project_id"]) == (project["goal_id"], DEFAULT_PROJECT_ID)
    assert filed["transitions"][-1]["goal"] == {"from": None, "to": project["goal_id"]}


def test_super_agent_leaves_a_task_in_its_project_when_it_already_has_the_goal(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, task = records(client)
    before = db.get_task(task["id"])
    assert (before["goal_id"], before["project_id"]) == (project["goal_id"], project["id"])
    # The filing call names no Project: for a Task of that Goal it would only take it out of its Project.
    filing = dict(task_id=task["id"], project_id=None, goal_id=project["goal_id"])
    reply = call(agent_os, "move_company_task", context(), **filing)
    assert reply == (
        f"'Draft' (Task {task['id']}) is already under Goal 'SDK', in Project 'Release'. "
        "It was not moved: to move it to the Default Project, pass a null goal_id."
    )
    assert db.get_task(task["id"]) == before
    # With no Goal named, the same call is the move to the Default Project it always was.
    reply = move(agent_os, context(), task["id"], None)
    assert reply == f"Moved 'Draft' (Task {task['id']}) into Project 'Default'. Nothing else about it changed."
    assert db.get_task(task["id"])["project_id"] == DEFAULT_PROJECT_ID


def test_super_agent_moves_a_task_to_the_default_project_named_beside_its_goal(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, task = records(client)
    # "Move it to Default and keep it under SDK": the Default Project is named, so this is a move.
    named = dict(task_id=task["id"], project_id=DEFAULT_PROJECT_ID, goal_id=project["goal_id"])
    reply = call(agent_os, "move_company_task", context(), **named)
    assert reply == f"Moved 'Draft' (Task {task['id']}) into Project 'Default'. Nothing else about it changed."
    moved = db.get_task(task["id"])
    assert (moved["goal_id"], moved["project_id"]) == (project["goal_id"], DEFAULT_PROJECT_ID)
    assert "goal" not in moved["transitions"][-1]
    # Named again where it already is, nothing is written.
    assert "already in that Project" in call(agent_os, "move_company_task", context(), **named)
    assert db.get_task(task["id"]) == moved


def test_super_agent_is_told_to_file_work_under_the_goal_it_serves():
    from agno.os.manager.prompts import COMPANY_INSTRUCTIONS

    said = " ".join(COMPANY_INSTRUCTIONS.split())
    assert "Before adding a Task, list the Goals and the Projects and put it in the Project it serves." in said
    assert "Work that serves a Goal and none of its Projects goes in the Default Project under that Goal" in said
    assert "leave its Project out and pass the Goal, so its executor can read the Goal's Sources" in said
    assert "fits no Goal and no Project goes in the Default Project with no Goal" in said
    assert "file that Task under the Goal with move_company_task" in said
    doc = " ".join(CompanyTaskTools.aadd_company_task.__doc__.split())
    assert "goal_id: The Goal this Task serves: check list_company_goals." in doc
    # Work Super Agent suggests itself is recorded with the proposal tool, which says the same.
    from agno.tools.company import CompanyTools

    for tool in (CompanyTools.propose_company_task, CompanyTools.apropose_company_task):
        doc = " ".join(tool.__doc__.split())
        assert "goal_id: The Goal this Task serves: check list_company_goals. Its executor reads" in doc
