"""A Task run is given its brief, its evidence and what its coordinator attached. Nothing else.

A Task holds a context list of references: a wiki page, a page of a Goal, another Task, a file a
Task wrote. A person, Super Agent for that person, or a Routine for the Backlog Tasks of its Goal
changes the list. A Task run never does. When a run starts, each reference is read as it is then
and pasted into the input, and the attempt records what was sent.
"""

import asyncio
import json

import pytest

from agno.company import AsyncCompanyManager, CompanyManager
from agno.company.context import (
    CONTEXT_FILE_NAMES,
    CONTEXT_ITEM_CHARS,
    CONTEXT_TITLE_CHARS,
    CONTEXT_TOTAL_CHARS,
    context_sent,
)
from agno.company.execution import _ExecutorAuthorization, _task_input
from agno.company.files import CompanyFiles
from agno.company.mini_agent import TASK_COMPANY_TOOLS, TASK_INSTRUCTIONS
from agno.company.routines import _RoutineAuthorization
from agno.db.schemas.tasks import MAX_TASK_CONTEXT_ENTRIES
from agno.db.sqlite import AsyncSqliteDb
from agno.os.manager.prompts import COMPANY_INSTRUCTIONS
from agno.run.authorization import authorization_scope
from tests.unit.os.test_company_file_tree import RUN_ONLY, call, person
from tests.unit.os.test_company_policy_path import PolicySystem, company_tools
from tests.unit.os.test_mini_agent_tasks import SCOPES, headers

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

NOTES = "Breaking: Agent(storage=) is now Agent(db=)."
HANDOFF = "The next section needs the renamed parameters: storage -> db, show_tool_calls removed."


@pytest.fixture
def system(tmp_path):
    value = PolicySystem(tmp_path)
    yield value
    value.db.close()


def seed(system):
    """A Goal with an active Project, a finished Task that wrote notes and a handoff, and the next Task."""
    manager = system.manager
    goal = manager.create(name="Developer docs")
    project = manager.create_project(goal_id=goal["id"], name="3.3 migration guide")
    manager.transition_project(project_id=project["id"], target="active", reason="Approved")
    earlier = manager.create_task(goal_id=goal["id"], project_id=project["id"], title="Write the upgrade notes")
    files = CompanyFiles(system.db)
    files.write(f"tasks/{earlier['id']}/upgrade-notes.md", NOTES)
    files.write(f"tasks/{earlier['id']}/handoff.md", HANDOFF)
    system.accept(earlier["id"])
    system.execute(earlier["id"])
    following = manager.create_task(
        goal_id=goal["id"], project_id=project["id"], title="Write the breaking-changes section", brief="Write it."
    )
    other = manager.create(name="Other")
    stray = manager.create_task(goal_id=other["id"], title="Elsewhere")
    files.write(f"tasks/{stray['id']}/report.md", "Elsewhere.")
    manager.write_wiki(goal_id=None, path="glossary.md", content="A Goal is a standing aim.", expected_version=0)
    return {
        "goal": goal["id"],
        "project": project["id"],
        "earlier": earlier["id"],
        "task": following["id"],
        "other": other["id"],
        "stray": stray["id"],
    }


def references(ids):
    return [
        {"kind": "wiki", "ref": "wiki/glossary.md"},
        {"kind": "goal", "ref": f"goals/{ids['goal']}/status.md"},
        {"kind": "task", "ref": ids["earlier"]},
        {"kind": "file", "ref": f"tasks/{ids['earlier']}/upgrade-notes.md"},
    ]


def task_input(system, task_id):
    return json.loads(asyncio.run(_task_input(system.manager, system.db.get_task(task_id), accepted_execution=True)))


def task_run(goal_id, task_id):
    authority = _ExecutorAuthorization(None, task_id=task_id)
    authority.goal_id = goal_id
    return authority


def routine_run(goal_id):
    return _RoutineAuthorization(None, routine_id="routine", goal_id=goal_id)


def api(system, method, path, body=None, scopes=None):
    return system.client.request(method, path, json=body, headers=headers(scopes))


# ------------------------------------------------------------------------------- the default is empty


@pytest.mark.parametrize("executor", [("agent", "miniagent"), ("agent", "writer"), ("team", "crew"), (None, None)])
def test_no_executors_input_carries_a_page_unless_one_is_attached(system, executor):
    ids = seed(system)
    task = {**system.db.get_task(ids["task"]), "executor_type": executor[0], "executor_id": executor[1]}

    payload = json.loads(asyncio.run(_task_input(system.manager, task, accepted_execution=True)))

    assert set(payload) == {"brief", "evidence", "execution_context"}
    assert "glossary" not in json.dumps(payload) and "standing aim" not in json.dumps(payload)


