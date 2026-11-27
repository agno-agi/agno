"""Work a person asks for in chat starts accepted, and a Routine a person creates accepts its own proposals."""

import asyncio
import json

import pytest

from agno.company.declarations import AutoAccept, Routine
from agno.company.execution import _automatic_task
from agno.company.routines import _DECLARED, _policy_fingerprint
from agno.db.schemas.projects import DEFAULT_PROJECT_ID
from agno.os.manager import company_tasks
from agno.os.manager.company_tasks import ACCEPTED_TASKS_PER_RUN, CompanyTaskTools
from agno.registry._reserved import BUILDER_ID, MANAGER_TEAM_ID, MINI_AGENT_ID
from agno.run import RunContext
from agno.run.authorization import AUTHORIZATION_KEY, authorization_scope
from tests.unit.os.test_company_decision_tools import (
    SCOPES,
    accept,
    automated_callers,
    build,
    call,
    chat,  # noqa: F401
    context,
    person,
    records,
    state,
    system,  # noqa: F401
)
from tests.unit.os.test_company_policy_path import SCOPES as POLICY_SCOPES
from tests.unit.os.test_company_policy_path import PolicySystem, company_tools, receipts
from tests.unit.os.test_company_policy_path import chat as policy_chat
from tests.unit.os.test_mini_agent_tasks import ScriptedModel
from tests.unit.os.test_mini_agent_tasks import headers as policy_headers

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")


@pytest.fixture(autouse=True)
def fresh_run_counts():
    """Each test starts with no chat run having added accepted work."""
    company_tasks._accepted_in_run.clear()
    yield
    company_tasks._accepted_in_run.clear()


def add(agent_os, run_context, title="Draft the notes", start=False, **arguments):
    arguments.setdefault("brief", "Write the release notes for 3.3.")
    return call(agent_os, "add_company_task", run_context, title=title, start=start, **arguments)


def only_task(db):
    rows, total = db.get_tasks(limit=100)
    assert total == 1, rows
    return rows[0]


# ----------------------------------------------------------------- the ask is the acceptance


def test_asked_work_is_ready_with_the_person_as_accepter_and_mini_agent_as_executor(system):  # noqa: F811
    client, db, agent_os, queue = system
    reply = add(agent_os, context())
    task = only_task(db)
    assert reply.startswith("Added") and "Ready and not started" in reply and task["id"] in reply, reply
    assert (task["status"], task["accepted_by"], task["user_id"]) == ("ready", "alice", "alice")
    assert (task["executor_type"], task["executor_id"]) == ("agent", MINI_AGENT_ID)
    assert (task["project_id"], task["goal_id"], task["origin"]) == (DEFAULT_PROJECT_ID, None, "human")
    # The acceptance is the person's, with the permissions they held, as on a confirmed acceptance.
    (entry,) = task["transitions"]
    assert (entry["from"], entry["target"], entry["user_id"]) == ("backlog", "ready", "alice")
    assert entry[AUTHORIZATION_KEY] is not None and "auto_accept" not in entry
    # Added is not started.
    assert task["job_id"] is None and asyncio.run(queue.store.get_job(task["id"] + ":1")) is None


def test_asked_to_do_the_work_it_is_accepted_and_started_in_one_call(system):  # noqa: F811
    client, db, agent_os, queue = system
    reply = add(agent_os, context(), start=True, executor_type="agent", executor_id="writer")
    task = only_task(db)
    assert reply.startswith("Added") and "Queued" in reply, reply
    assert (task["status"], task["executor_id"], task["accepted_by"]) == ("in_progress", "writer", "alice")
    assert task["job_id"] is not None
    attempt = [entry for entry in task["transitions"] if entry.get("attempt")][-1]
    # The run is the person's, asked for from this conversation, through the start route's own path.
    assert attempt["started_by"] == "alice"
    assert attempt["requested_from"] == {"session_id": "chat-session", "run_id": "chat-run", "team_id": "superagent"}
    # Asking again for the same Task joins its run instead of starting another.
    again = call(agent_os, "start_company_task", context(), task_id=task["id"])
    assert task["job_id"] in again, again


