"""Manage Company Projects without a model.

Prerequisites: Install agno and sqlalchemy.
Run: .venv/bin/python cookbook/05_agent_os/30_company/02_manage_projects.py
Try: Change the owner filters, transition reason, or target state.
"""

from tempfile import TemporaryDirectory

from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb

# ---------------------------------------------------------------------------
# Create and manage work
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=directory + "/company.db")
        manager = CompanyManager(db)
        product = manager.create(name="SDK", user_id="alice")
        first = manager.create_project(
            product_id=product["id"], name="Ship release", user_id="alice"
        )
        manager.create_project(
            product_id=product["id"], name="Plan next release", user_id="bob"
        )
        assert manager.list_projects()[1] == 2
        assert manager.list_projects(user_id="alice")[1] == 1
        manager.transition_project(
            project_id=first["id"],
            target="active",
            reason="Scope agreed",
            accepted_by="alice",
        )
        done = manager.transition_project(
            project_id=first["id"],
            target="done",
            reason="Outcome achieved",
            accepted_by="alice",
        )
        assert done["status"] == "done"
        assert manager.list_projects(status="done")[1] == 1
        assert manager.delete_project(first["id"], user_id="alice")
        assert manager.get_project(first["id"]) is None
        assert manager.restore_project(first["id"], user_id="alice")["status"] == "done"
        db.close()
        print("Company projects lifecycle passed")