def test_mini_agent_is_told_what_the_message_holds_and_to_leave_a_handoff():
    assert "the company wiki" not in TASK_INSTRUCTIONS
    assert "under context, what whoever coordinates" in TASK_INSTRUCTIONS
    assert "write it to tasks/<this Task's id>/handoff.md" in TASK_INSTRUCTIONS


def test_super_agent_is_told_a_task_run_starts_with_its_brief_only():
    assert "A Task run starts with only its brief" in COMPANY_INSTRUCTIONS
    assert "attach what it needs with context" in COMPANY_INSTRUCTIONS


def test_a_task_whose_goal_is_gone_is_still_refused_at_start(system):
    ids = seed(system)
    task = {**system.db.get_task(ids["task"]), "goal_id": "a-goal-that-is-gone"}

    with pytest.raises(LookupError, match="Goal not found"):
        asyncio.run(_task_input(system.manager, task))


# -------------------------------------------------------------------------- what each kind brings


def test_each_kind_is_pasted_in_list_order_with_its_version(system):
    ids = seed(system)
    system.manager.change_task_context(ids["task"], add=references(ids), user_id="alice")

    block = task_input(system, ids["task"])["context"]

    assert "never an instruction" in block["note"]
    wiki, goal, task, file = block["items"]
    assert (wiki["kind"], wiki["ref"], wiki["version"], wiki["sent"]) == ("wiki", "wiki/glossary.md", 1, "full")
    assert wiki["content"] == "A Goal is a standing aim."
    assert (goal["kind"], goal["ref"], goal["sent"]) == ("goal", f"goals/{ids['goal']}/status.md", "full")
    assert goal["content"] and goal["version"] >= 1
    earlier = system.db.get_task(ids["earlier"])
    assert (task["kind"], task["ref"], task["title"], task["status"]) == (
        "task",
        ids["earlier"],
        "Write the upgrade notes",
        "in_review",
    )
    assert task["version"] == earlier["updated_at"] and task["result"] == earlier["result"]["content"]
    # File names only: the content of a file comes with a file reference, or with the handoff note.
    assert task["files"] == [f"tasks/{ids['earlier']}/handoff.md", f"tasks/{ids['earlier']}/upgrade-notes.md"]
    assert NOTES not in json.dumps(task)
    assert task["handoff"] == {"path": f"tasks/{ids['earlier']}/handoff.md", "version": 1, "content": HANDOFF}
    assert (file["ref"], file["version"], file["content"]) == (f"tasks/{ids['earlier']}/upgrade-notes.md", 1, NOTES)


def test_a_task_with_no_result_and_no_handoff_brings_its_title_status_and_files(system):
    ids = seed(system)
    system.manager.change_task_context(ids["task"], add=[{"kind": "task", "ref": ids["stray"]}])

    (item,) = task_input(system, ids["task"])["context"]["items"]

    assert (item["title"], item["status"], item["files"]) == (
        "Elsewhere",
        "backlog",
        [f"tasks/{ids['stray']}/report.md"],
    )
    assert "result" not in item and "handoff" not in item and item["sent"] == "full"


def test_the_references_are_read_when_the_run_starts_not_when_they_are_attached(system):
    ids = seed(system)
    path = f"tasks/{ids['earlier']}/upgrade-notes.md"
    system.manager.change_task_context(ids["task"], add=[{"kind": "file", "ref": path}])
    CompanyFiles(system.db).write(path, "Rewritten after it was attached.")

    (item,) = task_input(system, ids["task"])["context"]["items"]

    assert (item["version"], item["content"]) == (2, "Rewritten after it was attached.")


