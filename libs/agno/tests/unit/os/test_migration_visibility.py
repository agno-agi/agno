"""AgentOS migration visibility: the startup warning, the opt-in auto_migrate_dbs,
and the read-only pending-migrations endpoints."""

import asyncio
import logging
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

LATEST = MigrationManager.available_versions[-1][1].public


@pytest.fixture
def stale_db():
    """A SQLite db whose evals table is stamped at 2.0.0, as an older Agno would have left it."""
    with tempfile.TemporaryDirectory() as tmp:
        db = SqliteDb(db_file=os.path.join(tmp, "stale.db"), id="stale-db")
        db._get_table(table_type="evals", create_table_if_not_found=True)
        db.upsert_schema_version(db.eval_table_name, "2.0.0")
        yield db


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


def test_startup_warns_about_pending_migrations_by_default(stale_db, caplog):
    agent_os = _os(stale_db)
    with caplog.at_level(logging.WARNING):
        _startup(agent_os)

    warning = next(r for r in caplog.records if "Pending database migrations" in r.getMessage())
    message = warning.getMessage()
    assert stale_db.eval_table_name in message
    assert f"2.0.0 -> {LATEST}" in message
    assert "agno db migrate" in message
    assert "/databases/all/migrate" in message
    assert "auto_migrate_dbs=True" in message
    # The warning is a report, not an action.
    assert stale_db.get_latest_schema_version(stale_db.eval_table_name) == "2.0.0"


def test_startup_does_not_warn_when_nothing_is_pending(stale_db, caplog):
    asyncio.run(MigrationManager(stale_db).up())
    agent_os = _os(stale_db)
    with caplog.at_level(logging.WARNING):
        _startup(agent_os)
    assert not any("Pending database migrations" in r.getMessage() for r in caplog.records)


def test_auto_migrate_dbs_applies_pending_migrations_at_startup(stale_db, caplog):
    agent_os = _os(stale_db, auto_migrate_dbs=True)
    with caplog.at_level(logging.WARNING):
        _startup(agent_os)

    assert stale_db.get_latest_schema_version(stale_db.eval_table_name) == LATEST
    assert asyncio.run(MigrationManager(stale_db).pending()) == []
    assert not any("Pending database migrations" in r.getMessage() for r in caplog.records)


def test_auto_migrate_dbs_defaults_off(stale_db):
    assert _os(stale_db).auto_migrate_dbs is False


def test_pending_endpoint_reports_and_does_not_change_anything(stale_db):
    client = TestClient(_os(stale_db).get_app())

    response = client.get("/databases/migrations/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["total_pending"] == 1
    [report] = body["databases"]
    assert report["db_id"] == "stale-db"
    assert report["remote"] is False
    assert report["pending"] == [
        {
            "table_type": "evals",
            "table_name": stale_db.eval_table_name,
            "current_version": "2.0.0",
            "target_version": LATEST,
        }
    ]
    assert stale_db.get_latest_schema_version(stale_db.eval_table_name) == "2.0.0"


def test_per_database_pending_endpoint(stale_db):
    client = TestClient(_os(stale_db).get_app())

    response = client.get("/databases/stale-db/migrations/pending")
    assert response.status_code == 200
    assert response.json()["pending"][0]["table_name"] == stale_db.eval_table_name

    assert client.get("/databases/nope/migrations/pending").status_code == 404


def test_migrate_endpoint_then_pending_is_empty(stale_db):
    client = TestClient(_os(stale_db).get_app())

    assert client.post("/databases/all/migrate").status_code == 200

    body = client.get("/databases/migrations/pending").json()
    assert body["total_pending"] == 0
    assert body["databases"][0]["pending"] == []
