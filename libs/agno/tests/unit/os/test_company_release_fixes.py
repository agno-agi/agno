"""Company fixes before 3.2: one section per finding, each with the healthy case next to the refusal."""

import asyncio

import pytest

from agno.company.declarations import AutoAccept
from agno.company.routines import _DECLARED, _policy_fingerprint
from agno.run.authorization import AUTHORIZATION_KEY
from tests.unit.os.test_company_policy_path import (
    SCOPES,
    PolicySystem,
    chat,
    turn_off,
    turn_on,
    waiting,
)
from tests.unit.os.test_mini_agent_tasks import headers

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")


@pytest.fixture
def system(tmp_path):
    """A deployment with authorization on."""
    value = PolicySystem(tmp_path)
    yield value
    value.db.close()


@pytest.fixture
def open_system(tmp_path):
    """A deployment with authorization off."""
    value = PolicySystem(tmp_path, authorization=False)
    yield value
    value.db.close()


def principal(payload):
    return ((payload.get(AUTHORIZATION_KEY) or {}).get("context") or {}).get("principal_id")


# ----------------------------------------------------------------- turning auto-accept off grants nothing


def test_turning_auto_accept_off_from_chat_leaves_a_waiting_declared_routine_with_no_run_authority(system):
    product_id, routine_id = system.declare(auto_accept=True)
    assert AUTHORIZATION_KEY not in system.stored(routine_id)

    assert turn_off(system, routine_id).startswith("Auto-accept is off")
    after = system.stored(routine_id)
    assert after["metadata"]["auto_accept"] is False and "_agno_company_acceptance" not in after
    # No person confirmed anything, so the Routine does not start running under the chatting person.
    assert AUTHORIZATION_KEY not in after


@pytest.mark.parametrize("surface", ["chat", "api"])
def test_turning_auto_accept_off_keeps_the_run_authority_of_the_person_who_authored_the_routine(system, surface):
    product_id, _ = system.declare(auto_accept=False)
    created = system.api_routine(product_id, {"default_executor": "writer"}, name="authored")
    assert created.status_code == 201, created.text
    routine_id = created.json()["id"]
    before = system.stored(routine_id)
    assert principal(before) == "alice" and before["_agno_company_acceptance"]["user_id"] == "alice"

    if surface == "chat":
        assert turn_off(system, routine_id, chat(user="bob"), routine="authored").startswith("Auto-accept is off")
    else:
        path = f"/company/routines/{routine_id}"
        patched = system.client.patch(path, json={"auto_accept": False}, headers=headers(SCOPES, user="bob"))
        assert patched.status_code == 200, patched.text
    after = system.stored(routine_id)
    assert after["metadata"]["auto_accept"] is False and "_agno_company_acceptance" not in after
    assert after[AUTHORIZATION_KEY] == before[AUTHORIZATION_KEY]


def test_turning_auto_accept_off_twice_grants_nothing(system):
    product_id, routine_id = system.declare(auto_accept=False)
    before = system.stored(routine_id)
    assert turn_off(system, routine_id).startswith("Auto-accept is off")
    assert system.stored(routine_id) == before


def test_a_person_who_may_not_run_the_executor_can_still_turn_auto_accept_off(system):
    product_id, routine_id = system.declare(auto_accept=False)
    assert turn_on(system, routine_id).startswith("Auto-accept is on")
    without = [scope for scope in SCOPES if not scope.startswith("agents:")]
    assert turn_off(system, routine_id, chat(scopes=without, user="bob")).startswith("Auto-accept is off")
    after = system.stored(routine_id)
    assert after["metadata"]["auto_accept"] is False and principal(after) == "alice"


def test_turning_auto_accept_on_and_editing_instructions_still_take_the_editors_authority(system):
    product_id, routine_id = system.declare(auto_accept=False)
    assert turn_on(system, routine_id, chat(user="bob")).startswith("Auto-accept is on")
    assert principal(system.stored(routine_id)) == "bob"
    path = f"/company/routines/{routine_id}"
    # Turning it off in the same request as an instructions edit is an edit of what the Routine runs.
    body = {"auto_accept": False, "instructions": "Read the Sources again."}
    assert system.client.patch(path, json=body, headers=headers(SCOPES, user="carol")).status_code == 200
    after = system.stored(routine_id)
    assert principal(after) == "carol" and after["metadata"]["auto_accept"] is False