def test_a_long_item_is_cut_and_items_past_the_total_are_named_without_content(system):
    ids = seed(system)
    files = CompanyFiles(system.db)
    count = CONTEXT_TOTAL_CHARS // CONTEXT_ITEM_CHARS + 1
    for index in range(count):
        files.write(f"tasks/{ids['earlier']}/part-{index}.md", str(index) * (CONTEXT_ITEM_CHARS + 5))
    files.write(f"tasks/{ids['earlier']}/small.md", "fits nowhere")
    paths = [f"tasks/{ids['earlier']}/part-{index}.md" for index in range(count)]
    refs = [{"kind": "file", "ref": path} for path in [*paths, f"tasks/{ids['earlier']}/small.md"]]
    system.manager.change_task_context(ids["task"], add=refs)

    items = task_input(system, ids["task"])["context"]["items"]

    assert sum(len(item["content"] or "") for item in items) <= CONTEXT_TOTAL_CHARS
    first, past = items[0], items[count - 1]
    assert first["content"] == "0" * CONTEXT_ITEM_CHARS and first["sent"] == "partial"
    assert first["note"] == f"{paths[0]} is cut at {CONTEXT_ITEM_CHARS} characters. The rest was not sent."
    assert past["content"] is None and past["sent"] == "partial" and past["version"] == 1
    assert past["note"] == (
        f"{paths[-1]} was not sent: the attached context holds {CONTEXT_TOTAL_CHARS} characters in total."
    )
    # The total is spent, so a later small item is named too.
    assert items[-1]["content"] is None and "was not sent" in items[-1]["note"]


def test_a_long_result_and_handoff_are_each_cut(system):
    ids = seed(system)
    CompanyFiles(system.db).write(f"tasks/{ids['earlier']}/handoff.md", "h" * (CONTEXT_ITEM_CHARS + 1))
    system.manager.change_task_context(ids["task"], add=[{"kind": "task", "ref": ids["earlier"]}])

    (item,) = task_input(system, ids["task"])["context"]["items"]

    assert len(item["handoff"]["content"]) == CONTEXT_ITEM_CHARS and item["sent"] == "partial"
    assert item["note"] == f"handoff.md is cut at {CONTEXT_ITEM_CHARS} characters. The rest was not sent."


def test_an_entry_whose_target_is_gone_is_named_and_the_start_goes_on(system):
    ids = seed(system)
    system.manager.change_task_context(
        ids["task"],
        add=[
            {"kind": "task", "ref": ids["stray"]},
            {"kind": "file", "ref": f"tasks/{ids['stray']}/report.md"},
            {"kind": "goal", "ref": f"goals/{ids['other']}/status.md"},
            {"kind": "wiki", "ref": "wiki/glossary.md"},
        ],
    )
    system.manager.delete_task(ids["stray"])
    system.db.delete_goal(ids["other"])

    gone_task, kept_file, gone_page, wiki = task_input(system, ids["task"])["context"]["items"]

    assert gone_task == {
        "kind": "task",
        "ref": ids["stray"],
        "sent": "missing",
        "note": "Not sent: the Task no longer exists.",
    }
    # Archiving a Task removes no file, so a file reference still reads.
    assert kept_file["content"] == "Elsewhere."
    assert gone_page["sent"] == "missing" and "Goal not found" in gone_page["note"] and "content" not in gone_page
    assert wiki["sent"] == "full"


# --------------------------------------------------------------------------------- who may change it


def test_a_person_attaches_and_removes_through_the_api_at_any_open_status(system):
    ids = seed(system)
    path = f"/company/tasks/{ids['task']}/context"

    added = api(system, "POST", path, {"kind": "task", "ref": ids["earlier"]})
    assert added.status_code == 200, added.text
    (entry,) = added.json()["context"]
    assert (entry["kind"], entry["ref"], entry["added_by"]) == ("task", ids["earlier"], "alice")
    assert entry["id"] and isinstance(entry["added_at"], int)
    # Attaching the same reference again changes nothing.
    again = api(system, "POST", path, {"kind": "task", "ref": ids["earlier"]})
    assert [item["id"] for item in again.json()["context"]] == [entry["id"]]

    # The list is not frozen at acceptance.
    system.accept(ids["task"])
    wiki = api(system, "POST", path, {"kind": "wiki", "ref": "glossary.md"})
    assert [item["ref"] for item in wiki.json()["context"]] == [ids["earlier"], "wiki/glossary.md"]
    removed = api(system, "DELETE", f"{path}/{entry['id']}")
    assert removed.status_code == 200 and [item["ref"] for item in removed.json()["context"]] == ["wiki/glossary.md"]
    assert api(system, "DELETE", f"{path}/{entry['id']}").status_code == 404
    assert api(system, "GET", f"/company/tasks/{ids['task']}").json()["context"] == removed.json()["context"]

    system.manager.transition_task(task_id=ids["task"], target="cancelled", reason="Not needed")
    closed = api(system, "POST", path, {"kind": "task", "ref": ids["earlier"]})
    assert closed.status_code == 409 and closed.json()["detail"] == "The context of a cancelled Task cannot change"
    assert api(system, "DELETE", f"{path}/{wiki.json()['context'][-1]['id']}").status_code == 409


