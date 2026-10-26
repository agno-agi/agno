"""SQLite Product persistence, native schema and configuration round trips."""

from sqlalchemy import BigInteger, Text, inspect

from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.db.utils import DB_TABLE_NAME_KEYS, resolve_db_from_config


def test_reopen_schema_and_serialization(tmp_path):
    path = str(tmp_path / "company.db")
    db = SqliteDb(db_file=path, products_table="custom_products")
    manager = CompanyManager(db)
    product = manager.create(name="SDK", user_id="alice", metadata={"nested": {"x": [1, 2]}})
    assert manager.delete(product["id"])
    serialized = db.to_dict()
    assert serialized["products_table"] == "custom_products"
    assert "products_table" in DB_TABLE_NAME_KEYS
    db.close()
    reopened = SqliteDb.from_dict(serialized)
    manager = CompanyManager(reopened)
    assert manager.get(product["id"]) is None
    assert manager.get(product["id"], include_deleted=True)["metadata"] == {
        "archive_window_days": 14,
        "nested": {"x": [1, 2]},
    }
    assert manager.restore(product["id"])["user_id"] == "alice"
    columns = {c["name"]: c for c in inspect(reopened.db_engine).get_columns("custom_products")}
    assert set(columns) == {"id", "name", "purpose", "user_id", "metadata", "created_at", "updated_at", "deleted_at"}
    assert isinstance(columns["purpose"]["type"], Text)
    assert isinstance(columns["created_at"]["type"], BigInteger)
    assert columns["user_id"]["nullable"]
    indexes = {tuple(i["column_names"]) for i in inspect(reopened.db_engine).get_indexes("custom_products")}
    assert {("name",), ("user_id",), ("created_at",)} <= indexes
    resolved = resolve_db_from_config(serialized)
    assert resolved.products_table_name == "custom_products"
    assert resolved.get_product(product["id"]) is not None
    resolved.close()
    reopened.close()


def test_reads_do_not_create_products_table(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "empty.db"))
    assert db.get_products() == ([], 0)
    assert db.get_product("missing") is None
    assert db.update_product("missing", name="SDK") is None
    assert db.delete_product("missing") is False
    assert db.restore_product("missing") is None
    assert not db.table_exists(db.products_table_name)
    db.close()
