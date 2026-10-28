"""SQLite project table and optional-method defaults."""

import pytest

from agno.company import CompanyManager
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb


def test_project_storage(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "projects.db"))
    m = CompanyManager(db)
    try:
        parent = m.create(name="SDK")
        record = m.create_project(product_id=parent["id"], name="Work", user_id="alice")
        assert db.get_project(record["id"], user_id="alice") == record
        assert db.delete_project(record["id"], user_id="bob") is False
        assert db.delete_project(record["id"], user_id="alice") is True
        assert db.restore_project(record["id"], user_id="alice")["deleted_at"] is None
    finally:
        db.close()


def test_unsupported_project_methods():
    db = InMemoryDb()
    for method, args in [
        ("create_project", ({},)),
        ("get_project", ("id",)),
        ("get_projects", ()),
        ("update_project", ("id",)),
        ("delete_project", ("id",)),
        ("restore_project", ("id",)),
        ("transition_project", ("id", "cancelled", "Stop")),
    ]:
        with pytest.raises(NotImplementedError, match="Company projects not supported"):
            getattr(db, method)(*args)