def test_a_task_is_created_with_its_context_through_the_api(system):
    ids = seed(system)
    body = {"title": "Write the summary", "project_id": ids["project"], "context": references(ids)}

    created = api(system, "POST", "/company/tasks", body)

    assert created.status_code == 201, created.text
    assert [(item["kind"], item["added_by"]) for item in created.json()["context"]] == [
        ("wiki", "alice"),
        ("goal", "alice"),
        ("task", "alice"),
        ("file", "alice"),
    ]
    assert api(system, "POST", "/company/tasks", {"title": "No context"}).json()["context"] == []


@pytest.mark.parametrize(
    "reference, status, detail",
    [
        ({"kind": "wiki", "ref": "wiki/absent.md"}, 422, "wiki/absent.md does not exist"),
        ({"kind": "task", "ref": "no-such-task"}, 404, "Task not found: no-such-task"),
        ({"kind": "file", "ref": "tasks/no-such-task/report.md"}, 404, "Task not found"),
        ({"kind": "goal", "ref": "goals/no-such-goal/status.md"}, 404, "Goal not found"),
        ({"kind": "goal", "ref": "wiki/glossary.md"}, 422, "A goal reference names a page of a Goal"),
        # A wiki reference is a path under wiki/, so this names no page there.
        ({"kind": "wiki", "ref": "notes/ideas.md"}, 422, "wiki/notes/ideas.md does not exist"),
        ({"kind": "file", "ref": "notes/ideas.md"}, 422, "A file reference names a file a Task wrote"),
        ({"kind": "notes", "ref": "notes/ideas.md"}, 422, "Input should be"),
    ],
)
def test_a_reference_that_names_nothing_is_refused_when_it_is_added(system, reference, status, detail):
    ids = seed(system)

    added = api(system, "POST", f"/company/tasks/{ids['task']}/context", reference)
    created = api(system, "POST", "/company/tasks", {"title": "Next", "context": [reference]})

    assert added.status_code == status and detail in added.text, added.text
    assert created.status_code == status and detail in created.text, created.text
    assert system.db.get_task(ids["task"])["context"] is None
    assert system.manager.list_tasks(limit=100)[1] == 3


@pytest.mark.parametrize(
    "kind, missing",
    [
        ("wiki", "wiki:read"),
        ("goal", "wiki:read"),
        ("file", "wiki:read"),
        ("task", "wiki:read"),
        ("task", "tasks:read"),
    ],
)
def test_a_reference_the_caller_may_not_read_is_refused_and_nothing_is_attached(system, kind, missing):
    ids = seed(system)
    reference = next(item for item in references(ids) if item["kind"] == kind)
    scopes = [scope for scope in SCOPES if scope != missing]

    added = api(system, "POST", f"/company/tasks/{ids['task']}/context", reference, scopes=scopes)
    created = api(system, "POST", "/company/tasks", {"title": "Next", "context": [reference]}, scopes=scopes)

    assert added.status_code == 403 and created.status_code == 403, (added.text, created.text)
    assert system.db.get_task(ids["task"])["context"] is None
    for use_async in (False, True):
        with pytest.raises(PermissionError):
            call(
                company_tools(system),
                "update_company_task_context",
                person([*RUN_ONLY, *scopes]),
                use_async,
                task_id=ids["task"],
                add=[reference],
            )
    assert system.db.get_task(ids["task"])["context"] is None


def test_changing_a_context_asks_for_tasks_write(system):
    ids = seed(system)
    readonly = [scope for scope in SCOPES if scope != "tasks:write"]
    path = f"/company/tasks/{ids['task']}/context"

    assert api(system, "POST", path, {"kind": "wiki", "ref": "wiki/glossary.md"}, scopes=readonly).status_code == 403
    assert api(system, "DELETE", f"{path}/abc", scopes=readonly).status_code == 403