def test_asked_work_goes_into_the_active_project_named_and_takes_its_goal(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, _ = records(client)
    reply = add(
        agent_os, context(), title="Second", project_id=project["id"], executor_type="agent", executor_id="writer"
    )
    assert reply.startswith("Added"), reply
    task = next(row for row in db.get_tasks(limit=100)[0] if row["title"] == "Second")
    assert (task["project_id"], task["goal_id"], task["status"]) == (project["id"], project["goal_id"], "ready")


def test_the_sync_tool_adds_nothing(system):  # noqa: F811
    client, db, agent_os, queue = system
    reply = CompanyTaskTools(agent_os).add_company_task("Draft", "Write", False, _agno_run_context=context())
    assert "asynchronous run" in reply and db.get_tasks(limit=10)[1] == 0


def test_adding_asked_work_does_not_pause_and_a_proposal_is_still_a_proposal(chat):  # noqa: F811
    functions = CompanyTaskTools(chat.os).get_async_functions()
    assert not functions["add_company_task"].requires_confirmation
    assert functions["accept_company_task"].requires_confirmation is True
    arguments = {"title": "Draft the notes", "brief": "Write the release notes.", "start": False}
    chat.os.manager.model = ScriptedModel([("add_company_task", arguments)])
    with authorization_scope(person):
        run = asyncio.run(chat.os.manager.arun("Add a task to draft the notes", user_id="alice", session_id="chat"))
    assert not run.is_paused, run.content
    task = only_task(chat.db)
    assert (task["status"], task["accepted_by"], task["executor_id"]) == ("ready", "alice", MINI_AGENT_ID)
    # What Super Agent suggests on its own still goes through the propose tool, into Backlog.
    proposal = {"goal_id": None, "title": "An idea", "brief": "Maybe do this."}
    chat.os.manager.model = ScriptedModel([("propose_company_task", proposal)])
    with authorization_scope(person):
        asyncio.run(chat.os.manager.arun("Any ideas?", user_id="alice", session_id="chat-2"))
    idea = next(row for row in chat.db.get_tasks(limit=100)[0] if row["title"] == "An idea")
    assert (idea["status"], idea["accepted_by"]) == ("backlog", None)


# ----------------------------------------------------------------- only a person, and only what they may run


@pytest.mark.parametrize("caller", ["routine-run", "task-run", "service-account", "scheduler", "automation-tick"])
@pytest.mark.parametrize("start", [False, True])
def test_only_a_person_adds_accepted_work(system, caller, start):  # noqa: F811
    client, db, agent_os, queue = system
    token = _automatic_task.set({"id": "task"}) if caller == "automation-tick" else None
    try:
        reply = add(agent_os, automated_callers()[caller], start=start)
    finally:
        if token is not None:
            _automatic_task.reset(token)
    assert reply.startswith("Not done") and "human" in reply, reply
    assert db.get_tasks(limit=10)[1] == 0


def test_a_scheduled_run_adds_no_accepted_work(system):  # noqa: F811
    client, db, agent_os, queue = system
    reply = add(agent_os, context(scheduled=True))
    assert reply.startswith("Not done") and "scheduled run has no person present" in reply, reply
    assert db.get_tasks(limit=10)[1] == 0


@pytest.mark.parametrize("authorization", [True, False], ids=["authorization-on", "authorization-off"])
def test_a_run_with_no_authority_adds_work_only_where_authorization_is_off(tmp_path, authorization):
    client, db, agent_os, queue = build(tmp_path, **({} if authorization else {"authorization": None}))
    try:
        nobody = RunContext(run_id="r", session_id="s", user_id=None, authorization=None)
        reply = add(agent_os, nobody)
        if authorization:
            assert "signed-in person" in reply and db.get_tasks(limit=10)[1] == 0, reply
        else:
            # Where authorization is off the deployment trusts its callers, as the Company API does.
            assert reply.startswith("Added") and only_task(db)["status"] == "ready", reply
    finally:
        db.close()


@pytest.mark.parametrize(
    "missing,executor",
    [("tasks:write", "writer"), ("agents:writer:run", "writer"), (f"agents:{MINI_AGENT_ID}:run", None)],
)
def test_adding_asked_work_needs_the_persons_own_grants(system, missing, executor):  # noqa: F811
    client, db, agent_os, queue = system
    named = {"executor_type": "agent", "executor_id": executor} if executor else {}
    reply = add(agent_os, context(scopes=[scope for scope in SCOPES if scope != missing]), **named)
    assert reply.startswith("Not done"), reply
    assert db.get_tasks(limit=10)[1] == 0
    assert add(agent_os, context(), **named).startswith("Added")


@pytest.mark.parametrize(
    "executor,message",
    [
        (("agent", BUILDER_ID), "Manager specialists are internal"),
        (("team", MANAGER_TEAM_ID), "Not done"),
        (("agent", "nobody"), "Not done"),
        (("robot", "writer"), "executor_type is agent, team or workflow"),
        (("agent", None), "together"),
    ],
)
def test_adding_asked_work_refuses_an_executor_that_cannot_take_it(system, executor, message):  # noqa: F811
    client, db, agent_os, queue = system
    reply = add(agent_os, context(), executor_type=executor[0], executor_id=executor[1])
    assert reply.startswith("Not done") and message in reply, reply
    assert db.get_tasks(limit=10)[1] == 0


def test_accepted_work_is_refused_in_a_proposed_project_with_what_to_do(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, proposal = records(client, approve=False)
    before = state(db)
    reply = add(agent_os, context(), project_id=project["id"])
    assert reply == (
        "Not done: Project 'Release' is proposed, and accepted work needs an active Project. Approve the Project "
        "first, or leave the Project out to put this Task in the Default Project."
    )
    assert state(db) == before
    assert add(agent_os, context(), project_id="missing") == "Not done: Project not found"
    assert state(db) == before


# ----------------------------------------------------------------- what waits for the person's confirmation


def test_the_sixth_task_added_in_one_run_is_a_proposal_the_person_confirms(system):  # noqa: F811
    client, db, agent_os, queue = system
    for number in range(ACCEPTED_TASKS_PER_RUN):
        assert add(agent_os, context(), title=f"Task {number}").startswith("Added")
    reply = add(agent_os, context(), title="Task 6", start=True, executor_type="agent", executor_id="writer")
    sixth = next(row for row in db.get_tasks(limit=100)[0] if row["title"] == "Task 6")
    assert reply.startswith("Recorded") and "as a proposal, not accepted" in reply, reply
    assert "accept_company_task" in reply and "start_company_task" in reply
    # It keeps the executor the person named, as a suggestion, and nothing is accepted or started.
    assert (sixth["status"], sixth["accepted_by"], sixth["executor_id"], sixth["job_id"]) == (
        "backlog",
        None,
        "writer",
        None,
    )
    assert sixth["transitions"] == []
    assert sum(1 for row in db.get_tasks(limit=100)[0] if row["status"] == "ready") == ACCEPTED_TASKS_PER_RUN
    # The tool that accepts it pauses for the person, and with their confirmation it is theirs.
    assert CompanyTaskTools(agent_os).get_async_functions()["accept_company_task"].requires_confirmation is True
    assert accept(agent_os, context(), sixth).startswith("Accepted")
    assert db.get_task(sixth["id"])["accepted_by"] == "alice"
    # The count is the run's. The person's next message is a new run.
    later = context()
    later.run_id = "next-run"
    assert add(agent_os, later, title="Later").startswith("Added")


def test_a_task_that_was_not_created_does_not_use_one_of_the_runs_places(system):  # noqa: F811
    client, db, agent_os, queue = system
    for _ in range(ACCEPTED_TASKS_PER_RUN + 2):
        assert add(agent_os, context(), goal_id="missing").startswith("Not done")
    for number in range(ACCEPTED_TASKS_PER_RUN):
        assert add(agent_os, context(), title=f"Task {number}").startswith("Added")


def test_work_for_an_executor_that_pushes_code_is_a_proposal_the_person_confirms(system, monkeypatch):  # noqa: F811
    from tests.unit.os.test_company_sandboxed_task_goal import writer_pushes_code

    client, db, agent_os, queue = system
    goal_id = writer_pushes_code(monkeypatch, client, agent_os)
    reply = add(agent_os, context(), start=True, executor_type="agent", executor_id="writer")
    task = only_task(db)
    assert reply.startswith("Recorded") and "runs in a sandbox and can push code" in reply, reply
    assert (task["status"], task["accepted_by"], task["executor_id"], task["job_id"], task["goal_id"]) == (
        "backlog",
        None,
        "writer",
        None,
        goal_id,
    )
    # It took none of the run's places for accepted work.
    for number in range(ACCEPTED_TASKS_PER_RUN):
        assert add(agent_os, context(), title=f"Task {number}").startswith("Added")


# ----------------------------------------------------------------- a Routine a person creates


@pytest.fixture
def policy(tmp_path):
    value = PolicySystem(tmp_path)
    yield value
    value.db.close()


def goal(policy, name="Docs"):  # noqa: F811
    created = policy.client.post("/company/goals", json={"name": name}, headers=policy_headers(POLICY_SCOPES))
    assert created.status_code == 201, created.text
    return created.json()["id"]


def grant(policy, routine_id):  # noqa: F811
    return policy.stored(routine_id).get("_agno_company_acceptance")


def test_a_routine_a_person_creates_through_the_api_accepts_its_own_proposals(policy):  # noqa: F811
    goal_id = goal(policy)
    created = policy.api_routine(goal_id)
    assert created.status_code == 201, created.text
    body = created.json()
    stored = policy.stored(body["id"])
    assert stored["metadata"]["auto_accept"] == AutoAccept().model_dump()
    assert body["payload"]["metadata"]["auto_accept"]["max_open"] == 5
    assert body["payload"]["metadata"]["auto_accept"]["default_executor"] == MINI_AGENT_ID
    assert (
        body["auto_accept_note"].startswith("Auto-accept is on")
        and "at most 5 open at once" in body["auto_accept_note"]
    )
    assert f"PATCH /company/routines/{body['id']}" in body["auto_accept_note"]
    assert "_agno_company_acceptance" not in json.dumps(body)
    # The same stored policy and grant as a Routine created with it off and turned on afterwards.
    later = policy.api_routine(goal_id, policy=False, name="later").json()
    assert grant(policy, later["id"]) is None
    turned_on = policy.client.patch(
        f"/company/routines/{later['id']}", json={"auto_accept": True}, headers=policy_headers(POLICY_SCOPES)
    )
    assert turned_on.status_code == 200, turned_on.text
    assert policy.stored(later["id"])["metadata"]["auto_accept"] == stored["metadata"]["auto_accept"]
    assert _policy_fingerprint(policy.db.get_schedule(later["id"])) == _policy_fingerprint(
        policy.db.get_schedule(body["id"])
    )
    first, second = grant(policy, body["id"]), grant(policy, later["id"])
    assert first["user_id"] == second["user_id"] == "alice"
    # The two requests carry tokens minted at different moments, so the saved claims differ in expiry only.
    saved = [value[AUTHORIZATION_KEY]["context"] for value in (first, second)]
    assert saved[0]["principal_id"] == saved[1]["principal_id"] == "alice"
    assert saved[0]["scopes"] == saved[1]["scopes"]
    assert first[AUTHORIZATION_KEY].keys() == second[AUTHORIZATION_KEY].keys()


def test_a_routine_created_with_auto_accept_off_stays_off(policy):  # noqa: F811
    created = policy.api_routine(goal(policy), policy=False).json()
    assert policy.stored(created["id"])["metadata"]["auto_accept"] is False
    assert grant(policy, created["id"]) is None
    assert created["auto_accept_note"].startswith("Auto-accept is off. This Routine's proposals wait for a person.")


def test_a_routine_made_from_a_template_gets_the_policy_too(policy):  # noqa: F811
    # A template names where the instructions came from, not what the Routine may propose.
    body = {"goal_id": goal(policy), "name": "refresh", "template": "refresh", "instructions": "Propose fixes."}
    created = policy.client.post("/company/routines", json=body, headers=policy_headers(POLICY_SCOPES))
    assert created.status_code == 201, created.text
    assert policy.stored(created.json()["id"])["metadata"]["auto_accept"] == AutoAccept().model_dump()
    assert created.json()["auto_accept_note"].startswith("Auto-accept is on")


@pytest.mark.parametrize("missing", ["tasks:write", "projects:write"])
def test_a_person_who_may_not_authorize_the_policy_creates_the_routine_with_it_off(policy, missing):  # noqa: F811
    goal_id = goal(policy)
    scopes = [scope for scope in POLICY_SCOPES if scope != missing]
    created = policy.api_routine(goal_id, scopes=scopes)
    assert created.status_code == 201, created.text
    body = created.json()
    assert policy.stored(body["id"])["metadata"]["auto_accept"] is False and grant(policy, body["id"]) is None
    assert body["auto_accept_note"].startswith("Auto-accept is off: "), body["auto_accept_note"]
    # A policy the request names is still refused outright.
    named = policy.api_routine(goal_id, policy=True, scopes=scopes, name="named")
    assert named.status_code == 403, named.text


def test_a_routine_created_in_chat_gets_the_policy_under_that_persons_grant(policy):  # noqa: F811
    goal_id = goal(policy)
    tools = company_tools(policy)
    created = json.loads(
        asyncio.run(
            tools.acreate_goal_routine(
                goal_id, "intake", instructions="Read the Sources and propose work.", _agno_run_context=policy_chat()
            )
        )
    )
    assert created["auto_accept"].startswith("Auto-accept is on"), created
    assert "turn_off_routine_auto_accept" in created["auto_accept"]
    assert created["payload"]["metadata"]["auto_accept"]["max_open"] == 5
    stored = policy.stored(created["id"])
    assert stored["metadata"]["auto_accept"] == AutoAccept().model_dump()
    assert stored["_agno_company_acceptance"]["user_id"] == "alice"
    # The same grant as the turn-on tool stamps.
    off = json.loads(
        asyncio.run(
            tools.acreate_goal_routine(
                goal_id,
                "second",
                instructions="Read the Sources and propose work.",
                leave_auto_accept_off=True,
                _agno_run_context=policy_chat(),
            )
        )
    )
    assert off["auto_accept"].startswith("Auto-accept is off. ") and grant(policy, off["id"]) is None
    from tests.unit.os.test_company_policy_path import turn_on

    assert turn_on(policy, off["id"], routine="second").startswith("Auto-accept is on")
    assert grant(policy, off["id"]).keys() == stored["_agno_company_acceptance"].keys()
    assert policy.stored(off["id"])["metadata"]["auto_accept"] == stored["metadata"]["auto_accept"]


def test_a_person_without_the_grants_creates_the_routine_in_chat_with_it_off(policy):  # noqa: F811
    goal_id = goal(policy)
    scopes = [scope for scope in POLICY_SCOPES if scope != "tasks:write"]
    created = json.loads(
        asyncio.run(
            company_tools(policy).acreate_goal_routine(
                goal_id, "intake", instructions="Read and propose.", _agno_run_context=policy_chat(scopes=scopes)
            )
        )
    )
    assert created["auto_accept"].startswith("Auto-accept is off: "), created
    assert policy.stored(created["id"])["metadata"]["auto_accept"] is False and grant(policy, created["id"]) is None


def test_the_sync_chat_tool_creates_the_routine_with_auto_accept_off(policy):  # noqa: F811
    goal_id = goal(policy)
    created = json.loads(
        company_tools(policy).create_goal_routine(
            goal_id, "intake", instructions="Read and propose.", _agno_run_context=policy_chat()
        )
    )
    assert created["auto_accept"].startswith("Auto-accept is off: turning it on needs an asynchronous run")
    assert policy.stored(created["id"])["metadata"]["auto_accept"] is False and grant(policy, created["id"]) is None


@pytest.mark.parametrize("auto_accept", [True, False])
def test_a_goal_created_in_chat_with_routines_turns_each_ones_policy_on(policy, auto_accept):  # noqa: F811
    routines = [
        Routine(name="intake", instructions="Read the Sources and propose work."),
        Routine(name="summary", template="summary"),
    ]
    created = json.loads(
        asyncio.run(
            company_tools(policy).acreate_company_goal(
                "Docs", routines=routines, leave_auto_accept_off=not auto_accept, _agno_run_context=policy_chat()
            )
        )
    )
    by_name = {policy.db.get_schedule(i)["name"].split(".", 1)[1]: i for i in created["metadata"]["routine_ids"]}
    assert set(created["routines_auto_accept"]) == {"intake", "summary"}
    for name in ("intake", "summary"):
        note = created["routines_auto_accept"][name]
        assert note.startswith("Auto-accept is on" if auto_accept else "Auto-accept is off."), note
        stored = policy.stored(by_name[name])
        assert bool(stored["metadata"]["auto_accept"]) is auto_accept
        assert (stored.get("_agno_company_acceptance") or {}).get("user_id") == ("alice" if auto_accept else None)


def test_a_goal_created_in_chat_cannot_declare_a_policy_of_its_own(policy):  # noqa: F811
    for declared in (True, AutoAccept(max_open=50)):
        custom = Routine(name="intake", instructions="Read.", auto_accept=declared)
        with pytest.raises(ValueError, match="Authorize automatic acceptance through the Routine API"):
            asyncio.run(
                company_tools(policy).acreate_company_goal("Docs", routines=[custom], _agno_run_context=policy_chat())
            )
    assert policy.db.get_goals(limit=10)[1] == 0


@pytest.mark.parametrize("caller", ["routine-run", "task-run", "service-account", "scheduler"])
def test_no_automated_caller_creates_a_routine_with_a_policy_in_chat(policy, caller):  # noqa: F811
    goal_id = goal(policy)
    with pytest.raises(PermissionError):
        asyncio.run(
            company_tools(policy).acreate_goal_routine(
                goal_id, "intake", instructions="Read and propose.", _agno_run_context=automated_callers()[caller]
            )
        )
    assert policy.db.get_goal(goal_id)["metadata"].get("routine_ids") in (None, [])


def test_setup_turns_the_policy_on_for_the_routines_it_creates(policy):  # noqa: F811
    body = {
        "name": "Docs",
        "routines": [
            {"name": "intake", "instructions": "Read the Sources and propose work."},
            {"name": "quiet", "instructions": "Read the Sources and propose work.", "auto_accept": False},
        ],
    }
    created = policy.client.post("/company/setup", json=body, headers=policy_headers(POLICY_SCOPES))
    assert created.status_code == 201, created.text
    row = created.json()
    assert set(row["routines_auto_accept"]) == {"intake"} and row["routines_auto_accept"]["intake"].startswith(
        "Auto-accept is on"
    )
    by_name = {policy.db.get_schedule(i)["name"].split(".", 1)[1]: i for i in row["metadata"]["routine_ids"]}
    assert policy.stored(by_name["intake"])["metadata"]["auto_accept"] == AutoAccept().model_dump()
    assert grant(policy, by_name["intake"])["user_id"] == "alice"
    assert policy.stored(by_name["quiet"])["metadata"]["auto_accept"] is False
    # A person turns it off, and sending the same setup again leaves the stored Routine as it is.
    path = f"/company/routines/{by_name['intake']}"
    assert (
        policy.client.patch(path, json={"auto_accept": False}, headers=policy_headers(POLICY_SCOPES)).status_code == 200
    )
    again = policy.client.post("/company/setup", json=body, headers=policy_headers(POLICY_SCOPES))
    assert again.status_code == 200 and "routines_auto_accept" not in again.json()
    assert policy.stored(by_name["intake"])["metadata"]["auto_accept"] is False


def test_a_routine_declared_in_code_keeps_what_its_declaration_says(policy):  # noqa: F811
    # No person stands behind a declaration, so nothing is turned on for it.
    _, plain = policy.declare(auto_accept=False)
    assert policy.stored(plain)["metadata"]["auto_accept"] is False and grant(policy, plain) is None
    # A declared policy still acts for no one where authorization is on.
    goal_id, declared = policy.declare(auto_accept=True, goal="Other")
    assert grant(policy, declared) == _DECLARED
    _, task = policy.proposes(goal_id, declared)
    outcome = policy.outcome(policy.tick(), task["id"])
    assert outcome["status"] == "skipped" and "acts only where authorization is off" in outcome["reason"]
    assert policy.db.get_task(task["id"])["status"] == "backlog"


def test_a_stored_routine_is_not_changed_by_reading_or_editing_it(policy):  # noqa: F811
    created = policy.api_routine(goal(policy), policy=False).json()
    path = f"/company/routines/{created['id']}"
    edited = policy.client.patch(path, json={"instructions": "Read again."}, headers=policy_headers(POLICY_SCOPES))
    assert edited.status_code == 200, edited.text
    assert policy.stored(created["id"])["metadata"]["auto_accept"] is False and grant(policy, created["id"]) is None
    assert edited.json()["auto_accept_note"] is None


def test_the_default_policy_accepts_the_routines_own_proposal_and_stops_at_five(policy):  # noqa: F811
    goal_id = goal(policy)
    routine_id = policy.api_routine(goal_id).json()["id"]
    tasks = [policy.proposes(goal_id, routine_id, title=f"Fix {number}")[1] for number in range(6)]
    policy.tick()
    accepted = [task for task in tasks if receipts(policy.db.get_task(task["id"]))]
    assert len(accepted) == 5
    record = policy.db.get_task(accepted[0]["id"])
    assert record["accepted_by"] == "alice" and record["executor_id"] == MINI_AGENT_ID
    # The Routine's own Project was approved with it, under the same grant.
    assert policy.db.get_project(record["project_id"])["status"] == "active"


def test_the_default_policy_leaves_a_task_in_the_default_project_for_a_person(policy):  # noqa: F811
    goal_id = goal(policy)
    routine_id = policy.api_routine(goal_id).json()["id"]
    # A proposal with no Project goes to the Default Project, which nobody approved.
    stray = policy.manager.create_task(
        goal_id=goal_id, title="Stray", brief="Fix it.", origin="routine", routine_id=routine_id
    )
    assert stray["project_id"] == DEFAULT_PROJECT_ID
    outcome = policy.outcome(policy.tick(), stray["id"])
    assert outcome["status"] == "skipped"
    assert outcome["reason"] == "A Task in the Default Project waits for a person to accept it"
    record = policy.db.get_task(stray["id"])
    assert record["status"] == "backlog" and not receipts(record)


def test_a_task_added_to_be_started_later_is_not_picked_up_by_the_automation_tick(policy):  # noqa: F811
    tools = CompanyTaskTools(policy.os)
    added = asyncio.run(tools.aadd_company_task("Later", "Do it.", False, _agno_run_context=policy_chat()))
    assert added.endswith("It is Ready and not started."), added
    held = only_task(policy.db)
    assert held["transitions"][-1]["start_on_request"] is True
    # A Task accepted in the Company pages is still picked up, as before.
    paged = policy.client.post(
        "/company/tasks",
        json={
            "title": "Paged",
            "brief": "Do it.",
            "status": "ready",
            "executor_type": "agent",
            "executor_id": "writer",
        },
        headers=policy_headers(POLICY_SCOPES),
    ).json()
    outcomes = policy.tick()
    assert policy.outcome(outcomes, held["id"]) is None
    assert policy.db.get_task(held["id"]) == held
    assert policy.db.get_task(paged["id"])["status"] == "in_progress"
    assert policy.tick() is not None and policy.db.get_task(held["id"]) == held
    # The person starts it when they say so.
    started = asyncio.run(tools.astart_company_task(held["id"], _agno_run_context=policy_chat()))
    assert started.startswith("Queued"), started
    assert policy.db.get_task(held["id"])["status"] == "in_progress"


def test_a_task_asked_to_be_done_is_not_held(policy):  # noqa: F811
    tools = CompanyTaskTools(policy.os)
    asyncio.run(tools.aadd_company_task("Now", "Do it.", True, _agno_run_context=policy_chat()))
    task = only_task(policy.db)
    acceptance = next(entry for entry in task["transitions"] if entry.get("target") == "ready")
    assert "start_on_request" not in acceptance and task["status"] == "in_progress"


@pytest.mark.parametrize("start", [False, True])
def test_a_task_past_five_added_to_be_started_later_is_still_held_once_it_is_accepted(policy, start):  # noqa: F811
    tools = CompanyTaskTools(policy.os)
    for number in range(ACCEPTED_TASKS_PER_RUN):
        asyncio.run(tools.aadd_company_task(f"Task {number}", "Do it.", False, _agno_run_context=policy_chat()))
    reply = asyncio.run(tools.aadd_company_task("Sixth", "Do it.", start, _agno_run_context=policy_chat()))
    assert reply.startswith("Recorded") and "as a proposal, not accepted" in reply, reply
    sixth = next(row for row in policy.db.get_tasks(limit=100)[0] if row["title"] == "Sixth")
    assert sixth["status"] == "backlog"

    # The person confirms it. What they asked for decides whether it waits for a start.
    assert accept(policy.os, policy_chat(), sixth, executor=("agent", MINI_AGENT_ID)).startswith("Accepted")
    accepted = policy.db.get_task(sixth["id"])
    acceptance = accepted["transitions"][-1]
    assert (accepted["status"], acceptance["target"]) == ("ready", "ready")
    assert acceptance.get("start_on_request") is (None if start else True)
    policy.tick()
    after = policy.db.get_task(sixth["id"])
    if start:
        # Asked to be done, it is picked up like any accepted Task.
        assert after["status"] == "in_progress"
    else:
        # Asked only to be added, it is held like the five before it.
        assert after == accepted
        started = asyncio.run(tools.astart_company_task(sixth["id"], _agno_run_context=policy_chat()))
        assert started.startswith("Queued"), started


@pytest.mark.parametrize("through", ["chat", "api"])
def test_a_task_added_for_later_is_still_held_after_a_return_to_backlog(policy, through):  # noqa: F811
    tools = CompanyTaskTools(policy.os)
    asyncio.run(tools.aadd_company_task("Later", "Do it.", False, _agno_run_context=policy_chat()))
    held = only_task(policy.db)
    # Back to Backlog, as an edit of the brief needs, then accepted again.
    back = policy.manager.transition_task(task_id=held["id"], target="backlog", reason="Edit the brief")
    assert back["status"] == "backlog"
    if through == "chat":
        assert accept(policy.os, policy_chat(), back, executor=("agent", MINI_AGENT_ID)).startswith("Accepted")
    else:
        again = policy.client.post(
            f"/company/tasks/{held['id']}/transitions",
            json={"target": "ready", "reason": "Go", "executor_type": "agent", "executor_id": MINI_AGENT_ID},
            headers=policy_headers(POLICY_SCOPES),
        )
        assert again.status_code == 200, again.text
    accepted = policy.db.get_task(held["id"])
    assert accepted["status"] == "ready" and accepted["transitions"][-1]["start_on_request"] is True

    policy.tick()

    # The person asked only to add it, so it still waits for a start.
    assert policy.db.get_task(held["id"]) == accepted
    started = asyncio.run(tools.astart_company_task(held["id"], _agno_run_context=policy_chat()))
    assert started.startswith("Queued"), started


def test_a_routine_created_in_chat_is_triggered_by_hand_where_authorization_is_off(tmp_path):
    # A deployment that checks no permissions and knows no caller: the chat's user id is only a label.
    system = PolicySystem(tmp_path, authorization=False)  # noqa: F811
    try:
        goal_id = system.client.post("/company/goals", json={"name": "Docs"}).json()["id"]
        sam = RunContext(run_id="r", session_id="s", user_id="sam", authorization=None)
        created = json.loads(
            asyncio.run(
                company_tools(system).acreate_goal_routine(
                    goal_id, "intake", instructions="Read and propose.", _agno_run_context=sam
                )
            )
        )
        assert created["auto_accept"].startswith("Auto-accept is on")
        assert system.stored(created["id"])["_agno_company_acceptance"]["user_id"] == "sam"
        # The request reaches the scheduler, which these tests do not start.
        for params in ({}, {"user_id": "sam"}, {"user_id": "someone-else"}):
            triggered = system.client.post(f"/company/routines/{created['id']}/trigger", params=params)
            assert (triggered.status_code, triggered.json()["detail"]) == (503, "Scheduler is not running")
    finally:
        system.db.close()
