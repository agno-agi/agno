"""Record work that has no Goal, without a model.

A Goal is a standing aim and is optional. A single piece of work goes into the
Default Project, and an outcome that finishes is a Project of its own, with or
without a Goal.

Prerequisites: Install agno and sqlalchemy.
Run: .venv/bin/python cookbook/05_agent_os/30_company/18_work_without_a_goal.py
Try: Give the Project a Goal with goal_id, or tag the loose Task with one.
"""

from tempfile import TemporaryDirectory

from agno.agent import Agent
from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.registry import Registry

# ---------------------------------------------------------------------------
# Create work with no Goal
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=directory + "/company.db")
        writer = Agent(id="writer", db=db)
        manager = CompanyManager(db, registry=Registry(agents=[writer]))

        # A single piece of work names no Project and no Goal. It goes into the Default Project.
        typo = manager.create_task(
            title="Fix the typo on the pricing page",
            brief="Change 'recieve' to 'receive'.",
            user_id="alice",
        )
        default = manager.get_project(typo["project_id"])
        assert default["is_default"] and default["name"] == "Default"
        assert default["status"] == "active" and default["goal_id"] is None
        assert typo["goal_id"] is None
        print(f"Task '{typo['title']}' is in the {default['name']} Project")

        # The Default Project is always active, so the Task is accepted with no Project approval.
        ready = manager.transition_task(
            task_id=typo["id"],
            target="ready",
            reason="Small and clear",
            accepted_by="alice",
            executor_type="agent",
            executor_id="writer",
        )
        assert ready["status"] == "ready"

        # An outcome that finishes is a Project. This one serves no Goal.
        project = manager.create_project(
            name="50 paying customers by the end of March",
            outcome="50 paying customers on the hosted plan",
            user_id="alice",
        )
        assert project["goal_id"] is None and project["status"] == "proposed"
        first = manager.create_task(
            title="Count the paying customers today",
            project_id=project["id"],
            user_id="alice",
        )
        # A Task in a Project carries the Project's Goal, and this Project has none.
        assert first["goal_id"] is None
        manager.transition_project(
            project_id=project["id"], target="active", reason="Approved by alice"
        )
        print(f"Project '{project['name']}' is active with no Goal")

        # A Project may still serve a Goal, and the Default Project holds a Task of any Goal.
        goal = manager.create(name="Customer growth", user_id="alice")
        under_goal = manager.create_project(goal_id=goal["id"], name="Launch week")
        assert under_goal["goal_id"] == goal["id"]
        stray = manager.create_task(goal_id=goal["id"], title="Reply to the Acme lead")
        assert stray["project_id"] == default["id"] and stray["goal_id"] == goal["id"]

        # The Default Project never finishes and cannot be changed.
        for change in (
            lambda: manager.update_project(default["id"], name="Inbox"),
            lambda: manager.transition_project(
                project_id=default["id"], target="done", reason="All done"
            ),
            lambda: manager.delete_project(default["id"]),
        ):
            try:
                change()
            except ValueError as refusal:
                print(f"Refused: {refusal}")
            else:
                raise AssertionError("The Default Project changed")

        projects, total = manager.list_projects()
        assert total == 3
        for row in sorted(projects, key=lambda item: not item["is_default"]):
            open_tasks = (
                row["counts"]["tasks"]["backlog"] + row["counts"]["tasks"]["ready"]
            )
            print(
                f"{row['name']}: status={row['status']} goal={row['goal_id']} open_tasks={open_tasks}"
            )
        db.close()
    print("Work without a Goal example passed")
