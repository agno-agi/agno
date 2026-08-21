"""AgentOS startup warning for pending schema migrations, and how a db constructed
with auto_migrate=True silences it by migrating during provisioning."""

import asyncio
import logging
import os
import tempfile

import pytest

from agno.agent import Agent
from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

LATEST = MigrationManager.available_versions[-1][1].public


@pytest.fixture
def stale_db_file():
    """A SQLite file whose evals table is stamped at 2.0.0, as an older Agno would have left it."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "stale.db")
        db = SqliteDb(db_file=path, id="stale-db")
        db._get_table(table_type="evals", create_table_if_not_found=True)
        db.upsert_schema_version(db.eval_table_name, "2.0.0")
        yield path


def _os(db, **kwargs):
    agent = Agent(name="a", id="a", db=db)
    return AgentOS(agents=[agent], db=db, telemetry=False, **kwargs)


def _startup(agent_os):
    """Run the app lifespan once (startup + shutdown)."""
    app = agent_os.get_app()

    async def _run():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(_run())


def _pending_warnings(caplog):
    return [r.getMessage() for r in caplog.records if "Pending database migrations" in r.getMessage()]


def test_startup_warns_about_pending_migrations_by_default(stale_db_file, caplog):
    db = SqliteDb(db_file=stale_db_file, id="stale-db")
    with caplog.at_level(logging.WARNING):
        _startup(_os(db))

    [message] = _pending_warnings(caplog)
    assert db.eval_table_name in message
    assert f"2.0.0 -> {LATEST}" in message
    assert "/databases/all/migrate" in message
    assert "auto_migrate=True" in message
    # The warning is a report, not an action.
    assert db.get_latest_schema_version(db.eval_table_name) == "2.0.0"


def test_startup_does_not_warn_when_nothing_is_pending(stale_db_file, caplog):
    db = SqliteDb(db_file=stale_db_file, id="stale-db")
    asyncio.run(MigrationManager(db).up())
    with caplog.at_level(logging.WARNING):
        _startup(_os(db))
    assert _pending_warnings(caplog) == []


def test_db_with_auto_migrate_is_migrated_during_startup_and_not_warned_about(stale_db_file, caplog):
    db = SqliteDb(db_file=stale_db_file, id="stale-db", auto_migrate=True)
    with caplog.at_level(logging.WARNING):
        _startup(_os(db))

    assert db.get_latest_schema_version(db.eval_table_name) == LATEST
    assert asyncio.run(MigrationManager(db).pending()) == []
    assert _pending_warnings(caplog) == []


def test_warning_still_fires_when_provisioning_is_disabled(stale_db_file, caplog):
    """auto_provision_dbs=False deployments own their schema, and are exactly the ones
    that need to hear about a pending migration."""
    db = SqliteDb(db_file=stale_db_file, id="stale-db")
    with caplog.at_level(logging.WARNING):
        _startup(_os(db, auto_provision_dbs=False))
    assert len(_pending_warnings(caplog)) == 1
