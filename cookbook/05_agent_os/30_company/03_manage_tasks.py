"""Manage Company Tasks without a model.

Prerequisites: Install agno and sqlalchemy.
Run: .venv/bin/python cookbook/05_agent_os/30_company/03_manage_tasks.py
Try: Change the owner filters, transition reason, or target state.
"""

from tempfile import TemporaryDirectory

from agno.agent import Agent
from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.registry import Registry

# ---------------------------------------------------------------------------
# Create and manage work
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=directory + "/company.db")
        writer = Agent(id="writer", db=db)
        manager = CompanyManager(db, registry=Registry(agents=[writer]))
        product = manager.create(name="SDK", user_id="alice")
        project = manager.create_project(product_id=product["id"], name="Release")
        first = manager.create_task(
            product_id=product["id"],
            title="Ship release",
            project_id=project["id"],
            user_id="alice",
        )
        manager.create_task(
            product_id=product["id"],
            title="Plan next release",
            project_id=project["id"],
            user_id="bob",
        )
        assert manager.list_tasks()[1] == 2
        assert manager.list_tasks(user_id="alice")[1] == 1
        # In HTTP, Ready also checks the accepting caller's executor run permission.
        ready = manager.transition_task(
            task_id=first["id"],
            target="ready",
            reason="Scope and executor agreed",
            accepted_by="alice",
            executor_type="agent",
            executor_id="writer",
        )
        assert ready["accepted_by"] == "alice"
        try:
            manager.update_task(first["id"], brief="Changed after acceptance")
        except ValueError:
            print("Accepted scope is protected")
        else:
            raise AssertionError("Accepted scope changed")
        manager.transition_task(
            task_id=first["id"],
            target="backlog",
            reason="Clarify scope",
            accepted_by="alice",
        )
        manager.update_task(first["id"], brief="Write the release notes")
        manager.transition_task(
            task_id=first["id"],
            target="ready",
            reason="Reaccepted",
            accepted_by="alice",
            executor_type="agent",
            executor_id="writer",
        )
        manager.transition_task(
            task_id=first["id"],
            target="in_progress",
            reason="Work started",
            accepted_by="alice",
        )
        manager.transition_task(
            task_id=first["id"],
            target="in_review",
            reason="Results available",
            accepted_by="alice",
        )
        done = manager.transition_task(
            task_id=first["id"],
            target="done",
            reason="Results approved",
            accepted_by="alice",
        )
        assert done["status"] == "done"
        assert manager.list_tasks(status="done")[1] == 1
        assert manager.delete_task(first["id"], user_id="alice")
        assert manager.get_task(first["id"]) is None
        assert manager.restore_task(first["id"], user_id="alice")["status"] == "done"
        db.close()
        print("Company tasks lifecycle passed")
