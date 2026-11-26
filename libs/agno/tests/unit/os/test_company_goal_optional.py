"""A Goal is optional on a Project and a Task, and every company has one Default Project.

A Task with no Project goes into the Default Project. That Project has no Goal, is always active
and never finishes, so each test of a refusal sits next to the case that still works.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from agno.company import AsyncCompanyManager, CompanyManager
from agno.company.bootstrap import _start_company
from agno.company.execution import _ExecutorAuthorization, _task_input
from agno.company.routines import _require_routine_goal, _RoutineAuthorization
from agno.db.schemas.projects import DEFAULT_PROJECT_ID
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os.manager.company_tasks import CompanyTaskTools
from agno.os.manager.prompts import COMPANY_INSTRUCTIONS
from agno.run.authorization import authorization_scope
from tests.unit.os.test_company_policy_path import SCOPES, PolicySystem, chat, company_tools, receipts
from tests.unit.os.test_mini_agent_tasks import headers

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

EDIT = "The Default Project cannot be renamed or edited"
TRANSITION = "The Default Project is always active and cannot be approved, completed or cancelled"
ARCHIVE = "The Default Project cannot be archived or deleted"


@pytest.fixture
def system(tmp_path):
    """A deployment with authorization on."""
    value = PolicySystem(tmp_path)
    yield value
    value.db.close()


@pytest.fixture
def open_system(tmp_path):
    """A deployment with authorization off, where a declared auto_accept acts."""
    value = PolicySystem(tmp_path, authorization=False)
    yield value
    value.db.close()


def listed(system, path, **params):
    response = system.client.get(path, params=params, headers=headers())
    assert response.status_code == 200, response.text
    return response.json()["data"]


def post(system, path, body, status=201):
    response = system.client.post(path, json=body, headers=headers())
    assert response.status_code == status, response.text
    return response.json()


# ------------------------------------------------------------------------- the Default Project exists


def test_starting_company_stores_one_default_project(system):
    assert asyncio.run(_start_company(system.os)) is True
    assert asyncio.run(_start_company(system.os)) is True

    projects = listed(system, "/company/projects")
    assert [(p["id"], p["name"], p["status"], p["goal_id"], p["is_default"]) for p in projects] == [
        (DEFAULT_PROJECT_ID, "Default", "active", None, True)
    ]
    shown = system.client.get(f"/company/projects/{DEFAULT_PROJECT_ID}", headers=headers()).json()
    assert shown["is_default"] is True and shown["transitions"] == []


def test_two_processes_starting_at_once_store_one_default_project(tmp_path):
    path = str(tmp_path / "company.db")
    first, second = SqliteDb(db_file=path), SqliteDb(db_file=path)
    # Each process finds the tables there: this test is about the row, not about creating a table.
    for db in (first, second):
        for kind in ("goals", "projects", "tasks"):
            db._get_table(table_type=kind, create_table_if_not_found=True)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            stored = list(pool.map(lambda db: CompanyManager(db).default_project(), [first, second] * 4))
        assert {project["id"] for project in stored} == {DEFAULT_PROJECT_ID}
        assert len({project["created_at"] for project in stored}) == 1
        rows, total = CompanyManager(first).list_projects()
        assert total == 1 and rows[0]["is_default"] is True
    finally:
        first.close()
        second.close()


async def test_the_async_manager_stores_and_uses_the_default_project(tmp_path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "company.db"))
    manager = AsyncCompanyManager(db)
    try:
        task = await manager.create_task(title="Fix the typo on the pricing page")
        project = await manager.create_project(name="Reach 50 customers by March")
        assert (task["project_id"], task["goal_id"], project["goal_id"]) == (DEFAULT_PROJECT_ID, None, None)
        default = await manager.default_project()
        assert default["is_default"] is True and default["status"] == "active"
        with pytest.raises(ValueError, match=EDIT):
            await manager.update_project(DEFAULT_PROJECT_ID, name="Inbox")
        with pytest.raises(ValueError, match=TRANSITION):
            await manager.transition_project(project_id=DEFAULT_PROJECT_ID, target="done", reason="All done")
        with pytest.raises(ValueError, match=ARCHIVE):
            await manager.delete_project(DEFAULT_PROJECT_ID)
        assert (await manager.list_tasks(has_goal=False))[1] == 1 and (await manager.list_tasks(has_goal=True))[1] == 0
        assert (await manager.list_projects(has_goal=False))[1] == 2
        rows, total = await manager.list_projects()
        assert {row["id"]: row["is_default"] for row in rows} == {DEFAULT_PROJECT_ID: True, project["id"]: False}
    finally:
        await db.close()


# ------------------------------------------------------------------- the Default Project never changes


def test_the_manager_refuses_every_change_to_the_default_project(system):
    manager = system.manager
    manager.default_project()

    with pytest.raises(ValueError, match=EDIT):
        manager.update_project(DEFAULT_PROJECT_ID, name="Inbox")
    for target in ("done", "cancelled", "active", "proposed"):
        with pytest.raises(ValueError, match=TRANSITION):
            manager.transition_project(project_id=DEFAULT_PROJECT_ID, target=target, reason="Asked")
    with pytest.raises(ValueError, match=ARCHIVE):
        manager.delete_project(DEFAULT_PROJECT_ID)
    # The store refuses too, for a caller that does not go through the manager.
    with pytest.raises(ValueError, match=TRANSITION):
        system.db.transition_project(DEFAULT_PROJECT_ID, "done", "Asked")
    with pytest.raises(ValueError, match=ARCHIVE):
        system.db.delete_project(DEFAULT_PROJECT_ID)

    default = manager.get_project(DEFAULT_PROJECT_ID)
    assert (default["name"], default["status"], default["deleted_at"]) == ("Default", "active", None)
    # Another Project still takes each of these.
    other = manager.create_project(name="Launch")
    assert manager.update_project(other["id"], name="Launch week")["name"] == "Launch week"
    assert manager.transition_project(project_id=other["id"], target="active", reason="Approved")["status"] == "active"
    assert manager.delete_project(other["id"]) is True


def test_the_api_refuses_every_change_to_the_default_project(system):
    system.manager.default_project()
    path = f"/company/projects/{DEFAULT_PROJECT_ID}"

    renamed = system.client.patch(path, json={"name": "Inbox"}, headers=headers())
    assert renamed.status_code == 422 and EDIT in renamed.json()["detail"]
    for target in ("done", "cancelled"):
        moved = system.client.post(path + "/transitions", json={"target": target, "reason": "Asked"}, headers=headers())
        assert moved.status_code == 409 and TRANSITION in moved.json()["detail"]
    may_delete = headers([*SCOPES, "projects:delete"])
    deleted = system.client.delete(path, headers=may_delete)
    assert deleted.status_code == 409 and ARCHIVE in deleted.json()["detail"]
    restored = system.client.post(path + "/restore", headers=may_delete)
    assert restored.status_code == 409 and restored.json()["detail"] == "Project is not archived"

    assert system.client.get(path, headers=headers()).json()["status"] == "active"


@pytest.mark.parametrize("use_async", [False, True])
def test_the_tools_refuse_every_change_to_the_default_project(system, use_async):
    system.manager.default_project()
    tools = company_tools(system)
    edit = tools.aedit_company_project if use_async else tools.edit_company_project
    with pytest.raises(ValueError, match=EDIT):
        call = edit(DEFAULT_PROJECT_ID, "Inbox", "Everything", _agno_run_context=chat())
        if use_async:
            asyncio.run(call)
    approve = CompanyTaskTools(system.os).aapprove_company_project("Default", DEFAULT_PROJECT_ID, None, chat())
    assert "only a proposed Project can be approved" in asyncio.run(approve)
    assert system.manager.get_project(DEFAULT_PROJECT_ID)["status"] == "active"


def test_a_routine_cannot_change_the_default_project(open_system):
    goal_id, routine_id = open_system.declare(auto_accept=False)
    open_system.manager.default_project()
    authority = _RoutineAuthorization(None, routine_id=routine_id, goal_id=goal_id)

    with authorization_scope(lambda: authority):
        with pytest.raises(ValueError, match=EDIT):
            open_system.manager.update_project(DEFAULT_PROJECT_ID, name="Inbox")
        with pytest.raises(ValueError, match=TRANSITION):
            open_system.manager.transition_project(project_id=DEFAULT_PROJECT_ID, target="done", reason="Refresh")
        with pytest.raises(ValueError, match=ARCHIVE):
            open_system.manager.delete_project(DEFAULT_PROJECT_ID)


# --------------------------------------------------------------------- a Project and a Task with no Goal


def test_the_manager_takes_a_project_and_a_task_with_no_goal(system):
    manager = system.manager
    goal = manager.create(name="Developer docs")

    loose = manager.create_task(title="Fix the typo on the pricing page")
    assert (loose["project_id"], loose["goal_id"], loose["status"]) == (DEFAULT_PROJECT_ID, None, "backlog")
    project = manager.create_project(name="Reach 50 customers by March")
    assert (project["goal_id"], project["status"]) == (None, "proposed")
    # A Task in a Project carries the Project's Goal: none here, and the Goal's own below.
    in_project = manager.create_task(title="Count paying customers", project_id=project["id"])
    assert in_project["goal_id"] is None
    under_goal = manager.create_project(goal_id=goal["id"], name="3.3 migration guide")
    inherited = manager.create_task(title="Write the breaking changes", project_id=under_goal["id"])
    assert inherited["goal_id"] == goal["id"]
    # The Default Project holds a Task of any Goal.
    tagged = manager.create_task(title="A stray finding", goal_id=goal["id"])
    assert (tagged["project_id"], tagged["goal_id"]) == (DEFAULT_PROJECT_ID, goal["id"])

    with pytest.raises(ValueError, match="Task and Project must belong to the same Goal"):
        manager.create_task(title="Mismatched", goal_id=goal["id"], project_id=project["id"])
    with pytest.raises(LookupError, match="Goal not found"):
        manager.create_task(title="No such Goal", goal_id="missing")
    with pytest.raises(LookupError, match="Goal not found"):
        manager.create_project(goal_id="missing", name="No such Goal")
    with pytest.raises(LookupError, match="Project not found"):
        manager.create_task(title="No such Project", project_id="missing")

    counts = {row["id"]: row["counts"]["tasks"]["backlog"] for row in manager.list_projects()[0]}
    assert counts == {DEFAULT_PROJECT_ID: 2, project["id"]: 1, under_goal["id"]: 1}
    assert manager.list_tasks()[1] == 4
    assert manager.list_tasks(goal_id=goal["id"])[1] == 2
    without = {task["id"] for task in manager.list_tasks(has_goal=False)[0]}
    assert without == {loose["id"], in_project["id"]}
    assert {task["id"] for task in manager.list_tasks(has_goal=True)[0]} == {inherited["id"], tagged["id"]}
    assert {row["id"] for row in manager.list_projects(has_goal=False)[0]} == {DEFAULT_PROJECT_ID, project["id"]}
    assert [row["id"] for row in manager.list_projects(has_goal=True)[0]] == [under_goal["id"]]
    assert manager.attention()["proposals"] == 4 and manager.attention(goal["id"])["proposals"] == 2
    assert manager.get(goal["id"])["counts"]["tasks"]["backlog"] == 2


def test_a_task_keeps_its_goal_when_it_moves_and_takes_one_when_it_has_none(system):
    manager = system.manager
    goal = manager.create(name="Developer docs")
    under_goal = manager.create_project(goal_id=goal["id"], name="3.3 migration guide")
    other = manager.create_project(name="Reach 50 customers by March")
    task = manager.create_task(title="Write the breaking changes", project_id=under_goal["id"])
    loose = manager.create_task(title="Fix the typo on the pricing page")

    moved = manager.update_task(task["id"], project_id=None)
    assert (moved["project_id"], moved["goal_id"]) == (DEFAULT_PROJECT_ID, goal["id"])
    assert manager.update_task(task["id"], project_id=under_goal["id"])["project_id"] == under_goal["id"]
    assert manager.update_task(loose["id"], project_id=other["id"])["project_id"] == other["id"]
    # A Task that has a Goal keeps it: a Project with no Goal, or with another, refuses it.
    elsewhere = manager.create_project(goal_id=manager.create(name="Customer support")["id"], name="Faster replies")
    for project_id in (other["id"], elsewhere["id"]):
        with pytest.raises(ValueError, match="Task and Project must belong to the same Goal"):
            manager.update_task(task["id"], project_id=project_id)
    # A Task with no Goal takes the Goal of the Project it moves into, from a Project or from Default.
    adopted = manager.update_task(loose["id"], project_id=under_goal["id"])
    assert (adopted["project_id"], adopted["goal_id"]) == (under_goal["id"], goal["id"])
    filed = manager.create_task(title="Fix the typo on the pricing page")
    adopted = manager.update_task(filed["id"], project_id=under_goal["id"])
    assert (adopted["project_id"], adopted["goal_id"]) == (under_goal["id"], goal["id"])
    assert manager.get(goal["id"])["counts"]["tasks"]["backlog"] == 3
    # Back in the Default Project it keeps the Goal it took.
    assert manager.update_task(filed["id"], project_id=None)["goal_id"] == goal["id"]


def test_work_with_no_goal_runs_the_whole_lifecycle(system):
    manager = system.manager
    loose = manager.create_task(title="Fix the typo on the pricing page")
    project = manager.create_project(name="Reach 50 customers by March")
    planned = manager.create_task(title="Count paying customers", project_id=project["id"])

    # The Default Project is active, so its Task is accepted with no approval.
    accepted = system.accept(loose["id"])
    assert accepted["status"] == "ready" and accepted["project_id"] == DEFAULT_PROJECT_ID
    refused = system.client.post(
        f"/company/tasks/{planned['id']}/transitions", json={"target": "ready", "reason": "Go"}, headers=headers()
    )
    assert refused.status_code == 409 and "Project approval is required" in refused.json()["detail"]
    manager.transition_project(project_id=project["id"], target="active", reason="Approved")
    assert system.accept(planned["id"])["status"] == "ready"

    done = system.execute(loose["id"])
    assert done["status"] == "in_review" and done["goal_id"] is None
    manager.transition_task(task_id=planned["id"], target="cancelled", reason="Not needed")
    assert manager.transition_project(project_id=project["id"], target="done", reason="Finished")["status"] == "done"
    assert manager.delete_task(loose["id"]) is True and manager.restore_task(loose["id"])["deleted_at"] is None
    assert manager.delete_project(project["id"]) is True
    assert manager.restore_project(project["id"])["deleted_at"] is None


def test_the_input_of_a_task_with_no_goal_carries_the_company_wiki_only(system):
    manager = system.manager
    goal = manager.create(name="Developer docs")
    loose = manager.create_task(title="Fix the typo", brief="Change 'recieve' to 'receive'.")
    tagged = manager.create_task(title="A stray finding", goal_id=goal["id"])

    pages = json.loads(asyncio.run(_task_input(manager, loose)))["wiki"]
    assert pages and {page["namespace"] for page in pages} == {"company"}
    with_goal = json.loads(asyncio.run(_task_input(manager, tagged)))["wiki"]
    assert [page["file"] for page in with_goal[:2]] == [
        f"goals/{goal['id']}/brief.md",
        f"goals/{goal['id']}/status.md",
    ]
    # The same company pages are sent either way.
    assert [page["file"] for page in with_goal[2:]] == [page["file"] for page in pages]


def test_the_api_takes_a_project_and_a_task_with_no_goal(system):
    goal = post(system, "/company/goals", {"name": "Developer docs"})

    project = post(system, "/company/projects", {"name": "Reach 50 customers by March"})
    assert (project["goal_id"], project["status"], project["is_default"]) == (None, "proposed", False)
    loose = post(system, "/company/tasks", {"title": "Fix the typo on the pricing page"})
    assert (loose["goal_id"], loose["project_id"]) == (None, DEFAULT_PROJECT_ID)
    in_project = post(system, "/company/tasks", {"title": "Count paying customers", "project_id": project["id"]})
    assert in_project["goal_id"] is None
    tagged = post(system, "/company/tasks", {"title": "A stray finding", "goal_id": goal["id"]})
    assert (tagged["goal_id"], tagged["project_id"]) == (goal["id"], DEFAULT_PROJECT_ID)
    mismatch = {"title": "Mismatched", "goal_id": goal["id"], "project_id": project["id"]}
    assert "same Goal" in post(system, "/company/tasks", mismatch, status=422)["detail"]

    projects = listed(system, "/company/projects")
    assert {p["id"]: (p["is_default"], p["goal_id"]) for p in projects} == {
        DEFAULT_PROJECT_ID: (True, None),
        project["id"]: (False, None),
    }
    assert listed(system, "/company/projects", goal_id=goal["id"]) == []
    assert {t["id"] for t in listed(system, "/company/tasks")} == {loose["id"], in_project["id"], tagged["id"]}
    in_default = listed(system, "/company/tasks", project_id=DEFAULT_PROJECT_ID)
    assert {t["id"] for t in in_default} == {loose["id"], tagged["id"]}
    assert [t["id"] for t in listed(system, "/company/tasks", goal_id=goal["id"])] == [tagged["id"]]
    # has_goal=false lists the records with no Goal, and has_goal=true the others.
    assert {t["id"] for t in listed(system, "/company/tasks", has_goal="false")} == {loose["id"], in_project["id"]}
    assert [t["id"] for t in listed(system, "/company/tasks", has_goal="true")] == [tagged["id"]]
    no_goal = listed(system, "/company/projects", has_goal="false")
    assert {p["id"] for p in no_goal} == {DEFAULT_PROJECT_ID, project["id"]}
    assert listed(system, "/company/projects", has_goal="true") == []

    moved = system.client.patch(
        f"/company/tasks/{in_project['id']}", json={"project_id": None}, headers=headers()
    ).json()
    assert moved["project_id"] == DEFAULT_PROJECT_ID
    attention = system.client.get("/company/attention", headers=headers()).json()
    assert attention["proposals"] == 3


@pytest.mark.parametrize("use_async", [False, True])
def test_the_tools_take_a_project_and_a_task_with_no_goal(system, use_async):
    tools = company_tools(system)
    # Listing Backlog Tasks also reads the Routines, from the table AgentOS creates when it starts.
    system.db._get_table(table_type="schedules", create_table_if_not_found=True)

    def call(tool_name, **arguments):
        function = getattr(tools, ("a" if use_async else "") + tool_name)
        result = function(**arguments, _agno_run_context=chat())
        return json.loads(asyncio.run(result) if use_async else result)

    project = call("propose_company_project", goal_id=None, name="Reach 50 customers by March")
    assert (project["goal_id"], project["status"]) == (None, "proposed")
    # A model sends an empty string where it means no value.
    loose = call("propose_company_task", title="Fix the typo on the pricing page", goal_id="", project_id="")
    assert (loose["goal_id"], loose["project_id"], loose["status"]) == (None, DEFAULT_PROJECT_ID, "backlog")
    in_project = call("propose_company_task", goal_id=None, title="Count paying customers", project_id=project["id"])
    assert in_project["goal_id"] is None

    # A Task may carry a Goal. In a Project it is the Project's Goal; in the Default Project it is the one given.
    goal = system.manager.create(name="Developer docs")
    under_goal = call("propose_company_project", goal_id=goal["id"], name="3.3 migration guide")
    filled = call("propose_company_task", goal_id=None, title="Write the breaking changes", project_id=under_goal["id"])
    agreed = call("propose_company_task", goal_id=goal["id"], title="Review it", project_id=under_goal["id"])
    assert filled["goal_id"] == agreed["goal_id"] == goal["id"]
    tagged = [
        call("propose_company_task", goal_id=goal["id"], title="A docs chore", project_id=project_id)
        for project_id in (None, "", DEFAULT_PROJECT_ID)
    ]
    assert {(task["project_id"], task["goal_id"]) for task in tagged} == {(DEFAULT_PROJECT_ID, goal["id"])}
    with pytest.raises(ValueError, match="Task and Project must belong to the same Goal"):
        call("propose_company_task", goal_id=goal["id"], title="Mismatched", project_id=project["id"])
    for task in (filled, agreed, *tagged):
        system.manager.delete_task(task["id"])
    system.manager.delete_project(under_goal["id"])

    projects = call("list_company_projects")["data"]
    assert {p["id"]: p["is_default"] for p in projects} == {DEFAULT_PROJECT_ID: True, project["id"]: False}
    tasks = call("list_company_tasks")
    assert {task["id"] for task in tasks["data"]} == {loose["id"], in_project["id"]}


def test_the_tool_arguments_take_no_goal_and_no_project(system):
    functions = company_tools(system).get_async_functions()
    for name in ("propose_company_project", "propose_company_task"):
        functions[name].process_entrypoint()
        # The argument keeps its place, and a model sends null for no Goal.
        assert next(iter(functions[name].parameters["properties"])) == "goal_id"
        assert "null" in json.dumps(functions[name].parameters["properties"]["goal_id"]), name
    assert "null" in json.dumps(functions["propose_company_task"].parameters["properties"]["project_id"])


def test_super_agent_is_told_where_a_single_task_goes():
    assert "A Goal is optional." in COMPANY_INSTRUCTIONS
    assert "A target with a number or a date is a Project, never a Goal." in COMPANY_INSTRUCTIONS
    assert "goes in the Default Project" in COMPANY_INSTRUCTIONS
    assert "never make a Project to hold one Task" in COMPANY_INSTRUCTIONS


# --------------------------------------------------------------------------- archiving a Goal


def test_archiving_a_goal_takes_its_tasks_out_of_the_default_project_and_leaves_the_project(system):
    manager = system.manager
    goal = manager.create(name="Developer docs")
    tagged = manager.create_task(title="A stray finding", goal_id=goal["id"])
    loose = manager.create_task(title="Fix the typo on the pricing page")

    assert manager.delete(goal["id"]) is True

    assert manager.get_task(tagged["id"]) is None and manager.get_task(loose["id"]) is not None
    default = manager.get_project(DEFAULT_PROJECT_ID)
    assert default["deleted_at"] is None and default["counts"]["tasks"]["backlog"] == 1
    assert manager.restore(goal["id"]) is not None
    assert manager.get_task(tagged["id"])["project_id"] == DEFAULT_PROJECT_ID


# ----------------------------------------------------------------- a Routine stays inside its Goal


def test_a_routine_is_refused_outside_its_goal(open_system, tmp_path):
    manager = open_system.manager
    goal_id, routine_id = open_system.declare(auto_accept=False)
    other = manager.create(name="Customer support")
    loose_project = manager.create_project(name="Reach 50 customers by March")
    other_project = manager.create_project(goal_id=other["id"], name="Faster replies")
    page = tmp_path / "release.md"
    page.write_text("# Release\nA new feature.\n")
    source = manager.create_source(goal_id=goal_id, type="markdown", reference=str(page))
    hashes = {item["link"]: item["content_hash"] for item in manager.read_source(source["id"], "observe")}

    def proposal(key):
        return dict(
            title="Document the feature",
            brief="Explain the released capability.",
            proposal_key=key,
            evidence_links=[page.as_uri()],
            evidence_hashes=hashes,
        )

    authority = _RoutineAuthorization(None, routine_id=routine_id, goal_id=goal_id)
    with authorization_scope(lambda: authority):
        with pytest.raises(PermissionError, match="Routine authority is restricted to its configured Goal"):
            manager.create_project(goal_id=other["id"], name="Outside")
        # A Project a Routine proposes carries the Routine's Goal, also when it names none.
        assert manager.create_project(name="Named no Goal")["goal_id"] == goal_id
        with pytest.raises(PermissionError, match="Routines must propose Tasks through intake_goal_source"):
            manager.create_task(title="A loose Task")
        for project in (loose_project, other_project):
            with pytest.raises(PermissionError, match="restricted to its configured Goal"):
                manager.delete_project(project["id"])
            with pytest.raises(ValueError, match="Task and Project must belong to the same Goal"):
                manager.intake(source_id=source["id"], run_id="run", proposal=proposal("a"), project_id=project["id"])
        with pytest.raises(PermissionError, match="restricted to its configured Goal"):
            manager.write_wiki(goal_id=None, path="priorities.md", content="# Changed\n", expected_version=0)

        # Inside its Goal it proposes a Project, and a Task with no Project lands in the Default
        # Project tagged with the Routine's Goal.
        own = manager.create_project(goal_id=goal_id, name="Fixes")
        stray = manager.intake(source_id=source["id"], run_id="run", proposal=proposal("stray"))
        filed = manager.intake(source_id=source["id"], run_id="run", proposal=proposal("filed"), project_id=own["id"])

    assert (stray["project_id"], stray["goal_id"], stray["routine_id"]) == (DEFAULT_PROJECT_ID, goal_id, routine_id)
    assert (filed["project_id"], filed["goal_id"]) == (own["id"], goal_id)


def test_a_task_run_acts_only_on_records_of_its_tasks_goal():
    with_goal = _ExecutorAuthorization(None, task_id="task-1")
    with_goal.goal_id = "docs"
    no_goal = _ExecutorAuthorization(None, task_id="task-2")
    unbound = _ExecutorAuthorization(None)

    _require_routine_goal("docs", with_goal)
    _require_routine_goal(None, no_goal)
    for goal_id, authority in ((None, with_goal), ("support", with_goal), ("docs", no_goal)):
        with pytest.raises(PermissionError, match="A Task run is restricted to its Task's Goal"):
            _require_routine_goal(goal_id, authority)
    # A page of the whole company is not a record with no Goal: no Task run changes it.
    for authority in (with_goal, no_goal):
        with pytest.raises(PermissionError, match="A Task run is restricted to its Task's Goal"):
            _require_routine_goal(None, authority, company_wide=True)
    # An authority that names no Task and no Goal is not bound, as before.
    _require_routine_goal("docs", unbound)
    _require_routine_goal(None, None)


def test_auto_accept_leaves_a_task_in_the_default_project_for_a_person(open_system):
    goal_id, routine_id = open_system.declare(auto_accept=True)
    stray = open_system.manager.create_task(
        goal_id=goal_id, title="Fix the install page", origin="routine", routine_id=routine_id
    )
    assert stray["project_id"] == DEFAULT_PROJECT_ID
    # The same Routine's Task in a Project of its own is accepted, with the Project approved by the policy.
    _, filed = open_system.proposes(goal_id, routine_id)

    outcomes = open_system.tick()

    skipped = open_system.outcome(outcomes, stray["id"])
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "A Task in the Default Project waits for a person to accept it"
    waiting = open_system.manager.get_task(stray["id"])
    assert waiting["status"] == "backlog" and not receipts(waiting)
    assert open_system.outcome(outcomes, filed["id"])["status"] == "accepted"
    assert open_system.manager.get_project(DEFAULT_PROJECT_ID)["transitions"] == []
    # A person accepts it with no Project approval: the Default Project is always active.
    accepted = open_system.manager.transition_task(
        task_id=stray["id"], target="ready", reason="Looks right", executor_type="agent", executor_id="writer"
    )
    assert accepted["status"] == "ready"


def test_a_proposal_in_the_default_project_is_not_counted_as_waiting_for_room():
    from agno.company.declarations import AutoAccept
    from agno.company.manager import _at_limit

    policy = AutoAccept(default_executor="writer", max_open=1).model_dump()
    schedule = {"id": "r1", "name": "docs.intake", "enabled": True, "payload": {"metadata": {"auto_accept": policy}}}
    tasks = [
        {"routine_id": "r1", "status": "in_review", "project_id": "p1"},
        {"routine_id": "r1", "status": "backlog", "project_id": "p1"},
        {"routine_id": "r1", "status": "backlog", "project_id": DEFAULT_PROJECT_ID},
    ]

    waiting = _at_limit({"id": "docs"}, [schedule], tasks)

    # Finishing the open Task makes room for the one proposal in a Project. The other waits for a person.
    assert [(item["routine"], item["open_tasks"], item["proposals_waiting"]) for item in waiting] == [("intake", 1, 1)]


def test_a_move_with_no_goal_locks_the_project_it_moves_into(system):
    from sqlalchemy import event

    manager = system.manager
    source = manager.create_project(name="Reach 50 customers by March")
    target = manager.create_project(name="Launch week")
    task = manager.create_task(title="Count paying customers", project_id=source["id"])
    locked = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE") and "agno_company_projects" in statement:
            locked.extend(value for value in parameters if value in (source["id"], target["id"]))
        elif statement.lstrip().upper().startswith("UPDATE") and "agno_company_tasks" in statement:
            locked.append("task written")

    event.listen(system.db.db_engine, "before_cursor_execute", record)
    try:
        moved = manager.update_task(task["id"], project_id=target["id"])
    finally:
        event.remove(system.db.db_engine, "before_cursor_execute", record)

    assert moved["project_id"] == target["id"]
    # Both Projects are locked before the Task is written, so neither can complete in between.
    # The lower id is locked first whichever way the Task moves, so opposite moves cannot deadlock.
    assert locked[-1] == "task written"
    assert list(dict.fromkeys(locked[:-1])) == sorted([source["id"], target["id"]])
    locked.clear()
    event.listen(system.db.db_engine, "before_cursor_execute", record)
    try:
        manager.update_task(task["id"], project_id=source["id"])
    finally:
        event.remove(system.db.db_engine, "before_cursor_execute", record)
    assert list(dict.fromkeys(locked[:-1])) == sorted([source["id"], target["id"]])
    manager.update_task(task["id"], project_id=target["id"])
    manager.transition_project(project_id=target["id"], target="active", reason="Approved")
    with pytest.raises(ValueError, match="Project has open Tasks"):
        manager.transition_project(project_id=target["id"], target="done", reason="Finished")


def test_a_write_that_waited_behind_a_goal_taking_move_follows_the_task_to_its_goal(system, monkeypatch):
    import agno.db.sql.company as company

    manager = system.manager
    goal = manager.create(name="Developer docs")
    under_goal = manager.create_project(goal_id=goal["id"], name="3.3 migration guide")
    task = manager.create_task(title="Fix the typo on the pricing page")
    tasks = system.db._get_table(table_type="tasks")
    original_parent, original_goal = company.lock_parent, company.lock_goal
    locked = []

    def move_wins_first(sess, goals, projects, goal_id, project_id=None):
        # The move into the Goal's Project finishes while this write waits for its lock.
        original_parent(sess, goals, projects, goal_id, project_id)
        if goal_id is None and project_id == DEFAULT_PROJECT_ID and not locked:
            moved = tasks.update().where(tasks.c.id == task["id"])
            sess.execute(moved.values(goal_id=goal["id"], project_id=under_goal["id"]))

    def record(sess, goals, goal_id):
        locked.append(goal_id)
        return original_goal(sess, goals, goal_id)

    monkeypatch.setattr(company, "lock_parent", move_wins_first)
    monkeypatch.setattr(company, "lock_goal", record)

    # The edit is not refused as a Goal mismatch, and it takes the lock of the Goal the Task now has.
    edited = system.db.update_task(task["id"], title="Fix the pricing page typo")

    assert locked == [goal["id"]]
    assert (edited["title"], edited["goal_id"], edited["project_id"]) == (
        "Fix the pricing page typo",
        goal["id"],
        under_goal["id"],
    )


# ------------------------------------------------------------- the Default Project never completes


def test_completion_checks_skip_the_default_project(open_system):
    manager = open_system.manager
    policy = {"complete_projects": True}
    goal_id, _ = open_system.declare(auto_accept=False)
    created = open_system.api_routine(goal_id, None, name="refresh-work")
    assert created.status_code == 201, created.text
    project = manager.create_project(goal_id=goal_id, name="Fixes")
    manager.transition_project(project_id=project["id"], target="active", reason="Approved")
    in_project = manager.create_task(goal_id=goal_id, project_id=project["id"], title="Fix the install page")
    in_default = manager.create_task(goal_id=goal_id, title="A stray finding")
    loose = manager.create_task(title="Fix the typo")
    for task in (in_project, in_default, loose):
        manager.transition_task(task_id=task["id"], target="cancelled", reason="Not needed")

    result = manager.refresh(goal_id)

    # Every Task of the Default Project is terminal, and only the ordinary Project is proposed.
    assert [item["project_id"] for item in result["completion_proposals"]] == [project["id"]]
    assert result["archived_projects"] == []
    outcomes = asyncio.run(open_system.executor._complete_projects())
    assert DEFAULT_PROJECT_ID not in {item.get("project_id") for item in outcomes}
    default = manager.get_project(DEFAULT_PROJECT_ID)
    assert (default["status"], default["deleted_at"], default["transitions"]) == ("active", None, [])
    with pytest.raises(ValueError, match=TRANSITION):
        manager.transition_project(
            project_id=DEFAULT_PROJECT_ID,
            target="done",
            reason="Authorized Refresh completion proposal",
            auto_accept={"routine_id": created.json()["id"], "policy": json.dumps(policy)},
            expected_updated_at=default["updated_at"],
        )
    # New work still goes in after every earlier Task has finished.
    assert manager.create_task(title="Another one")["project_id"] == DEFAULT_PROJECT_ID
