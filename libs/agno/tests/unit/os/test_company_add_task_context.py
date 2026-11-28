"""Work a person asks for in chat is created accepted with its context in the same call.

add_company_task can queue the run as it creates the Task, so nothing can be attached afterwards.
The context it is given is checked before anything is created, and is kept when the Task is held
back for the person's confirmation.
"""

import asyncio
import json

import pytest

from agno.company.files import CompanyFiles
from agno.os.manager import company_tasks
from agno.os.manager.company_tasks import ACCEPTED_TASKS_PER_RUN, CompanyTaskTools
from agno.os.manager.prompts import COMPANY_INSTRUCTIONS
from tests.unit.os.test_company_decision_tools import (
    SCOPES,
    accept,
    call,
    context,
    records,
    system,  # noqa: F401
)

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

NOTES = "Breaking: Agent(storage=) is now Agent(db=)."


@pytest.fixture(autouse=True)
def fresh_run_counts():
    company_tasks._accepted_in_run.clear()
    yield
    company_tasks._accepted_in_run.clear()


def earlier_work(client, db):
    """An active Project with one Task that wrote its notes, and what attaching both looks like."""
    project, earlier = records(client)
    path = f"tasks/{earlier['id']}/upgrade-notes.md"
    CompanyFiles(db).write(path, NOTES)
    return project, earlier, [{"kind": "task", "ref": earlier["id"]}, {"kind": "file", "ref": path}]


def add(agent_os, run_context, title="Write the breaking-changes section", start=False, **arguments):
    arguments.setdefault("brief", "Write the breaking-changes section of the 3.3 migration guide.")
    return call(agent_os, "add_company_task", run_context, title=title, start=start, **arguments)


def titled(db, title):
    return next((row for row in db.get_tasks(limit=100)[0] if row["title"] == title), None)


