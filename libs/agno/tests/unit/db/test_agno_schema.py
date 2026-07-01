from __future__ import annotations

from pathlib import Path
from typing import Set

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, inspect  # noqa: E402

from agno.db.schema import (  # noqa: E402
    DEFAULT_TABLE_NAMES,
    build_agno_metadata,
    compile_ddl_for_metadata,
)
from agno.db.sqlite.sqlite import SqliteDb  # noqa: E402


def _tables_from_sqlite_ddl(ddl_statements: list[str]) -> Set[str]:
    """Apply DDL to an in-memory SQLite DB and reflect created tables."""
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        for stmt in ddl_statements:
            s = (stmt or "").strip()
            if not s:
                continue
            try:
                conn.exec_driver_sql(s)
            except Exception:
                # Ignore non-table/SQLite-incompatible statements; table existence is verified via reflection.
                continue

    return set(inspect(engine).get_table_names())


def test_build_agno_metadata_registers_all_tables_and_compiles_sqlite_ddl():
    assert DEFAULT_TABLE_NAMES, "DEFAULT_TABLE_NAMES must not be empty"
    expected_tables = set(DEFAULT_TABLE_NAMES.values())

    metadata = build_agno_metadata(schema="ai")

    # Behavior: metadata registers all expected table names
    actual_names = {table.name for table in metadata.tables.values()}
    assert expected_tables.issubset(actual_names)

    # Behavior: compiling DDL for SQLite yields statements that can create the expected tables
    engine = create_engine("sqlite:///:memory:")
    ddl_statements = compile_ddl_for_metadata(metadata, dialect=engine.dialect)

    assert ddl_statements, "compile_ddl_for_metadata() must return at least one statement"
    assert all(isinstance(s, str) and s.strip() for s in ddl_statements)

    created_tables = _tables_from_sqlite_ddl(ddl_statements)
    assert expected_tables.issubset(created_tables)


def test_sqlite_create_all_tables_and_ddl(tmp_path: Path):
    assert DEFAULT_TABLE_NAMES, "DEFAULT_TABLE_NAMES must not be empty"
    expected_tables = set(DEFAULT_TABLE_NAMES.values())

    db_path = tmp_path / "agno.db"
    db = SqliteDb(db_file=str(db_path))

    # Should be idempotent
    db.create_all_tables()
    db.create_all_tables()

    existing_tables = set(inspect(db.db_engine).get_table_names())
    assert expected_tables.issubset(existing_tables)

    ddl_statements = db.get_create_all_tables_ddl()
    assert ddl_statements, "get_create_all_tables_ddl() must return at least one statement"
    assert all(isinstance(s, str) and s.strip() for s in ddl_statements)

    ddl_tables = _tables_from_sqlite_ddl(ddl_statements)
    assert expected_tables.issubset(ddl_tables)