# ----------------------------------------------------------------- an edit does not turn a declared policy on


@pytest.mark.parametrize("edit", [{"instructions": "Read the Sources again."}, {"executor_id": "writer"}])
def test_an_edit_that_does_not_set_auto_accept_leaves_a_declared_policy_waiting(system, edit):
    declared = AutoAccept(default_executor="writer", max_open=2)
    product_id, routine_id = system.declare(auto_accept=declared)
    version = _policy_fingerprint(system.db.get_schedule(routine_id))
    project, task = system.proposes(product_id, routine_id)

    path = f"/company/routines/{routine_id}"
    patched = system.client.patch(path, json=edit, headers=headers(SCOPES, user="bob"))
    assert patched.status_code == 200, patched.text
    after = system.stored(routine_id)
    # The policy is the declared one and still has no person behind it.
    assert after["_agno_company_acceptance"] == _DECLARED
    assert after["metadata"]["auto_accept"] == declared.model_dump()
    assert _policy_fingerprint(system.db.get_schedule(routine_id)) == version
    assert waiting(system) == [("intake", "docs", "writer")]

    outcome = system.outcome(system.tick(), task["id"])
    assert outcome["status"] == "skipped" and "acts only where authorization is off" in outcome["reason"], outcome
    assert system.db.get_task(task["id"])["status"] == "backlog"
    assert system.db.get_project(project["id"])["status"] == "proposed"

    # A person still turns it on with one confirmation, and it then runs under that person.
    assert "with the policy its code declares" in turn_on(system, routine_id, chat(user="carol"))
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "carol"
    system.tick()
    assert system.db.get_task(task["id"])["status"] == "in_progress"


def test_editing_a_waiting_declared_routine_does_not_need_the_permissions_its_policy_would_use(system):
    product_id, routine_id = system.declare(auto_accept=True)
    without = [scope for scope in SCOPES if scope not in ("tasks:write", "projects:write")]
    path = f"/company/routines/{routine_id}"
    patched = system.client.patch(path, json={"instructions": "Read again."}, headers=headers(without, user="bob"))
    assert patched.status_code == 200, patched.text
    assert system.stored(routine_id)["_agno_company_acceptance"] == _DECLARED


def test_an_edit_of_a_policy_a_person_set_still_needs_the_editors_own_grant(system):
    product_id, routine_id = system.declare(auto_accept=False)
    assert turn_on(system, routine_id).startswith("Auto-accept is on")
    path = f"/company/routines/{routine_id}"
    without = [scope for scope in SCOPES if scope != "tasks:write"]
    refused = system.client.patch(path, json={"instructions": "Read again."}, headers=headers(without, user="bob"))
    assert refused.status_code == 403, refused.text
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "alice"
    edited = system.client.patch(path, json={"instructions": "Read again."}, headers=headers(SCOPES, user="bob"))
    assert edited.status_code == 200, edited.text
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "bob"


def test_setting_auto_accept_on_a_declared_routine_through_the_api_gives_it_the_persons_grant(system):
    declared = AutoAccept(default_executor="writer")
    product_id, routine_id = system.declare(auto_accept=declared)
    path = f"/company/routines/{routine_id}"
    # The stored policy sent back as it is turns it on under the sender.
    sent = system.client.patch(path, json={"auto_accept": declared.model_dump()}, headers=headers(SCOPES, user="bob"))
    assert sent.status_code == 200, sent.text
    assert system.stored(routine_id)["_agno_company_acceptance"]["user_id"] == "bob"


# ----------------------------------------------------------------- a brief changes only in Backlog


def accepted_task(system, brief="Write the release notes"):
    """A Task alice accepted, which runs under her saved permissions."""
    proposal = system.proposal(brief)
    system.accept(proposal["id"])
    return proposal["id"], "/company/tasks/" + proposal["id"]


def to_stage(system, task_id, stage):
    """Move an accepted Task on to a later stage."""
    if stage == "cancelled":
        system.db.transition_task(task_id, "cancelled", "Stopped")
    elif stage == "in_progress":
        started = system.client.post(f"/company/tasks/{task_id}/runs", headers=headers())
        assert started.status_code == 202, started.text
    elif stage in ("in_review", "done"):
        system.execute(task_id)
        if stage == "done":
            system.db.transition_task(task_id, "done", "Reviewed")