def test_asked_work_is_created_accepted_with_its_context(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, earlier, attached = earlier_work(client, db)

    reply = add(agent_os, context(), project_id=project["id"], context=attached)

    task = titled(db, "Write the breaking-changes section")
    assert reply.startswith("Added") and "Ready and not started" in reply, reply
    assert (task["status"], task["accepted_by"]) == ("ready", "alice")
    assert [(e["kind"], e["ref"], e["added_by"]) for e in task["context"]] == [
        ("task", earlier["id"], "alice"),
        ("file", f"tasks/{earlier['id']}/upgrade-notes.md", "alice"),
    ]


def test_asked_to_do_the_work_its_run_is_queued_with_what_was_attached(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, earlier, attached = earlier_work(client, db)

    reply = add(
        agent_os,
        context(),
        start=True,
        project_id=project["id"],
        executor_type="agent",
        executor_id="writer",
        context=attached,
    )

    task = titled(db, "Write the breaking-changes section")
    assert reply.startswith("Added") and "Queued" in reply, reply
    # The run this one call queued already holds the notes: there was no later moment to attach them.
    job = asyncio.run(queue.store.get_job(task["job_id"]))
    sent = json.loads(job["payload"]["input"])
    assert [item["ref"] for item in sent["context"]["items"]] == [entry["ref"] for entry in attached]
    assert NOTES in job["payload"]["input"]
    attempt = [entry for entry in task["transitions"] if entry.get("attempt")][-1]
    assert [(r["kind"], r["sent"]) for r in attempt["context_sent"]] == [("task", "full"), ("file", "full")]


@pytest.mark.parametrize(
    "reference, refusal",
    [
        ({"kind": "wiki", "ref": "wiki/absent.md"}, "wiki/absent.md does not exist"),
        ({"kind": "task", "ref": "no-such-task"}, "Task not found: no-such-task"),
        ({"kind": "file", "ref": "notes/ideas.md"}, "A file reference names a file a Task wrote"),
    ],
)
@pytest.mark.parametrize("start", [False, True])
def test_a_reference_that_names_nothing_is_refused_before_anything_is_created(system, reference, refusal, start):  # noqa: F811
    client, db, agent_os, queue = system
    project, earlier, attached = earlier_work(client, db)
    before = db.get_tasks(limit=100)[1]

    reply = add(agent_os, context(), start=start, project_id=project["id"], context=[*attached, reference])

    assert reply.startswith("Not done") and refusal in reply, reply
    assert db.get_tasks(limit=100)[1] == before
    # A Task that was not created does not use one of the run's places.
    for number in range(ACCEPTED_TASKS_PER_RUN):
        assert add(agent_os, context(), title=f"Task {number}").startswith("Added")


@pytest.mark.parametrize("kind, missing", [("file", "wiki:read"), ("task", "wiki:read"), ("task", "tasks:read")])
@pytest.mark.parametrize("start", [False, True])
def test_a_reference_the_person_may_not_read_is_refused_before_anything_is_created(system, kind, missing, start):  # noqa: F811
    client, db, agent_os, queue = system
    project, earlier, attached = earlier_work(client, db)
    reference = next(entry for entry in attached if entry["kind"] == kind)
    before = db.get_tasks(limit=100)[1]
    allowed = [scope for scope in SCOPES if scope != missing]

    reply = add(agent_os, context(allowed), start=start, project_id=project["id"], context=[reference])

    assert reply.startswith("Not done"), reply
    assert db.get_tasks(limit=100)[1] == before
    # The same person adds the Task with nothing attached.
    assert add(agent_os, context(allowed), project_id=project["id"]).startswith("Added")


def test_a_task_held_back_past_five_in_one_run_keeps_its_context(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, earlier, attached = earlier_work(client, db)
    for number in range(ACCEPTED_TASKS_PER_RUN):
        assert add(agent_os, context(), title=f"Task {number}").startswith("Added")

    reply = add(
        agent_os,
        context(),
        start=True,
        project_id=project["id"],
        executor_type="agent",
        executor_id="writer",
        context=attached,
    )

    held = titled(db, "Write the breaking-changes section")
    assert reply.startswith("Recorded") and "as a proposal, not accepted" in reply, reply
    assert (held["status"], held["accepted_by"], held["job_id"]) == ("backlog", None, None)
    assert [entry["ref"] for entry in held["context"]] == [entry["ref"] for entry in attached]
    # The person's confirmation accepts it with what was attached.
    assert accept(agent_os, context(), held).startswith("Accepted")
    accepted = db.get_task(held["id"])
    assert accepted["status"] == "ready" and accepted["context"] == held["context"]


def test_a_task_held_back_for_an_executor_that_pushes_code_keeps_its_context(system, monkeypatch):  # noqa: F811
    client, db, agent_os, queue = system
    from tests.unit.os.test_company_sandboxed_task_goal import writer_pushes_code

    project, earlier, attached = earlier_work(client, db)
    writer_pushes_code(monkeypatch, client, agent_os, goal_id=project["goal_id"])

    reply = add(
        agent_os,
        context(),
        start=True,
        project_id=project["id"],
        executor_type="agent",
        executor_id="writer",
        context=attached,
    )

    held = titled(db, "Write the breaking-changes section")
    assert reply.startswith("Recorded") and "runs in a sandbox and can push code" in reply, reply
    assert (held["status"], held["accepted_by"], held["job_id"]) == ("backlog", None, None)
    assert [(e["kind"], e["added_by"]) for e in held["context"]] == [("task", "alice"), ("file", "alice")]


def test_the_tool_and_the_prompt_say_one_thing_about_what_a_run_is_given():
    functions = CompanyTaskTools.__dict__
    described = functions["aadd_company_task"].__doc__
    assert "given only this brief" not in described and "CONTEXT_KINDS" not in described
    assert "With start true the" in described and "attach here: there is no later moment" in described
    assert "It brings file names, not file text" in described
    # One bullet, directly after the one that says to add asked work accepted.
    lines = COMPANY_INSTRUCTIONS.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("- A Task run starts with only its brief"))
    assert "pauses for the person's confirmation." in lines[index - 1]
    assert "adding or proposing a Task" in lines[index + 1]
    assert "other than Mini Agent" not in COMPANY_INSTRUCTIONS


def test_moving_a_task_keeps_its_context_and_its_next_run_is_given_it(system):  # noqa: F811
    client, db, agent_os, queue = system
    project, earlier, attached = earlier_work(client, db)
    # Added to be started later, in the Default Project, then moved into the Project it serves.
    assert add(agent_os, context(), executor_type="agent", executor_id="writer", context=attached).startswith("Added")
    task = titled(db, "Write the breaking-changes section")
    (acceptance,) = task["transitions"]
    assert acceptance["start_on_request"] is True and len(task["context"]) == 2

    reply = call(agent_os, "move_company_task", context(), task_id=task["id"], project_id=project["id"])

    moved = db.get_task(task["id"])
    assert moved["project_id"] == project["id"], reply
    assert moved["context"] == task["context"]
    started = call(agent_os, "start_company_task", context(), task_id=task["id"])
    assert "Queued" in started, started
    job = asyncio.run(queue.store.get_job(db.get_task(task["id"])["job_id"]))
    assert NOTES in job["payload"]["input"]