@pytest.mark.parametrize("use_async", [False, True])
def test_super_agent_creates_a_task_with_its_context_and_changes_it_later(system, use_async):
    ids = seed(system)
    tools = company_tools(system)

    created = call(
        tools,
        "propose_company_task",
        person(),
        use_async,
        goal_id=None,
        title="Write the summary",
        project_id=ids["project"],
        context=[{"kind": "task", "ref": ids["earlier"]}],
    )
    (entry,) = created["context"]
    assert (entry["kind"], entry["ref"], entry["added_by"]) == ("task", ids["earlier"], "alice")

    changed = call(
        tools,
        "update_company_task_context",
        person(),
        use_async,
        task_id=created["id"],
        add=[{"kind": "wiki", "ref": "wiki/glossary.md"}],
        remove=[entry["id"]],
    )
    assert [(item["kind"], item["ref"]) for item in changed["context"]] == [("wiki", "wiki/glossary.md")]
    with pytest.raises(ValueError, match="wiki/absent.md does not exist"):
        call(
            tools,
            "update_company_task_context",
            person(),
            use_async,
            task_id=created["id"],
            add=[{"kind": "wiki", "ref": "wiki/glossary.md"}, {"kind": "wiki", "ref": "wiki/absent.md"}],
        )
    with pytest.raises(LookupError, match="Context entry gone not found"):
        call(tools, "update_company_task_context", person(), use_async, task_id=created["id"], remove=["gone"])
    assert system.db.get_task(created["id"])["context"] == changed["context"]


@pytest.mark.parametrize("use_async", [False, True])
def test_a_task_run_never_changes_a_context_whatever_tools_it_holds(system, use_async):
    ids = seed(system)
    tools = company_tools(system)
    own = task_run(ids["goal"], ids["task"])
    refusal = "A Task run cannot change what a Task is given"

    for target in (ids["task"], ids["earlier"], ids["stray"]):
        with pytest.raises(PermissionError, match=refusal):
            call(
                tools,
                "update_company_task_context",
                own,
                use_async,
                task_id=target,
                add=[{"kind": "wiki", "ref": "wiki/glossary.md"}],
            )
    with pytest.raises(PermissionError, match=refusal):
        call(
            tools,
            "propose_company_task",
            own,
            use_async,
            goal_id=ids["goal"],
            title="A Task that reads the wiki for me",
            context=[{"kind": "wiki", "ref": "wiki/glossary.md"}],
        )
    # The same refusal for a run that wraps a person's authority, and below the tools.
    wrapped = _ExecutorAuthorization(person(), ids["task"])
    with authorization_scope(lambda: wrapped):
        with pytest.raises(PermissionError, match=refusal):
            system.manager.change_task_context(ids["task"], add=[{"kind": "wiki", "ref": "wiki/glossary.md"}])
        with pytest.raises(PermissionError, match=refusal):
            system.manager.change_task_context(ids["task"], remove=["anything"])
    assert system.db.get_task(ids["task"])["context"] is None
    assert system.manager.list_tasks(limit=100)[1] == 3


def test_mini_agents_task_run_holds_no_tool_that_changes_a_context(system):
    assert "update_company_task_context" not in TASK_COMPANY_TOOLS
    held = {name for toolkit in system.mini.tools.task for name in toolkit.get_functions()}
    assert not {"update_company_task_context", "propose_company_task", "intake_goal_source"} & held
    routine = {name for toolkit in system.mini.tools.routine for name in toolkit.get_functions()}
    assert {"update_company_task_context", "intake_goal_source"} <= routine


@pytest.mark.parametrize("use_async", [False, True])
def test_a_routine_changes_only_backlog_tasks_of_its_goal_with_its_goals_references(system, use_async):
    ids = seed(system)
    tools = system.mini.tools.routine[0]
    routine = routine_run(ids["goal"])

    def attach(task_id, reference):
        return call(tools, "update_company_task_context", routine, use_async, task_id=task_id, add=[reference])

    allowed = [item for item in references(ids)]
    for reference in allowed:
        changed = attach(ids["task"], reference)
    assert [item["added_by"] for item in changed["context"]] == ["routine:routine"] * 4

    outside = "Routine authority is restricted to its configured Goal"
    for reference in (
        {"kind": "goal", "ref": f"goals/{ids['other']}/status.md"},
        {"kind": "task", "ref": ids["stray"]},
        {"kind": "file", "ref": f"tasks/{ids['stray']}/report.md"},
    ):
        with pytest.raises(PermissionError, match=outside):
            attach(ids["task"], reference)
    # A Task of another Goal, and a Task of its own Goal that left Backlog.
    with pytest.raises(PermissionError, match=outside):
        attach(ids["stray"], {"kind": "wiki", "ref": "wiki/glossary.md"})
    with pytest.raises(PermissionError, match="A Routine changes the context of Backlog Tasks only"):
        attach(ids["earlier"], {"kind": "wiki", "ref": "wiki/glossary.md"})
    with pytest.raises(PermissionError, match="Backlog Tasks only"):
        call(tools, "update_company_task_context", routine, use_async, task_id=ids["earlier"], remove=["x"])
    assert len(system.db.get_task(ids["task"])["context"]) == 4
    assert system.db.get_task(ids["stray"])["context"] is None and system.db.get_task(ids["earlier"])["context"] is None


