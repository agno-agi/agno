"""MigrationManager.pending(): the read-only check behind the AgentOS startup warning,
the /databases/migrations/pending endpoint, and `agno db migrate --dry-run`."""

import asyncio
import os
import tempfile

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import SqliteDb


@pytest.fixture
def db_file():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "pending.db")


def test_fresh_database_has_nothing_pending(db_file):
    """No tables exist yet, so nothing is pending: missing tables are created at the
    current schema on first use, not migrated."""
    db = SqliteDb(db_file=db_file)
    assert asyncio.run(MigrationManager(db).pending()) == []


def test_table_stamped_behind_latest_is_pending(db_file):
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="evals", create_table_if_not_found=True)
    # A freshly created table is stamped at the latest version; rewind it to simulate
    # a table created by an older Agno release.
    db.upsert_schema_version(db.eval_table_name, "2.0.0")

    pending = asyncio.run(MigrationManager(db).pending())

    assert [p.table_name for p in pending] == [db.eval_table_name]
    item = pending[0]
    assert item.table_type == "evals"
    assert item.current_version == "2.0.0"
    assert item.target_version == MigrationManager.available_versions[-1][1].public
    assert item.to_dict() == {
        "table_type": "evals",
        "table_name": db.eval_table_name,
        "current_version": "2.0.0",
        "target_version": MigrationManager.available_versions[-1][1].public,
    }


def test_pending_is_read_only(db_file):
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="evals", create_table_if_not_found=True)
    db.upsert_schema_version(db.eval_table_name, "2.0.0")

    asyncio.run(MigrationManager(db).pending())
    asyncio.run(MigrationManager(db).pending())

    assert db.get_latest_schema_version(db.eval_table_name) == "2.0.0"


def test_up_clears_pending(db_file):
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="evals", create_table_if_not_found=True)
    db.upsert_schema_version(db.eval_table_name, "2.0.0")
    assert asyncio.run(MigrationManager(db).pending())

    asyncio.run(MigrationManager(db).up())

    assert asyncio.run(MigrationManager(db).pending()) == []


def test_current_table_is_not_pending(db_file):
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="evals", create_table_if_not_found=True)
    assert asyncio.run(MigrationManager(db).pending()) == []


def test_in_memory_db_reports_nothing_pending_after_migrating():
    """InMemoryDb claims every table exists and defaults to 2.0.0, so it reports every
    migratable table pending until up() stamps them. Either way pending() must not raise."""
    db = InMemoryDb()
    before = asyncio.run(MigrationManager(db).pending())
    assert {p.table_type for p in before} == set(MigrationManager.TABLE_TYPE_TO_ATTR)
    asyncio.run(MigrationManager(db).up())
    assert asyncio.run(MigrationManager(db).pending()) == []
