"""Company fixes before 3.2: one section per finding, each with the healthy case next to the refusal."""

import asyncio
import json

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
from tests.unit.os.test_mini_agent_tasks import ScriptedModel, headers

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


# ----------------------------------------------------------------- schemas a strict provider can satisfy


def chat_tool_schemas(agent_os):
    """The parameter schema of each Company Task tool, as it is sent to the model."""
    from agno.os.manager.company_tasks import CompanyTaskTools

    schemas = {}
    for name, function in CompanyTaskTools(agent_os).get_async_functions().items():
        function.process_entrypoint()
        schemas[name] = function.parameters
    return schemas


def shape(schema):
    """A schema without its descriptions."""
    if isinstance(schema, dict):
        return {key: shape(value) for key, value in schema.items() if key != "description"}
    return [shape(item) for item in schema] if isinstance(schema, list) else schema


def accepts_null(schema):
    return schema.get("type") == "null" or any(accepts_null(option) for option in schema.get("anyOf", []))


def test_every_optional_argument_of_the_chat_tools_is_nullable_in_the_schema(system):
    import inspect
    from typing import get_args, get_type_hints

    from agno.os.manager.company_tasks import CompanyTaskTools

    schemas = chat_tool_schemas(system.os)
    tools = CompanyTaskTools(system.os)
    optional = {}
    for name in schemas:
        for method in (getattr(tools, name), getattr(tools, "a" + name)):
            hints = get_type_hints(method)
            for parameter in inspect.signature(method).parameters:
                if parameter.startswith("_agno") or parameter == "self":
                    continue
                if type(None) in get_args(hints[parameter]):
                    optional.setdefault(name, set()).add(parameter)
    assert optional == {
        "approve_company_project": {"updated_at"},
        "accept_company_task": {"executor_type", "executor_id"},
        "review_company_task": {"executor_type", "executor_id"},
        "turn_on_routine_auto_accept": {"default_executor", "kept_policy"},
    }
    for name, parameters in optional.items():
        for parameter in parameters:
            assert accepts_null(schemas[name]["properties"][parameter]), (name, parameter, schemas[name])
    # The sync tools are sent with the same types. Their descriptions are shorter.
    for name, function in tools.get_functions().items():
        function.process_entrypoint()
        assert shape(function.parameters) == shape(schemas[name]), name


def test_the_schemas_accept_a_never_edited_record_and_refuse_what_is_not_a_task(system):
    import jsonschema

    schemas = chat_tool_schemas(system.os)
    task = schemas["accept_company_task"]["properties"]["tasks"]["items"]
    assert set(task["properties"]) == {"title", "task_id", "updated_at"} and task["additionalProperties"] is False
    assert set(task["required"]) == {"title", "task_id", "updated_at"}
    assert accepts_null(task["properties"]["updated_at"])

    never_edited = {
        "approve_company_project": {"project_name": "Cut subscription churn", "project_id": "p1", "updated_at": None},
        "accept_company_task": {
            "tasks": [{"title": "Write a win-back email", "task_id": "t1", "updated_at": None}],
            "executor_type": None,
            "executor_id": None,
        },
        "review_company_task": {
            "task_title": "Write reminder copy",
            "outcome": "send_back",
            "reason": "Six templates",
            "task_id": "t1",
            "reviewed_run_id": "r1",
            "executor_type": None,
            "executor_id": None,
        },
        "turn_on_routine_auto_accept": {
            "routine_name": "intake",
            "product_name": "Docs",
            "default_executor": None,
            "kept_policy": None,
            "routine_id": "r1",
        },
    }
    for name, arguments in never_edited.items():
        jsonschema.validate(arguments, schemas[name])
    for not_a_task in ({}, {"title": "Draft"}, {"title": "Draft", "task_id": "t1", "updated_at": None, "extra": 1}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {**never_edited["accept_company_task"], "tasks": [not_a_task]}, schemas["accept_company_task"]
            )


def decide(system, tool, arguments, session="chat"):
    """One decision through Super Agent: the model calls the tool, the person confirms, the run continues."""
    from agno.run.authorization import authorization_scope
    from tests.unit.os.test_company_decision_tools import ask, person

    paused = ask(system, tool, arguments, session=session)
    assert paused.is_paused and len(paused.requirements) == 1, paused.content
    assert paused.requirements[0].tool_execution.tool_args == arguments
    paused.requirements[0].confirm()
    with authorization_scope(person):
        result = asyncio.run(system.os.manager.acontinue_run(run_response=paused, user_id="alice"))
    assert not result.is_paused, result.content
    return str(result.content)


@pytest.mark.parametrize("version", [0, None], ids=["zero-as-in-F1", "null"])
def test_one_confirmation_approves_a_never_edited_project(system, version):
    # F1: the Project was never edited, and the model sent updated_at 0.
    task = system.proposal()
    project = system.client.post(
        "/company/projects",
        json={"product_id": task["product_id"], "name": "Cut subscription churn"},
        headers=headers(),
    ).json()
    assert project["updated_at"] is None and project["status"] == "proposed"
    arguments = {"project_name": "Cut subscription churn", "project_id": project["id"], "updated_at": version}
    reply = decide(system, "approve_company_project", arguments)
    assert "Approved Project 'Cut subscription churn'" in reply, reply
    assert system.db.get_project(project["id"])["status"] == "active"


def test_a_version_of_zero_does_not_match_a_project_that_was_edited(system):
    task = system.proposal()
    project = system.client.post(
        "/company/projects", json={"product_id": task["product_id"], "name": "Churn"}, headers=headers()
    ).json()
    edited = system.client.patch(f"/company/projects/{project['id']}", json={"outcome": "Less"}, headers=headers())
    assert edited.status_code == 200 and edited.json()["updated_at"] is not None
    reply = decide(
        system, "approve_company_project", {"project_name": "Churn", "project_id": project["id"], "updated_at": 0}
    )
    assert "changed since the person saw it" in reply
    assert system.db.get_project(project["id"])["status"] == "proposed"