def test_a_context_holds_a_bounded_number_of_entries(system):
    ids = seed(system)
    files = CompanyFiles(system.db)
    refs = []
    for index in range(MAX_TASK_CONTEXT_ENTRIES + 1):
        files.write(f"tasks/{ids['earlier']}/n-{index}.md", "x")
        refs.append({"kind": "file", "ref": f"tasks/{ids['earlier']}/n-{index}.md"})

    with pytest.raises(ValueError, match=f"at most {MAX_TASK_CONTEXT_ENTRIES} entries"):
        system.manager.change_task_context(ids["task"], add=refs)
    assert system.db.get_task(ids["task"])["context"] is None


# ---------------------------------------------------------------------- what the attempt records


@pytest.mark.parametrize("executor", ["miniagent", "writer"])
def test_the_attempt_records_which_entries_and_versions_its_input_carried(system, executor):
    ids = seed(system)
    system.manager.change_task_context(ids["task"], add=[*references(ids), {"kind": "task", "ref": ids["stray"]}])
    system.manager.delete_task(ids["stray"])
    accepted = api(
        system,
        "POST",
        f"/company/tasks/{ids['task']}/transitions",
        {"target": "ready", "reason": "Go", "executor_type": "agent", "executor_id": executor},
    )
    assert accepted.status_code == 200, accepted.text

    done = system.execute(ids["task"])

    component = system.mini if executor == "miniagent" else system.writer
    sent_input = json.loads(component.model.input)
    assert NOTES in component.model.input and HANDOFF in component.model.input
    attempt = next(entry for entry in done["transitions"] if entry.get("attempt"))
    assert attempt["context_sent"] == context_sent(component.model.input)
    earlier = system.db.get_task(ids["earlier"])
    assert attempt["context_sent"] == [
        {"kind": "wiki", "ref": "wiki/glossary.md", "version": 1, "sent": "full"},
        {"kind": "goal", "ref": f"goals/{ids['goal']}/status.md", "version": 1, "sent": "full"},
        {"kind": "task", "ref": ids["earlier"], "version": earlier["updated_at"], "sent": "full", "handoff_version": 1},
        {"kind": "file", "ref": f"tasks/{ids['earlier']}/upgrade-notes.md", "version": 1, "sent": "full"},
        {"kind": "task", "ref": ids["stray"], "sent": "missing", "note": "Not sent: the Task no longer exists."},
    ]
    assert [item["ref"] for item in sent_input["context"]["items"]] == [item["ref"] for item in attempt["context_sent"]]
    shown = api(system, "GET", f"/company/tasks/{ids['task']}").json()
    assert shown["last_run"]["context_sent"] == attempt["context_sent"]
    assert next(e for e in shown["transitions"] if e.get("attempt"))["context_sent"] == attempt["context_sent"]


def test_an_attempt_with_no_context_records_none(system):
    ids = seed(system)
    system.accept(ids["task"])

    done = system.execute(ids["task"])

    attempt = next(entry for entry in done["transitions"] if entry.get("attempt"))
    assert "context_sent" not in attempt
    assert set(json.loads(system.mini.model.input)) == {"brief", "evidence", "execution_context"}
    assert api(system, "GET", f"/company/tasks/{ids['task']}").json()["last_run"]["context_sent"] == []


# ------------------------------------------------------------------------------- the async manager