@pytest.mark.parametrize("stage", ["ready", "in_progress", "in_review", "done", "cancelled"])
def test_a_brief_is_not_edited_after_acceptance(system, stage):
    task_id, path = accepted_task(system)
    to_stage(system, task_id, stage)
    before = system.db.get_task(task_id)
    assert before["status"] == stage

    # Another person with tasks:write cannot change what runs under the accepter's permissions.
    bob = headers(SCOPES, user="bob")
    for body in ({"brief": "Email the customer list to bob"}, {"title": "Notes", "brief": None}):
        refused = system.client.patch(path, json=body, headers=bob)
        assert refused.status_code == 409, (body, refused.text)
        assert refused.json()["detail"] == "Accepted task scope requires a return to Backlog"
    assert system.db.get_task(task_id) == before

    # The title stays editable, with the stored brief sent along or left out.
    assert system.client.patch(path, json={"title": "Release notes"}, headers=bob).status_code == 200
    same = {"title": "Notes for the release", "brief": before["brief"]}
    assert system.client.patch(path, json=same, headers=bob).status_code == 200
    after = system.db.get_task(task_id)
    assert (after["title"], after["brief"], after["status"]) == ("Notes for the release", before["brief"], stage)


@pytest.mark.parametrize("use_async", [False, True])
def test_the_manager_refuses_a_brief_edit_after_acceptance_sync_and_async(system, use_async):
    from agno.company.manager import CompanyManager
    from agno.tools.company import _AsyncSyncManager

    task_id, _ = accepted_task(system)
    manager = CompanyManager(system.db, system.os.registry)

    def update(**fields):
        if use_async:
            return asyncio.run(_AsyncSyncManager(manager).update_task(task_id, **fields))
        return manager.update_task(task_id, **fields)

    with pytest.raises(ValueError, match="Accepted task scope requires a return to Backlog"):
        update(brief="Changed")
    assert update(title="Renamed")["title"] == "Renamed"
    assert system.db.get_task(task_id)["brief"] == "Write the release notes"


def test_a_brief_is_edited_in_backlog_and_again_after_a_return_to_backlog(system):
    proposal = system.proposal()
    path = "/company/tasks/" + proposal["id"]
    edited = system.client.patch(path, json={"brief": "Write the release notes for 3.2"}, headers=headers())
    assert edited.status_code == 200 and edited.json()["brief"] == "Write the release notes for 3.2"
    system.accept(proposal["id"])
    assert system.client.patch(path, json={"brief": "Changed"}, headers=headers()).status_code == 409
    returned = system.client.post(
        path + "/transitions", json={"target": "backlog", "reason": "Rescope"}, headers=headers()
    )
    assert returned.status_code == 200, returned.text
    assert system.client.patch(path, json={"brief": "Changed"}, headers=headers()).json()["brief"] == "Changed"


def test_a_brief_edit_that_loses_the_race_with_acceptance_is_not_written(system, monkeypatch):
    proposal = system.proposal()
    task_id = proposal["id"]
    read = system.db.get_task

    def accepted_after_the_read(*args, **kwargs):
        row = read(*args, **kwargs)
        monkeypatch.setattr(system.db, "get_task", read)
        system.accept(task_id)
        return row

    monkeypatch.setattr(system.db, "get_task", accepted_after_the_read)
    from agno.company.manager import CompanyManager

    assert CompanyManager(system.db, system.os.registry).update_task(task_id, brief="Changed") is None
    stored = system.db.get_task(task_id)
    assert (stored["status"], stored["brief"]) == ("ready", "Write the release notes")


def test_the_chat_tool_edits_a_title_after_acceptance_and_refuses_a_new_brief(system):
    from agno.tools.company import CompanyTools

    task_id, _ = accepted_task(system)
    tools = CompanyTools(system.db, registry=system.os.registry)
    with pytest.raises(ValueError, match="Accepted task scope requires a return to Backlog"):
        tools.edit_company_task(task_id, "Notes", "Changed", _agno_run_context=chat())
    tools.edit_company_task(task_id, "Release notes", "Write the release notes", _agno_run_context=chat())
    stored = system.db.get_task(task_id)
    assert (stored["title"], stored["brief"]) == ("Release notes", "Write the release notes")