def test_one_confirmation_accepts_a_never_edited_task(system):
    task = system.proposal()
    assert task["updated_at"] is None
    arguments = {
        "tasks": [{"title": task["title"], "task_id": task["id"], "updated_at": None}],
        "executor_type": "agent",
        "executor_id": "writer",
    }
    reply = decide(system, "accept_company_task", arguments)
    assert "Accepted 'Notes'" in reply, reply
    stored = system.db.get_task(task["id"])
    assert (stored["status"], stored["executor_id"], stored["accepted_by"]) == ("ready", "writer", "alice")


@pytest.mark.parametrize(
    "sent",
    [",", "", None, "__NONE__", "^null^"],
    ids=["comma-as-in-F2", "empty", "null", "none-placeholder", "null-placeholder"],
)
def test_one_confirmation_sends_a_task_back_when_the_model_names_no_executor(system, sent):
    # F2: the Task has an executor, and the model sent "," for executor_type and executor_id.
    # Two validation runs sent "__NONE__" and "^null^" for the same two arguments.
    task = system.proposal()
    accepted = system.client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    )
    assert accepted.status_code == 200, accepted.text
    system.writer.model.script = []
    started = system.client.post(f"/company/tasks/{task['id']}/runs", headers=headers())
    assert started.status_code == 202, started.text

    async def run():
        job = await system.queue.store.claim_job(system.queue.worker_id, system.queue.config.lock_grace_seconds)
        await system.queue._execute_claimed(job)

    asyncio.run(run())
    review = system.db.get_task(task["id"])
    assert review["status"] == "in_review"
    arguments = {
        "task_title": "Notes",
        "outcome": "send_back",
        "reason": "I want six reusable templates, not one message.",
        "task_id": task["id"],
        "reviewed_run_id": review["job_id"],
        "executor_type": sent,
        "executor_id": sent,
    }
    reply = decide(system, "review_company_task", arguments)
    assert "back to Ready for agent writer" in reply, reply
    stored = system.db.get_task(task["id"])
    assert (stored["status"], stored["executor_type"], stored["executor_id"]) == ("ready", "agent", "writer")


def test_send_back_still_refuses_an_executor_that_is_not_the_tasks_own(system):
    task = system.proposal()
    system.accept(task["id"])
    system.execute(task["id"])
    review = system.db.get_task(task["id"])
    arguments = {
        "task_title": "Notes",
        "outcome": "send_back",
        "reason": "Redo",
        "task_id": task["id"],
        "reviewed_run_id": review["job_id"],
        "executor_type": "agent",
        "executor_id": "writer",
    }
    reply = decide(system, "review_company_task", arguments)
    assert "returns 'Notes' to its executor, agent miniagent" in reply, reply
    assert system.db.get_task(task["id"])["status"] == "in_review"


# ----------------------------------------------------------------- a new executor starts from the brief


class ChainingModel(ScriptedModel):
    """A model whose replies carry a provider response id, and which records what each call was sent."""

    def __init__(self, response_id, calls=()):
        super().__init__(calls)
        self.response_id = response_id
        self.seen = []

    def invoke(self, messages, tools=None, **kwargs):
        self.seen = [
            (message.role, bool(message.from_history), (message.provider_data or {}).get("response_id"))
            for message in messages
        ]
        self.messages = list(messages)
        response = super().invoke(messages, tools=tools, **kwargs)
        response.content = f"Answer from {self.response_id}"
        response.provider_data = {"response_id": self.response_id}
        return response


def move(system, task_id, target, **executor):
    response = system.client.post(
        f"/company/tasks/{task_id}/transitions",
        json={"target": target, "reason": "Decided", **executor},
        headers=headers(),
    )
    assert response.status_code == 200, response.text


def chained_from(messages):
    """The previous_response_id OpenAIResponses would send for these messages."""
    from agno.models.openai import OpenAIResponses

    model = OpenAIResponses(id="gpt-5.6-luna", api_key="test")
    return model.get_request_params(messages=messages).get("previous_response_id")


def test_a_task_given_to_a_second_executor_does_not_carry_the_first_executors_attempts(system):
    # F3: two attempts on a built agent, then the Task is returned to Backlog and accepted for Mini Agent.
    task = system.proposal("Write six reminder templates")
    task_id = task["id"]
    system.writer.add_history_to_context = True
    move(system, task_id, "ready", executor_type="agent", executor_id="writer")
    system.writer.model = ChainingModel("resp_writer_1")
    assert system.execute(task_id)["result"]["content"] == "Answer from resp_writer_1"
    move(system, task_id, "ready", executor_type="agent", executor_id="writer")
    system.writer.model = ChainingModel("resp_writer_2")
    assert system.execute(task_id)["result"]["content"] == "Answer from resp_writer_2"
    # The same executor keeps its own earlier attempt, and its own chain.
    assert ("assistant", True, "resp_writer_1") in system.writer.model.seen
    assert chained_from(system.writer.model.messages) == "resp_writer_1"

    move(system, task_id, "backlog")
    system.accept(task_id)
    mini = ChainingModel("resp_mini_1")
    saved = system.execute(task_id, model=mini)
    assert (saved["executor_id"], saved["session_id"]) == ("miniagent", task["session_id"])
    assert saved["result"]["content"] == "Answer from resp_mini_1"
    # Mini Agent is sent its own instructions and this attempt's brief, and nothing the writer said.
    assert [(role, history) for role, history, _ in mini.seen] == [("system", False), ("user", False)], mini.seen
    assert chained_from(mini.messages) is None

    # Sent back to Mini Agent, the next attempt still carries nothing of the writer's.
    move(system, task_id, "ready", executor_type="agent", executor_id="miniagent")
    again = ChainingModel("resp_mini_2")
    system.execute(task_id, model=again)
    assert not [seen for seen in again.seen if seen[2] and seen[2].startswith("resp_writer")], again.seen
    assert chained_from(again.messages) in (None, "resp_mini_1")


