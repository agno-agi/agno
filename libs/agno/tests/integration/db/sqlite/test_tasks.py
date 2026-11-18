"""SQLite task table and optional-method defaults."""

import pytest

from agno.company import CompanyManager
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb


def test_task_storage(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "tasks.db"))
    m = CompanyManager(db)
    try:
        parent = m.create(name="SDK")
        project = m.create_project(product_id=parent["id"], name="Release")
        m.transition_project(project_id=project["id"], target="active", reason="Approved")
        record = m.create_task(product_id=parent["id"], title="Work", project_id=project["id"], user_id="alice")
        assert db.get_task(record["id"], user_id="alice") == record
        assert db.delete_task(record["id"], user_id="bob") is False
        assert db.delete_task(record["id"], user_id="alice") is True
        assert db.restore_task(record["id"], user_id="alice")["deleted_at"] is None
    finally:
        db.close()


def test_unsupported_task_methods():
    db = InMemoryDb()
    for method, args in [
        ("create_task", ({},)),
        ("get_task", ("id",)),
        ("get_tasks", ()),
        ("update_task", ("id",)),
        ("delete_task", ("id",)),
        ("restore_task", ("id",)),
        ("transition_task", ("id", "cancelled", "Stop")),
    ]:
        with pytest.raises(NotImplementedError, match="Company tasks not supported"):
            getattr(db, method)(*args)