# ----------------------------------------------------------------- a sandboxed executor runs only its own Task


def sandboxed(system, monkeypatch):
    """Serve a sandboxed agent next to the writer and record every run it is given."""
    from agno.sandbox import Repository
    from agno.sandbox.docker import DockerSandbox
    from agno.sandbox.fixture import FixtureAgent

    engineer = FixtureAgent(
        id="engineer",
        name="Engineer",
        sandbox=DockerSandbox("unused", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"}),
        repository=Repository("https://github.com/a/b"),
    )
    runs = []

    def run(*args, **kwargs):
        runs.append(args)
        raise AssertionError("The sandboxed agent ran outside the sandbox gate")

    async def arun(*args, **kwargs):
        run(*args, **kwargs)

    monkeypatch.setattr(engineer, "run", run)
    monkeypatch.setattr(engineer, "arun", arun)
    system.os.agents.append(engineer)
    return runs


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("named", ["engineer", "Engineer"])
def test_mini_agent_does_not_list_or_run_a_sandboxed_agent(system, monkeypatch, use_async, named):
    import json

    from agno.run.authorization import authorization_scope
    from tests.unit.os.test_mini_agent_tasks import task_authority

    runs = sandboxed(system, monkeypatch)
    tools = system.mini.tools.run_tools[0]
    with authorization_scope(lambda: task_authority()):
        if use_async:
            listed = asyncio.run(tools.alist_agents())
            reply = asyncio.run(tools.arun_agent(named, "Fix the bug"))
            healthy = asyncio.run(tools.arun_agent("writer", "Write"))
        else:
            listed = tools.list_agents()
            reply = tools.run_agent(named, "Fix the bug")
            healthy = tools.run_agent("writer", "Write")
    assert [row["id"] for row in json.loads(listed)["agents"]] == ["writer"]
    error = json.loads(reply)["error"]
    assert "sandbox" in error and "accept the Task on" in error and "engineer" in error, error
    assert runs == []
    # A component with no sandbox still runs.
    assert json.loads(healthy)["status"] == "COMPLETED"


def test_a_task_run_on_mini_agent_reports_the_sandboxed_agent_as_a_refusal(system, monkeypatch):
    runs = sandboxed(system, monkeypatch)
    scopes = [*SCOPES, "agents:engineer:run", "agents:engineer:read"]
    proposal = system.proposal()
    system.accept(proposal["id"], scopes=scopes)
    saved = system.execute(
        proposal["id"],
        [("list_agents", {}), ("run_agent", {"agent_id": "engineer", "message": "Fix the bug"})],
        scopes=scopes,
    )
    content = saved["result"]["content"]
    assert "accept the Task on" in content and runs == [], content


# ----------------------------------------------------------------- the auto-accept tools check before they tell


def authored_routine(system):
    """A Routine named 'nightly-intake' in Product 'Docs', with a policy alice set."""
    product_id, _ = system.declare(auto_accept=False)
    created = system.api_routine(product_id, {"default_executor": "writer", "max_open": 3}, name="nightly-intake")
    assert created.status_code == 201, created.text
    return created.json()["id"]


TOLD = ("nightly-intake", "Docs", "default executor writer", "at most 3 Tasks open")


@pytest.mark.parametrize("missing", ["routines:write", "products:read"])
def test_turning_auto_accept_on_tells_nothing_to_a_person_the_routine_api_would_refuse(system, missing):
    routine_id = authored_routine(system)
    before = system.db.get_schedule(routine_id)
    without = chat(scopes=[scope for scope in SCOPES if scope != missing], user="bob")
    # Wrong names and no kept policy: each of these made the tool reply with the stored value.
    for routine, product in (("guess", "Guess"), ("nightly-intake", "Guess"), ("nightly-intake", "Docs")):
        reply = turn_on(system, routine_id, without, routine=routine, product=product)
        assert reply.startswith("Not done") and missing in reply, reply
        told = [text for text in TOLD if text in reply and text not in (routine, product)]
        assert not told, reply
    assert system.db.get_schedule(routine_id) == before


def test_turning_auto_accept_off_tells_nothing_to_a_person_the_routine_api_would_refuse(system):
    routine_id = authored_routine(system)
    before = system.db.get_schedule(routine_id)
    without = chat(scopes=[scope for scope in SCOPES if scope != "routines:write"], user="bob")
    reply = turn_off(system, routine_id, without, routine="guess")
    assert reply.startswith("Not done") and "routines:write" in reply and "nightly-intake" not in reply, reply
    assert system.db.get_schedule(routine_id) == before


def test_a_person_the_routine_api_accepts_is_still_told_what_to_confirm(system):
    routine_id = authored_routine(system)
    bob = chat(user="bob")
    assert "is named 'nightly-intake'" in turn_on(system, routine_id, bob, routine="guess")
    assert "belongs to Product 'Docs'" in turn_on(system, routine_id, bob, routine="nightly-intake", product="Guess")
    kept = turn_on(system, routine_id, bob, routine="nightly-intake")
    assert "default executor writer" in kept and "at most 3 Tasks open" in kept
    assert "is named 'nightly-intake'" in turn_off(system, routine_id, bob, routine="guess")


def test_the_auto_accept_tools_read_a_routine_as_the_routine_api_does(system):
    # An archived Routine and the automation schedule are not Routines to the API, and not to the tools.
    from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID

    routine_id = authored_routine(system)
    archive = headers([*SCOPES, "routines:delete", "schedules:delete"])
    assert system.client.post(f"/company/routines/{routine_id}/archive", headers=archive).status_code == 200
    assert system.client.get(f"/company/routines/{routine_id}", headers=headers(SCOPES)).status_code == 404
    before = system.db.get_schedule(routine_id)
    for target in (routine_id, COMPANY_AUTOMATION_SCHEDULE_ID):
        assert "Routine not found" in turn_on(system, target, routine="nightly-intake")
        assert "Routine not found" in turn_off(system, target, routine="nightly-intake")
    assert system.db.get_schedule(routine_id) == before


# ----------------------------------------------------------------- a policy's executor_type is checked


MISMATCHED = [
    {"executor_type": "team", "executor_id": "writer"},
    {"executor_type": "robot", "executor_id": "writer"},
    {"default_executor": "writer", "executor_type": "workflow", "executor_id": "writer"},
]


@pytest.mark.parametrize("sent", MISMATCHED)
def test_a_policy_whose_executor_type_does_not_match_the_component_is_refused(system, sent):
    product_id, routine_id = system.declare(auto_accept=False)
    before = system.db.get_schedule(routine_id)
    patched = system.client.patch(
        f"/company/routines/{routine_id}", json={"auto_accept": sent}, headers=headers(SCOPES)
    )
    assert patched.status_code == 422, patched.text
    assert system.db.get_schedule(routine_id) == before
    created = system.api_routine(product_id, sent, name="second")
    assert created.status_code == 422, created.text


def test_a_declared_policy_whose_executor_type_does_not_match_is_refused(system):
    from agno.company import Product, Routine
    from agno.company.bootstrap import arehydrate_product

    routine = Routine(name="intake", instructions="Read.", auto_accept=MISMATCHED[0])
    declaration = Product(id="docs", name="Docs", routines=[routine])
    with pytest.raises(ValueError, match="executor_type"):
        asyncio.run(
            arehydrate_product(
                system.db, declaration, system.os.registry, schedule_db=system.db, agent_os=system.os, trusted=True
            )
        )


def test_a_policy_whose_executor_type_matches_is_accepted_in_both_shapes(system):
    product_id, routine_id = system.declare(auto_accept=False)
    path = f"/company/routines/{routine_id}"
    for sent in (
        {"executor_type": "agent", "executor_id": "writer"},
        {"default_executor": "writer", "executor_type": "agent", "executor_id": "writer"},
    ):
        patched = system.client.patch(path, json={"auto_accept": sent}, headers=headers(SCOPES))
        assert patched.status_code == 200, patched.text
        assert "executor_type" not in system.stored(routine_id)["metadata"]["auto_accept"]
    assert (
        AutoAccept.model_validate(MISMATCHED[0]).model_dump()
        == AutoAccept(default_executor="writer", executors=["writer"], approve_projects=False).model_dump()
    )