def test_a_task_that_stays_on_one_executor_keeps_its_earlier_attempts_as_history(system):
    task = system.proposal()
    system.accept(task["id"])
    system.execute(task["id"], model=ChainingModel("resp_mini_1"))
    move(system, task["id"], "ready", executor_type="agent", executor_id="miniagent")
    second = ChainingModel("resp_mini_2")
    system.execute(task["id"], model=second)
    assert ("assistant", True, "resp_mini_1") in second.seen, second.seen
    assert chained_from(second.messages) == "resp_mini_1"


# ----------------------------------------------------------------- the acceptance bounds every executor


@pytest.mark.parametrize("accepting_may_run,starting_may_run", [(False, True), (True, False), (True, True)])
def test_a_named_executor_with_run_tools_needs_both_accepting_and_starting_permissions(
    tmp_path, accepting_may_run, starting_may_run
):
    # The Task's executor is an agent that holds run tools and tries to run the writer.
    system = PolicySystem(tmp_path, pausing="agent")
    try:
        system.helper.model = ScriptedModel([("run_agent", {"agent_id": "writer", "message": "Write the notes"})])
        both = [*SCOPES, "agents:helper:run", "agents:helper:read"]
        without = [scope for scope in both if scope != "agents:writer:run"]
        task = system.proposal()
        accepted = system.client.post(
            f"/company/tasks/{task['id']}/transitions",
            json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "helper"},
            headers=headers(both if accepting_may_run else without),
        )
        assert accepted.status_code == 200, accepted.text
        saved = system.execute(task["id"], scopes=both if starting_may_run else without, user="bob")
        allowed = accepting_may_run and starting_may_run
        assert system.writer.model.turns == int(allowed), saved["result"]
        assert [(entry["id"], entry["status"]) for entry in saved["result"]["invoked"]] == [
            ("writer", "COMPLETED" if allowed else "REFUSED")
        ]
        assert saved["accepted_by"] == "alice"
    finally:
        system.db.close()


# ----------------------------------------------------------------- max_open holds through the checks


def test_max_open_is_not_exceeded_by_an_acceptance_that_lands_during_the_checks(open_system):
    system = open_system
    gap_taken = []

    def gap(task, manager):
        # While one proposal is checked, a person accepts the Routine's other proposal.
        if not gap_taken:
            other = next(item for item in proposals if item["id"] != task["id"])
            gap_taken.append((task["id"], other["id"]))
            system.manager.transition_task(
                task_id=other["id"], target="ready", reason="Accepted", executor_type="agent", executor_id="writer"
            )
        return True

    system.os.company.acceptance_checks["gap"] = gap
    policy = AutoAccept(max_open=1, required_checks=["executor_registered", "gap"])
    product_id, routine_id = system.declare(auto_accept=policy)
    project, first = system.proposes(product_id, routine_id, title="First")
    _, second = system.proposes(product_id, routine_id, title="Second")
    proposals = [first, second]
    system.manager.transition_project(project_id=project["id"], target="active", reason="Approved by a person")

    outcomes = system.tick()
    checked, by_person = gap_taken[0]
    # The person's acceptance took the one place. The policy's acceptance is refused where it is written.
    assert system.db.get_task(checked)["status"] == "backlog", outcomes
    assert system.db.get_task(by_person)["status"] in ("ready", "in_progress")
    outcome = system.outcome(outcomes, checked)
    assert outcome["status"] == "skipped" and "1 Tasks open, its limit" in outcome["reason"], outcome
    open_now = [
        task
        for task in system.db.get_tasks(product_id=product_id, limit=100)[0]
        if task["status"] in ("ready", "in_progress", "in_review")
    ]
    assert len(open_now) == 1


def test_max_open_still_lets_a_routine_fill_its_places(open_system):
    product_id, routine_id = open_system.declare(auto_accept=AutoAccept(max_open=2))
    tasks = [open_system.proposes(product_id, routine_id, title=f"Task {n}")[1] for n in range(3)]
    open_system.tick()
    statuses = sorted(open_system.db.get_task(task["id"])["status"] for task in tasks)
    assert statuses == ["backlog", "in_progress", "in_progress"]


# ----------------------------------------------------------------- a Routine is told how it proposes


def test_routine_instructions_name_the_tools_a_routine_proposes_with(system):
    from agno.company.mini_agent import ROUTINE_INSTRUCTIONS
    from agno.company.routines import _RoutineAuthorization
    from agno.run.authorization import authorization_scope

    for name in ("propose_company_project", "intake_product_source", "evidence_links", "evidence_hashes"):
        assert name in ROUTINE_INSTRUCTIONS, name
    assert "propose_company_task is refused" in ROUTINE_INSTRUCTIONS
    # Both tools are held in a Routine run, and the plain Task proposal is the one that is refused there.
    product = system.client.post("/company/products", json={"name": "Clinics"}, headers=headers()).json()
    authority = _RoutineAuthorization(None, routine_id="routine", product_id=product["id"])
    with authorization_scope(lambda: authority):
        tools = {
            name: function for toolkit in system.mini.tools(None) for name, function in toolkit.get_functions().items()
        }
        assert {"propose_company_project", "intake_product_source", "read_product_source"} <= set(tools)
        project = json.loads(tools["propose_company_project"].entrypoint(product_id=product["id"], name="Updates"))
        assert project["status"] == "proposed"
        with pytest.raises(PermissionError, match="intake_product_source"):
            tools["propose_company_task"].entrypoint(
                product_id=product["id"], title="Draft the update", project_id=project["id"]
            )


