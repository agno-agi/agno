from pathlib import Path

import pytest

from agno.db.schema import DEFAULT_TABLE_NAMES, build_agno_metadata, compile_ddl_for_metadata
from agno.db.sqlite.sqlite import SqliteDb

try:
    from sqlalchemy import inspect
except ImportError:  # pragma: no cover - sqlalchemy should be installed for runtime
    inspect = None  # type: ignore


@pytest.mark.skipif(inspect is None, reason="SQLAlchemy not available")
def test_build_agno_metadata_registers_all_tables():
    metadata = build_agno_metadata(schema="ai")
    # Ensure every default table name is present (ignore schema prefix)
    actual_names = {table.name for table in metadata.tables.values()}
    assert set(DEFAULT_TABLE_NAMES.values()).issubset(actual_names)
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    ddl_statements = compile_ddl_for_metadata(metadata, dialect=engine.dialect)
    assert ddl_statements  # Should produce DDL strings


@pytest.mark.skipif(inspect is None, reason="SQLAlchemy not available")
def test_sqlite_create_all_tables_and_ddl(tmp_path: Path):
    db_path = tmp_path / "agno.db"
    db = SqliteDb(db_file=str(db_path))

    # Should be idempotent
    db.create_all_tables()
    db.create_all_tables()

    inspector = inspect(db.db_engine)
    existing_tables = inspector.get_table_names()
    for expected in DEFAULT_TABLE_NAMES.values():
        assert expected in existing_tables

    ddl_statements = db.get_create_all_tables_ddl()
    assert all(stmt.upper().startswith("CREATE TABLE") or "CREATE DATABASE" in stmt for stmt in ddl_statements)