async def test_the_async_manager_stores_changes_and_resolves_a_context(tmp_path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "company.db"))
    manager = AsyncCompanyManager(db)
    try:
        goal = await manager.create(name="Developer docs")
        earlier = await manager.create_task(goal_id=goal["id"], title="Write the upgrade notes")
        files = CompanyFiles(db)
        await files.awrite(f"tasks/{earlier['id']}/handoff.md", HANDOFF)
        await manager.write_wiki(goal_id=None, path="glossary.md", content="A Goal.", expected_version=0)
        task = await manager.create_task(
            goal_id=goal["id"],
            title="Write the breaking-changes section",
            user_id="alice",
            context=[{"kind": "task", "ref": earlier["id"]}],
        )
        assert [(e["kind"], e["ref"], e["added_by"]) for e in task["context"]] == [("task", earlier["id"], "alice")]

        changed = await manager.change_task_context(
            task["id"], add=[{"kind": "wiki", "ref": "wiki/glossary.md"}], remove=[task["context"][0]["id"]]
        )
        assert [e["ref"] for e in changed["context"]] == ["wiki/glossary.md"]
        with pytest.raises(ValueError, match="does not exist"):
            await manager.change_task_context(task["id"], add=[{"kind": "wiki", "ref": "wiki/absent.md"}])
        with pytest.raises(LookupError, match="Task not found"):
            await manager.change_task_context(task["id"], add=[{"kind": "task", "ref": "absent"}])
        with authorization_scope(lambda: task_run(goal["id"], task["id"])):
            with pytest.raises(PermissionError, match="A Task run cannot change what a Task is given"):
                await manager.change_task_context(task["id"], remove=[changed["context"][0]["id"]])
            with pytest.raises(PermissionError, match="A Task run cannot change what a Task is given"):
                await manager.create_task(title="More", context=[{"kind": "wiki", "ref": "wiki/glossary.md"}])
        with authorization_scope(lambda: routine_run("another-goal")):
            with pytest.raises(PermissionError, match="restricted to its configured Goal"):
                await manager.change_task_context(task["id"], add=[{"kind": "wiki", "ref": "wiki/glossary.md"}])

        await manager.change_task_context(task["id"], add=[{"kind": "task", "ref": earlier["id"]}])
        payload = json.loads(await _task_input(manager, await manager.get_task(task["id"])))
        wiki, attached = payload["context"]["items"]
        assert wiki["content"] == "A Goal." and attached["handoff"]["content"] == HANDOFF

        await manager.transition_task(task_id=task["id"], target="cancelled", reason="Not needed")
        with pytest.raises(ValueError, match="The context of a cancelled Task cannot change"):
            await manager.change_task_context(task["id"], add=[{"kind": "wiki", "ref": "wiki/glossary.md"}])
    finally:
        await db.close()


def test_two_changes_at_once_lose_neither(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    try:
        manager = CompanyManager(db)
        task = manager.create_task(title="Write the summary")
        for index in range(8):
            manager.write_wiki(goal_id=None, path=f"page-{index}.md", content="x", expected_version=0)

        def attach(index):
            return manager.change_task_context(task["id"], add=[{"kind": "wiki", "ref": f"wiki/page-{index}.md"}])

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(attach, range(8)))

        stored = db.get_task(task["id"])["context"]
        assert sorted(entry["ref"] for entry in stored) == [f"wiki/page-{index}.md" for index in range(8)]
    finally:
        db.close()


# --------------------------------------------------------------------- found in review of the change


def test_a_task_is_created_with_each_reference_once_and_within_the_limit(system):
    seed(system)
    wiki = {"kind": "wiki", "ref": "wiki/glossary.md"}

    twice = api(system, "POST", "/company/tasks", {"title": "Twice", "context": [wiki, wiki]})
    assert twice.status_code == 201 and [item["ref"] for item in twice.json()["context"]] == ["wiki/glossary.md"]
    over = api(system, "POST", "/company/tasks", {"title": "Sixty", "context": [wiki] * 60})
    assert over.status_code == 422, over.text
    with pytest.raises(ValueError, match=f"at most {MAX_TASK_CONTEXT_ENTRIES} entries"):
        system.manager.create_task(title="Sixty", context=[wiki] * 60)
    # The limit is on the list, so the same reference many times within it is still one entry.
    made = system.manager.create_task(title="Many", context=[wiki] * MAX_TASK_CONTEXT_ENTRIES)
    assert len(made["context"]) == 1
    assert system.manager.list_tasks(limit=100)[1] == 5


def test_a_list_over_the_limit_can_still_be_made_shorter(system):
    ids = seed(system)
    # A row written before the limit was applied at creation.
    entries = [{"id": f"e{n}", "kind": "wiki", "ref": f"wiki/p{n}.md"} for n in range(MAX_TASK_CONTEXT_ENTRIES + 5)]
    table = system.db._get_table("tasks")
    with system.db.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.id == ids["task"]).values(context=entries))

    shorter = system.manager.change_task_context(ids["task"], remove=["e0"])

    assert len(shorter["context"]) == MAX_TASK_CONTEXT_ENTRIES + 4
    with pytest.raises(ValueError, match="at most"):
        system.manager.change_task_context(ids["task"], add=[{"kind": "task", "ref": ids["earlier"]}])