# ----------------------------------------------------------------- a Routine with no Source says so


@pytest.mark.parametrize("use_async", [False, True])
def test_creating_a_routine_on_a_product_with_no_source_says_a_source_is_needed(system, use_async):
    from agno.tools.company import CompanyTools

    tools = CompanyTools(system.db, registry=system.os.registry)
    tools._agent_os_ref = __import__("weakref").ref(system.os)
    product = system.client.post("/company/products", json={"name": "Clinics"}, headers=headers()).json()
    context = chat(scopes=[*SCOPES, "sources:write"])

    def create(name, **fields):
        arguments = dict(product_id=product["id"], name=name, **fields, _agno_run_context=context)
        if use_async:
            return json.loads(asyncio.run(tools.acreate_product_routine(**arguments)))
        return json.loads(tools.create_product_routine(**arguments))

    # It is created. The reply says it can propose nothing until the Product has a Source.
    weekly = create("weekly", instructions="Each run, propose one task to draft a short update.")
    assert weekly["id"] and system.db.get_schedule(weekly["id"]) is not None
    assert "no Source" in weekly["note"] and "add a Source" in weekly["note"], weekly
    assert "note" in create("intake", template="intake")
    # A Routine that proposes no Task from a Source carries no note.
    assert "note" not in create("refresh", template="refresh")

    added = system.client.post(
        "/company/sources",
        json={"product_id": product["id"], "type": "website", "reference": "https://example.com/changes"},
        headers=headers([*SCOPES, "sources:write"]),
    )
    assert added.status_code == 201, added.text
    assert "note" not in create("second", instructions="Read the Source and propose work.")


# ----------------------------------------------------------------- each Task has its own folder and limit


def task_files(system):
    """Two Tasks in two Products, and the tree tools Super Agent holds."""
    from tests.unit.os.test_company_file_tree import records, tree

    return records(system), tree(system.os)


def tree_call(*args, **kwargs):
    from tests.unit.os.test_company_file_tree import call

    return call(*args, **kwargs)


@pytest.mark.parametrize("use_async", [False, True])
def test_one_task_filling_its_folder_does_not_refuse_another_tasks_write(system, monkeypatch, use_async):
    import agno.company.files as company_files
    from agno.fs.errors import FileSystemError

    # The limit, small enough to reach in a test, under the name it has before and after the change.
    monkeypatch.setattr(company_files, "TASKS_NAMESPACE_BYTES", 1500, raising=False)
    monkeypatch.setattr(company_files, "TASK_FOLDER_BYTES", 1500, raising=False)
    ids, files = task_files(system)
    first, second = f"tasks/{ids['task']}", f"tasks/{ids['stray']}"
    tree_call(files, "write_company_file", None, use_async, path=f"{first}/report.md", content="x" * 1000)
    with pytest.raises(FileSystemError):
        tree_call(files, "write_company_file", None, use_async, path=f"{first}/more.md", content="x" * 1000)
    written = tree_call(files, "write_company_file", None, use_async, path=f"{second}/report.md", content="y" * 1000)
    assert written["version"] == 1
    read = tree_call(files, "read_company_file", None, use_async, path=f"{second}/report.md")
    assert read["content"] == "y" * 1000


@pytest.mark.parametrize("use_async", [False, True])
def test_task_files_stored_before_each_task_had_its_own_folder_stay_readable(system, use_async):
    from agno.fs import FileSystem

    ids, files = task_files(system)
    folder = f"tasks/{ids['task']}"
    # A file as it was stored when every Task shared one namespace.
    shared = FileSystem(system.db, namespace="company/tasks", user_scoped=False)
    shared.write(f"{ids['task']}/given.md", "Material from the older layout")
    shared.write(f"{ids['task']}/data/rows.csv", "a,b")

    read = tree_call(files, "read_company_file", None, use_async, path=f"{folder}/given.md")
    assert read["content"] == "Material from the older layout" and read["version"] == 1
    listed = tree_call(files, "list_company_files", None, use_async, folder=folder)
    assert sorted(row["path"] for row in listed["files"]) == [f"{folder}/data/rows.csv", f"{folder}/given.md"]
    for searched in (folder, "tasks", None):
        found = tree_call(files, "search_company_files", None, use_async, query="older layout", folder=searched)
        assert [match["path"] for match in found["matches"]] == [f"{folder}/given.md"], searched

    # A new file sits next to it, and the older file is replaced at the version that was read.
    tree_call(files, "write_company_file", None, use_async, path=f"{folder}/report.md", content="The report")
    replaced = tree_call(
        files, "write_company_file", None, use_async, path=f"{folder}/given.md", content="Revised", expected_version=1
    )
    assert replaced["path"] == f"{folder}/given.md"
    assert tree_call(files, "read_company_file", None, use_async, path=f"{folder}/given.md")["content"] == "Revised"
    listed = tree_call(files, "list_company_files", None, use_async, folder=folder)
    assert sorted(row["path"] for row in listed["files"]) == [
        f"{folder}/data/rows.csv",
        f"{folder}/given.md",
        f"{folder}/report.md",
    ]
    # The older file itself is not removed or rewritten.
    assert shared.read(f"{ids['task']}/given.md") == "Material from the older layout"


