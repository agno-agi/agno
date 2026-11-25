"""SQLite Goal persistence, native schema and configuration round trips."""

from sqlalchemy import BigInteger, Text, inspect

from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.db.utils import DB_TABLE_NAME_KEYS, resolve_db_from_config


def test_reopen_schema_and_serialization(tmp_path):
    path = str(tmp_path / "company.db")
    db = SqliteDb(db_file=path, goals_table="custom_goals")
    manager = CompanyManager(db)
    goal = manager.create(name="SDK", user_id="alice", metadata={"nested": {"x": [1, 2]}})
    assert manager.delete(goal["id"])
    serialized = db.to_dict()
    assert serialized["goals_table"] == "custom_goals"
    assert "goals_table" in DB_TABLE_NAME_KEYS
    db.close()
    reopened = SqliteDb.from_dict(serialized)
    manager = CompanyManager(reopened)
    assert manager.get(goal["id"]) is None
    assert manager.get(goal["id"], include_deleted=True)["metadata"] == {
        "archive_window_days": 14,
        "nested": {"x": [1, 2]},
    }
    assert manager.restore(goal["id"])["user_id"] == "alice"
    columns = {c["name"]: c for c in inspect(reopened.db_engine).get_columns("custom_goals")}
    assert set(columns) == {"id", "name", "objective", "user_id", "metadata", "created_at", "updated_at", "deleted_at"}
    assert isinstance(columns["objective"]["type"], Text)
    assert isinstance(columns["created_at"]["type"], BigInteger)
    assert columns["user_id"]["nullable"]
    indexes = {tuple(i["column_names"]) for i in inspect(reopened.db_engine).get_indexes("custom_goals")}
    assert {("name",), ("user_id",), ("created_at",)} <= indexes
    resolved = resolve_db_from_config(serialized)
    assert resolved.goals_table_name == "custom_goals"
    assert resolved.get_goal(goal["id"]) is not None
    resolved.close()
    reopened.close()


def test_reads_do_not_create_goals_table(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "empty.db"))
    assert db.get_goals() == ([], 0)
    assert db.get_goal("missing") is None
    assert db.update_goal("missing", name="SDK") is None
    assert db.delete_goal("missing") is False
    assert db.restore_goal("missing") is None
    assert not db.table_exists(db.goals_table_name)
    db.close()