@pytest.mark.parametrize("ref", ["wiki/glossary.md/", "wiki/../glossary.md", "tasks/x/a\\b.md"])
def test_a_malformed_path_is_refused_as_a_bad_request(system, ref):
    ids = seed(system)
    kind = "wiki" if ref.startswith("wiki") else "file"

    added = api(system, "POST", f"/company/tasks/{ids['task']}/context", {"kind": kind, "ref": ref})
    created = api(system, "POST", "/company/tasks", {"title": "Next", "context": [{"kind": kind, "ref": ref}]})

    assert added.status_code == 422 and "invalid path" in added.text, added.text
    assert created.status_code == 422 and "invalid path" in created.text, created.text
    assert system.db.get_task(ids["task"])["context"] is None


def test_an_attached_tasks_title_and_file_names_count_toward_the_total(system):
    ids = seed(system)
    files = CompanyFiles(system.db)
    folder = f"tasks/{ids['stray']}"
    for index in range(CONTEXT_FILE_NAMES + 10):
        files.write(f"{folder}/{'d' * 100}/{'n' * 100}-{index:03d}.md", "x")
    system.manager.update_task(ids["stray"], title="T" * (CONTEXT_TITLE_CHARS + 50))
    system.manager.change_task_context(ids["task"], add=[{"kind": "task", "ref": ids["stray"]}])

    (item,) = task_input(system, ids["task"])["context"]["items"]

    assert len(item["title"]) == CONTEXT_TITLE_CHARS and len(item["files"]) == CONTEXT_FILE_NAMES
    assert item["sent"] == "partial"
    assert item["note"] == f"files names {CONTEXT_FILE_NAMES} of {CONTEXT_FILE_NAMES + 11} files."

    # Many attached Tasks cannot pass the total through their names alone.
    others = []
    for number in range(8):
        other = system.manager.create_task(goal_id=ids["other"], title=f"Other {number}")
        for index in range(CONTEXT_FILE_NAMES):
            files.write(f"tasks/{other['id']}/{'d' * 100}/{'m' * 100}-{index:03d}.md", "x")
        others.append({"kind": "task", "ref": other["id"]})
    system.manager.change_task_context(ids["task"], add=others)
    items = task_input(system, ids["task"])["context"]["items"]
    named = sum(len(name) for item in items for name in item["files"]) + sum(len(item["title"]) for item in items)
    assert named <= CONTEXT_TOTAL_CHARS
    assert items[-1]["files"] == [] and "files names 0 of" in items[-1]["note"]


def test_an_attached_task_says_whether_its_result_is_a_failed_runs_error(system):
    ids = seed(system)
    table = system.db._get_table("tasks")
    failed = {"run_id": "r", "status": "ERROR", "content": "Rate limit exceeded"}
    with system.db.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.id == ids["stray"]).values(result=failed))
    system.manager.change_task_context(
        ids["task"], add=[{"kind": "task", "ref": ids["stray"]}, {"kind": "task", "ref": ids["earlier"]}]
    )

    errored, finished = task_input(system, ids["task"])["context"]["items"]

    assert (errored["run_status"], errored["result"]) == ("ERROR", "Rate limit exceeded")
    assert finished["run_status"] == "COMPLETED"


def test_attaching_what_is_already_attached_leaves_the_task_as_it_was(system, monkeypatch):
    import time

    ids = seed(system)
    first = system.manager.change_task_context(ids["task"], add=[{"kind": "wiki", "ref": "wiki/glossary.md"}])
    later = time.time() + 60
    monkeypatch.setattr(time, "time", lambda: later)

    again = system.manager.change_task_context(ids["task"], add=[{"kind": "wiki", "ref": "wiki/glossary.md"}])

    assert again["updated_at"] == first["updated_at"] and again["context"] == first["context"]
    # A real change still moves it.
    changed = system.manager.change_task_context(ids["task"], add=[{"kind": "task", "ref": ids["earlier"]}])
    assert changed["updated_at"] > first["updated_at"]


def test_the_company_tools_import_with_docstrings_stripped():
    import subprocess
    import sys

    done = subprocess.run(
        [sys.executable, "-OO", "-c", "import agno.tools.company, agno.os.manager.company_tasks"],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr[-400:]