@pytest.mark.parametrize("use_async", [False, True])
def test_listing_tasks_names_each_tasks_folder(system, use_async):
    ids, files = task_files(system)
    tree_call(files, "write_company_file", None, use_async, path=f"tasks/{ids['task']}/report.md", content="Report")
    listed = tree_call(files, "list_company_files", None, use_async, folder="tasks")
    folders = {row["folder"]: row for row in listed["folders"]}
    assert {f"tasks/{ids['task']}/", f"tasks/{ids['stray']}/"} <= set(folders) and listed["total"] == len(folders)
    assert folders[f"tasks/{ids['task']}/"]["title"] == "Notes"
    again = tree_call(files, "list_company_files", None, use_async, folder=f"tasks/{ids['task']}/")
    assert [row["path"] for row in again["files"]] == [f"tasks/{ids['task']}/report.md"]


# ----------------------------------------------------------------- a Task's input stops reading at the budget


def test_a_tasks_input_reads_no_page_after_the_budget_is_spent(system, monkeypatch):
    from agno.company.execution import _task_input
    from agno.company.files import ALWAYS_LOADED_PAGE_CHARS, ALWAYS_LOADED_TOTAL_CHARS
    from agno.company.manager import CompanyManager

    task = system.proposal()
    manager = CompanyManager(system.db, system.os.registry)
    for index in range(12):
        manager.write_wiki(
            product_id=None, path=f"page-{index:02d}.md", content="p" * ALWAYS_LOADED_PAGE_CHARS, expected_version=0
        )
    read = []
    original = CompanyManager.read_wiki

    def counted(self, product_id, path):
        read.append(path)
        return original(self, product_id, path)

    monkeypatch.setattr(CompanyManager, "read_wiki", counted)
    pages = json.loads(asyncio.run(_task_input(manager, task)))["wiki"]
    loaded = [page for page in pages if "content" in page]
    named = [page for page in pages if "content" not in page]
    assert sum(len(page["content"]) for page in loaded) <= ALWAYS_LOADED_TOTAL_CHARS
    # Every page is still named with the file to read. Only the pages that fit, and the first that did not, were read.
    assert len(pages) == 2 + len(manager.list_wiki(None, limit=100)[0])
    assert named and all("Not loaded" in page["note"] and page["file"] in page["note"] for page in named)
    assert len(read) == len(loaded) + 1, (len(read), len(loaded), len(named))


# ----------------------------------------------------------------- a search opens a bounded number of folders


@pytest.mark.parametrize("use_async", [False, True])
def test_a_whole_tree_search_opens_a_bounded_number_of_products_and_says_so(system, monkeypatch, use_async):
    import agno.company.files as company_files
    from agno.company.manager import AsyncCompanyManager, CompanyManager

    monkeypatch.setattr(company_files, "SEARCH_FOLDERS", 3, raising=False)
    manager = CompanyManager(system.db, system.os.registry)
    # Each Product is created a second after the one before, so the newest three are the last three.
    clock = iter(range(1_794_000_000, 1_794_000_100))
    with monkeypatch.context() as patch:
        patch.setattr("agno.company.manager.time.time", lambda: next(clock))
        created = [manager.create(name=f"Product {index}")["id"] for index in range(6)]
    manager.write_wiki(product_id=created[-1], path="needle.md", content="recentneedle", expected_version=0)
    manager.write_wiki(product_id=created[0], path="needle.md", content="oldneedle", expected_version=0)
    from tests.unit.os.test_company_file_tree import tree

    files = tree(system.os)
    opened = []
    for cls in (CompanyManager, AsyncCompanyManager):
        original = cls.get_wiki

        def counted(self, product_id=None, _original=original):
            opened.append(product_id)
            return _original(self, product_id)

        monkeypatch.setattr(cls, "get_wiki", counted)

    for folder in (None, "products"):
        opened.clear()
        found = tree_call(files, "search_company_files", None, use_async, query="oldneedle", folder=folder)
        assert len([product_id for product_id in opened if product_id is not None]) == 3, opened
        # The Product it did not open is not searched, and the reply says how many were and what to do.
        assert found["matches"] == [] and "3 of 6 Products" in found["note"], found
        assert "products/<product-id>" in found["note"]
        recent = tree_call(files, "search_company_files", None, use_async, query="recentneedle", folder=folder)
        assert [match["path"] for match in recent["matches"]] == [f"products/{created[-1]}/needle.md"]
    # A named Product is always searched.
    named = tree_call(
        files, "search_company_files", None, use_async, query="oldneedle", folder=f"products/{created[0]}"
    )
    assert [match["path"] for match in named["matches"]] == [f"products/{created[0]}/needle.md"]
    assert "note" not in named


def test_a_search_within_the_bound_carries_no_note(system):
    ids, files = task_files(system)
    found = tree_call(files, "search_company_files", query="nothing matches this")
    assert found["matches"] == [] and "note" not in found


# ----------------------------------------------------------------- Mini Agent's model and Super Agent's tools


def deployment(tmp_path, **options):
    from agno.db.sqlite import SqliteDb
    from agno.os import AgentOS

    db = SqliteDb(db_file=str(tmp_path / "models.db"))
    return AgentOS(id="models", db=db, telemetry=False, **options), db


def test_mini_agent_uses_super_agents_model_when_company_config_names_none(tmp_path):
    from agno.os import CompanyConfig, OSManager
    from agno.registry import Registry

    super_model, registry_model = ScriptedModel(), ScriptedModel()
    agent_os, db = deployment(tmp_path, manager=OSManager(model=super_model), company=CompanyConfig())
    try:
        assert agent_os._mini_agent is not None and agent_os._mini_agent.model is super_model
    finally:
        db.close()
    # Super Agent's model comes before the registry's first model.
    agent_os, db = deployment(
        tmp_path / "second",
        manager=OSManager(model=super_model),
        company=CompanyConfig(),
        registry=Registry(models=[registry_model]),
    )
    try:
        assert agent_os._mini_agent.model is super_model
    finally:
        db.close()


