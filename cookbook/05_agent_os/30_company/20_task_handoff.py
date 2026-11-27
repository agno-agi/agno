"""Hand one Task's work to the next, without a model.

A Task run starts with its brief and its evidence. It sees no wiki page, no Goal
page and no earlier Task unless whoever coordinates the Task attaches it. This
script plays both parts: the first Task writes its notes and a handoff note in
its own folder, and the second Task is created with the first one attached.

An attached Task brings its title, status and result, the names of the files in
its folder, and the full text of tasks/<task-id>/handoff.md when it wrote one.
Each attached item is read when the run starts, and the attempt records which
items and versions the run was shown.

Prerequisites: Install agno and sqlalchemy.
Run: .venv/bin/python cookbook/05_agent_os/30_company/20_task_handoff.py
Try: Remove the entry with change_task_context(remove=[entry_id]) and build the input again.
"""

import asyncio
import json
from tempfile import TemporaryDirectory

from agno.company import CompanyManager
from agno.company.context import context_sent
from agno.company.execution import _task_input
from agno.company.files import CompanyFiles
from agno.db.sqlite import SqliteDb

# ---------------------------------------------------------------------------
# Hand off from one Task to the next
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=directory + "/company.db")
        manager = CompanyManager(db)
        files = CompanyFiles(db)

        goal = manager.create(name="Developer docs")
        project = manager.create_project(goal_id=goal["id"], name="3.3 migration guide")
        manager.transition_project(
            project_id=project["id"], target="active", reason="Approved"
        )

        # The first Task. Its executor writes what it produced, and what the next Task needs, in its folder.
        notes = manager.create_task(
            goal_id=goal["id"],
            project_id=project["id"],
            title="Write the upgrade notes",
            brief="List what changes for a developer who upgrades from 3.2 to 3.3.",
        )
        folder = f"tasks/{notes['id']}"
        files.write(
            folder + "/upgrade-notes.md",
            "Product is now Goal. product_id is now goal_id.\n",
        )
        files.write(
            folder + "/handoff.md",
            "For the breaking-changes section: a request that sends product_id is answered with 422.\n",
        )

        # The next Task builds on the first, so the first is attached when it is created.
        section = manager.create_task(
            goal_id=goal["id"],
            project_id=project["id"],
            title="Write the breaking-changes section",
            brief="Write the breaking-changes section of the 3.3 migration guide.",
            user_id="alice",
            context=[{"kind": "task", "ref": notes["id"]}],
        )
        (entry,) = section["context"]
        print("Attached:", entry["kind"], entry["ref"], "by", entry["added_by"])

        # More can be attached later, at any status before Done or Cancelled.
        section = manager.change_task_context(
            section["id"],
            add=[{"kind": "file", "ref": folder + "/upgrade-notes.md"}],
            user_id="alice",
        )
        assert [item["kind"] for item in section["context"]] == ["task", "file"]

        # What the run receives when it starts.
        message = asyncio.run(_task_input(manager, section))
        payload = json.loads(message)
        assert sorted(payload) == ["brief", "context", "evidence"]
        attached, file = payload["context"]["items"]
        print("The earlier Task:", attached["title"], "-", attached["status"])
        print("Its files:", attached["files"])
        print("Its handoff note:", attached["handoff"]["content"].strip())
        assert "answered with 422" in attached["handoff"]["content"]
        assert "product_id is now goal_id" in file["content"]
        # The names of a Task's files come with it. The text of a file comes only when the file is attached.
        assert "product_id is now goal_id" not in json.dumps(attached)

        # What the attempt records, so a person can see later what the worker was shown.
        for record in context_sent(message):
            print("Sent:", record)
        assert [record["sent"] for record in context_sent(message)] == ["full", "full"]

        # A Task nothing is attached to receives its brief and evidence only.
        alone = manager.create_task(title="Fix the typo on the pricing page")
        assert sorted(json.loads(asyncio.run(_task_input(manager, alone)))) == [
            "brief",
            "evidence",
        ]

        db.close()
        print("Task handoff example passed")
        print("No model call was made")