def test_company_config_still_names_mini_agents_model_and_the_registry_still_serves_without_super_agent(tmp_path):
    from agno.os import CompanyConfig, OSManager
    from agno.registry import Registry

    super_model, company_model, registry_model = ScriptedModel(), ScriptedModel(), ScriptedModel()
    agent_os, db = deployment(
        tmp_path, manager=OSManager(model=super_model), company=CompanyConfig(model=company_model)
    )
    try:
        assert agent_os._mini_agent.model is company_model
    finally:
        db.close()
    agent_os, db = deployment(tmp_path / "second", company=CompanyConfig(), registry=Registry(models=[registry_model]))
    try:
        assert agent_os._mini_agent.model is registry_model
    finally:
        db.close()


def super_agent_tools(agent_os):
    names = []
    for toolkit in agent_os.manager.tools:
        functions = getattr(toolkit, "functions", None) or {}
        names.extend(functions)
    return names


def test_super_agent_does_not_hold_the_decision_log_tools(system):
    from agno.tools.company import CompanyTools

    held = super_agent_tools(system.os)
    assert "log_company_decision" not in held and "search_company_decisions" not in held
    # The tools stay on CompanyTools for custom agents, and the API stays.
    custom = CompanyTools(system.db).functions
    assert {"log_company_decision", "search_company_decisions"} <= set(custom)
    listed = system.client.get("/company/decisions", headers=headers([*SCOPES, "decisions:read"]))
    assert listed.status_code == 200, listed.text


# ----------------------------------------------------------------- a Routine cut off at its limit is not a success


def routine_run(system, calls):
    """One Routine run on Mini Agent, and the schedule status the scheduler records for it."""
    from agno.company.routines import _RoutineAuthorization
    from agno.run.authorization import authorization_scope
    from agno.scheduler.executor import terminal_run_status

    product = system.client.post("/company/products", json={"name": "Clinics"}, headers=headers()).json()
    system.mini.model = ScriptedModel([("list_company_projects", {"product_id": product["id"]})] * calls)
    authority = _RoutineAuthorization(None, routine_id="routine", product_id=product["id"])
    with authorization_scope(lambda: authority):
        output = asyncio.run(system.mini.arun("Operate only on this Product.", session_id="routine-run"))
    return output, terminal_run_status(output.to_dict(), company_routine=True)


def test_a_routine_cut_off_at_the_tool_call_limit_is_recorded_as_incomplete(open_system):
    limit = open_system.mini.tool_call_limit
    output, recorded = routine_run(open_system, limit + 5)
    executed = [tool for tool in output.tools or [] if not tool.tool_call_error]
    assert len(executed) == limit
    status, error = recorded
    assert status == "failed", (output.status, recorded)
    assert "incomplete" in error and f"limit of {limit} tool calls" in error, error
    assert "list_company_projects" in error


def test_a_routine_that_stays_within_the_tool_call_limit_is_a_success(open_system):
    limit = open_system.mini.tool_call_limit
    output, recorded = routine_run(open_system, limit)
    assert recorded == ("success", None), (output.status, recorded)


# ----------------------------------------------------------------- a scheduled run is not a person


def fire_owned_schedule(system, calls, message="Do the morning work"):
    """Create an ordinary schedule on Super Agent as alice, through the API, and fire it with the real executor."""
    import httpx

    from agno.db.schemas.scheduler import Schedule
    from agno.registry._reserved import MANAGER_TEAM_ID
    from agno.scheduler.executor import ScheduleExecutor

    scopes = [*SCOPES, f"teams:{MANAGER_TEAM_ID}:run", f"teams:{MANAGER_TEAM_ID}:read", "schedules:read"]
    created = system.client.post(
        "/schedules",
        json={
            "name": "morning",
            "cron_expr": "0 9 * * 1",
            "endpoint": f"/teams/{MANAGER_TEAM_ID}/runs",
            "payload": {"message": message},
        },
        headers=headers(scopes),
    )
    assert created.status_code in (200, 201), created.text
    row = system.db.get_schedule(created.json()["id"])
    assert row["user_id"] == "alice" and row["payload"][AUTHORIZATION_KEY]["context"]["principal_id"] == "alice"
    system.os.manager.model = ScriptedModel(calls)

    async def fire():
        executor = ScheduleExecutor(
            base_url="http://test",
            internal_service_token=system.os._internal_service_token,
            poll_interval=0.01,
            timeout=30,
        )
        executor._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=system.app), base_url="http://test")
        try:
            call = asyncio.create_task(executor._call_endpoint(Schedule.from_dict(row)))
            # The schedule submits a background run. Run it as the queue worker does.
            job = None
            for _ in range(500):
                job = await system.queue.store.claim_job(system.queue.worker_id, system.queue.config.lock_grace_seconds)
                if job is not None or call.done():
                    break
                await asyncio.sleep(0.01)
            if job is not None:
                await system.queue._execute_claimed(job)
            return await asyncio.wait_for(call, 30)
        finally:
            await executor.close()

    return asyncio.run(fire())


def test_a_scheduled_run_on_super_agent_cannot_create_products_or_routines(system):
    before = system.db.get_products(limit=100)[1]
    result = fire_owned_schedule(
        system,
        [
            ("create_company_product", {"name": "Made with nobody present"}),
            ("update_company_details", {"name": "Renamed with nobody present"}),
        ],
    )
    assert result["status"] in ("success", "failed"), result
    content = json.dumps(result.get("output"))
    assert content.count("scheduled run") >= 2, result
    assert system.db.get_products(limit=100)[1] == before
    details = system.client.get("/company/details", headers=headers([*SCOPES, "company:read"]))
    assert details.status_code == 200 and details.json()["name"] != "Renamed with nobody present", details.text


def test_a_scheduled_run_on_super_agent_still_reads_and_proposes(system):
    task = system.proposal()
    result = fire_owned_schedule(
        system,
        [
            ("list_company_products", {}),
            (
                "propose_company_task",
                {"product_id": task["product_id"], "title": "Follow up", "project_id": task["project_id"]},
            ),
        ],
    )
    assert result["status"] == "success", result
    assert system.db.get_tasks(product_id=task["product_id"], limit=100)[1] == 2


def test_the_mark_of_a_scheduled_run_survives_a_snapshot_and_a_person_carries_none(system):
    from agno.os.authz.run_context import restore_authorization
    from agno.tools.company import _require_human_creation

    person = chat()
    _require_human_creation(person)
    assert "scheduled" not in person.authorization.snapshot()
    restored = restore_authorization(system.app, {**person.authorization.snapshot(), "scheduled": True})
    again = restore_authorization(system.app, restored.snapshot())
    for authority in (restored, again):
        context = chat()
        context.authorization = authority
        with pytest.raises(PermissionError, match="scheduled run"):
            _require_human_creation(context)


# ----------------------------------------------------------------- a failed Task is retried from chat


def start_from_chat(system, task_id, context=None):
    from agno.os.manager.company_tasks import CompanyTaskTools

    tools = CompanyTaskTools(system.os)
    return asyncio.run(tools.astart_company_task(task_id, _agno_run_context=context or chat()))


def test_a_person_retries_a_task_whose_last_attempt_failed_from_chat(system):
    from agno.db.schemas.tasks import task_run_id
    from tests.unit.os.test_mini_agent_tasks import FailingModel

    task = system.proposal()
    system.accept(task["id"])
    failed = system.execute(task["id"], model=FailingModel())
    assert failed["status"] == "in_progress" and failed["result"]["status"] == "ERROR", failed["result"]

    reply = start_from_chat(system, task["id"])
    assert reply.startswith("Queued 'Notes'") and task_run_id(task["id"], 2) in reply, reply
    retried = system.db.get_task(task["id"])
    assert retried["job_id"] == task_run_id(task["id"], 2) and retried["result"] is None
    # The retry runs like any attempt and reaches review.
    system.mini.model = ScriptedModel()

    async def run():
        job = await system.queue.store.claim_job(system.queue.worker_id, system.queue.config.lock_grace_seconds)
        await system.queue._execute_claimed(job)

    asyncio.run(run())
    assert system.db.get_task(task["id"])["status"] == "in_review"


def test_a_retry_from_chat_passes_the_run_routes_checks(system):
    from tests.unit.os.test_mini_agent_tasks import FailingModel

    task = system.proposal()
    system.accept(task["id"])
    system.execute(task["id"], model=FailingModel())
    before = system.db.get_task(task["id"])
    # A person who may not run the executor cannot retry it.
    without = [scope for scope in SCOPES if not scope.startswith("agents:")]
    refused = start_from_chat(system, task["id"], chat(scopes=without, user="bob"))
    assert refused.startswith("Not started"), refused
    assert system.db.get_task(task["id"]) == before


def test_a_task_that_is_running_or_finished_is_still_not_started_from_chat(system):
    done = system.proposal()
    system.accept(done["id"])
    system.execute(done["id"])
    assert "waiting for review" in start_from_chat(system, done["id"])

    task = system.proposal()
    system.accept(task["id"])
    started = system.client.post(f"/company/tasks/{task['id']}/runs", headers=headers())
    assert started.status_code == 202
    # Its attempt is queued: starting again joins that attempt and queues nothing new.
    running = start_from_chat(system, task["id"])
    assert "run " + started.json()["run_id"] in running, running


# ----------------------------------------------------------------- created_at as the version of a never-edited record


def test_one_confirmation_accepts_a_never_edited_task_named_by_its_created_at(system):
    # F8: on another model the call carries the Task's created_at as updated_at, for a Task never edited.
    task = system.proposal()
    assert task["updated_at"] is None and task["created_at"]
    arguments = {
        "tasks": [{"title": task["title"], "task_id": task["id"], "updated_at": task["created_at"]}],
        "executor_type": "agent",
        "executor_id": "miniagent",
    }
    reply = decide(system, "accept_company_task", arguments)
    assert "Accepted 'Notes'" in reply, reply
    assert system.db.get_task(task["id"])["status"] == "ready"

    project = system.client.post(
        "/company/projects", json={"product_id": task["product_id"], "name": "Sign-ups"}, headers=headers()
    ).json()
    approved = decide(
        system,
        "approve_company_project",
        {"project_name": "Sign-ups", "project_id": project["id"], "updated_at": project["created_at"]},
        session="second-chat",
    )
    assert "Approved Project 'Sign-ups'" in approved, approved


def test_created_at_does_not_name_a_record_that_was_edited_later(system, monkeypatch):
    task = system.proposal()
    # The Task is edited a minute after it was created, so its version is no longer its created_at.
    import time

    later = task["created_at"] + 60
    with monkeypatch.context() as patch:
        patch.setattr(time, "time", lambda: later)
        edited = system.db.update_task(task["id"], brief="Rewritten after the person saw it")
    assert edited["updated_at"] == later
    arguments = {
        "tasks": [{"title": task["title"], "task_id": task["id"], "updated_at": task["created_at"]}],
        "executor_type": "agent",
        "executor_id": "miniagent",
    }
    reply = decide(system, "accept_company_task", arguments)
    assert "changed since the person saw it" in reply, reply
    assert system.db.get_task(task["id"])["status"] == "backlog"


# ----------------------------------------------------------------- a placeholder for nothing names nothing


@pytest.mark.parametrize(
    "name,executor,kept,runs_on",
    [
        ("docs.intake", ";", ";", "miniagent"),
        ("intake", "[null]", "[null]", "miniagent"),
        ("intake", "__omit_placeholder__", "__omit_placeholder__", "miniagent"),
        ("intake", "writer", ".", "writer"),
    ],
    ids=["semicolon", "null-in-brackets", "omit-placeholder", "full-stop"],
)
def test_one_confirmation_turns_auto_accept_on_when_the_model_fills_an_empty_argument(
    system, name, executor, kept, runs_on
):
    # The arguments of four validation runs. The Routine has no policy, so there is none to keep.
    _, routine_id = system.declare(auto_accept=False)
    arguments = {
        "routine_name": name,
        "product_name": "Docs",
        "default_executor": executor,
        "kept_policy": kept,
        "routine_id": routine_id,
    }
    reply = decide(system, "turn_on_routine_auto_accept", arguments)
    assert "Auto-accept is on for Routine 'intake'" in reply and f"run on {runs_on}," in reply, reply
    assert system.stored(routine_id)["metadata"]["auto_accept"]["default_executor"] == runs_on


def test_text_that_is_not_the_stored_policy_is_still_not_confirmed_as_kept(system):
    # One validation run sent this for a Routine with no policy. The person would confirm a policy that
    # does not exist, so nothing is turned on.
    _, routine_id = system.declare(auto_accept=False)
    arguments = {
        "routine_name": "intake",
        "product_name": "Docs",
        "default_executor": "writer",
        "kept_policy": "); DROP TABLE company_tasks; --",
        "routine_id": routine_id,
    }
    reply = decide(system, "turn_on_routine_auto_accept", arguments)
    assert "has no policy to keep" in reply, reply
    assert system.stored(routine_id)["metadata"]["auto_accept"] is False


def test_a_placeholder_is_not_an_executor_a_person_accepts_a_task_on(system):
    task = system.proposal()
    arguments = {
        "tasks": [{"title": task["title"], "task_id": task["id"], "updated_at": None}],
        "executor_type": "__NONE__",
        "executor_id": "__NONE__",
    }
    reply = decide(system, "accept_company_task", arguments)
    assert "names no executor" in reply, reply
    assert system.db.get_task(task["id"])["status"] == "backlog"


# ----------------------------------------------------------------- notes/ is shared, and a private fact is not a note


def super_agent_prompt(tmp_path, company=True, **manager_options):
    from agno.os import CompanyConfig, OSManager

    manager = OSManager(model=ScriptedModel(), **manager_options)
    agent_os, db = deployment(tmp_path, manager=manager, **({"company": CompanyConfig()} if company else {}))
    try:
        return " ".join("\n".join(agent_os.manager.instructions()).split())
    finally:
        db.close()


SHARED = "notes/ is shared with everyone who uses this AgentOS"


@pytest.mark.parametrize("company", [True, False])
def test_super_agent_with_no_personal_memory_is_told_it_has_no_private_place(tmp_path, company):
    prompt = super_agent_prompt(tmp_path, company=company)
    assert SHARED in prompt, prompt
    assert "You have no private place" in prompt and "write nothing" in prompt
    assert "your own notes" not in prompt and "your own folder" not in prompt


@pytest.mark.parametrize("company", [True, False])
@pytest.mark.parametrize("stores", [None, {"user_memory": True}, {"user_profile": True}])
def test_super_agent_with_personal_memory_is_told_a_private_fact_goes_there(tmp_path, company, stores):
    from agno.learn import LearningMachine

    learning = True if stores is None else LearningMachine(**stores)
    prompt = super_agent_prompt(tmp_path, company=company, learning=learning)
    assert SHARED in prompt, prompt
    assert "your memory of that person" in prompt and "no private place" not in prompt


def test_a_learning_machine_that_keeps_nothing_about_a_person_is_not_a_private_place(tmp_path):
    from agno.learn import LearningMachine

    prompt = super_agent_prompt(tmp_path, learning=LearningMachine(session_context=True))
    assert "You have no private place" in prompt and "your memory of that person" not in prompt


def test_the_file_tools_say_that_every_file_is_shared():
    from agno.tools.company_files import CompanyFileTools

    for name in ("write_company_file", "awrite_company_file"):
        described = " ".join(getattr(CompanyFileTools, name).__doc__.split())
        assert "shared with everyone who uses this AgentOS" in described, described
        assert "private" in described
    for name in ("list_company_files", "alist_company_files"):
        described = " ".join(getattr(CompanyFileTools, name).__doc__.split())
        assert "own notes" not in described and "shared with everyone" in described, described


# ----------------------------------------------------------------- what Super Agent says about Company work


@pytest.mark.parametrize(
    "told",
    [
        # Recorded work and a list of waiting work both say how a person accepts it.
        "say a person accepts it by asking here or in the Company pages",
        # A fact or a decision said in passing is not a page to save.
        "Save a page only when asked to",
        "said in passing is not a request",
        # A Ready Task is not blocked by who runs it.
        "A Ready Task is not blocked by its executor",
        # A Routine runs on Mini Agent or a named component, and never on Super Agent.
        "run by Mini Agent or a named component, never by you",
    ],
)
def test_super_agent_is_told_how_to_speak_about_company_work(tmp_path, told):
    assert told in super_agent_prompt(tmp_path)


def test_the_page_save_tool_is_for_a_page_the_person_asked_to_save():
    from agno.tools.company_files import CompanyFileTools

    for name in ("save_company_page", "asave_company_page"):
        described = " ".join(getattr(CompanyFileTools, name).__doc__.split())
        assert "only when the person asked" in described and "said in passing" in described, described
