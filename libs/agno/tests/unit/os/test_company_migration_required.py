"""AgentOS starts on a database written by agno 3.2 and leaves it as it is. Company waits for the migration.

The operator migrates with ``MigrationManager(db).up()`` or ``POST /databases/all/migrate``, and Company
then starts with no restart.

Each test runs on SQLite and on PostgreSQL, with the sync and the async adapter. The database is the
3.2.0 fixture of the migration tests, stamped the way 3.2.0 stamps it.
"""

import asyncio
import json
import logging
from typing import Any, List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from agno.company import Goal, Routine
from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.versions import v3_3_0
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig
from agno.utils.log import log_error
from tests.unit.db import test_v3_3_0_company_goals_migration as migration_tests
from tests.unit.db.test_v3_3_0_company_goals_migration import (
    ARCHIVED_GOAL,
    GOAL,
    _stamp_3_0_0,
    _write_3_2_0,
    _write_company_3_2_0,
)

# The database fixtures of the migration tests: one database of each kind, removed after the test.
postgres_available = migration_tests.postgres_available
databases = migration_tests.databases
database = migration_tests.database

MIGRATED = (
    "agno_company_goals",
    "agno_company_sources",
    "agno_company_projects",
    "agno_company_tasks",
    "agno_schedules",
    "agno_schedule_runs",
)


@pytest.fixture
def logged():
    """Every record agno logs at INFO or above while the test runs.

    agno logs through one of three loggers, and an earlier test in the same process can leave
    any of them active. All three are listened to, and the capture is checked before the test.
    """
    records: List[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collect(level=logging.INFO)
    loggers = [logging.getLogger(name) for name in ("agno", "agno-team", "agno-workflow")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    # An empty list below then means nothing was logged, not that nothing was heard.
    log_error("capture check")
    assert [record.getMessage() for record in records] == ["capture check"]
    records.clear()
    yield records
    for logger, level in zip(loggers, levels):
        logger.removeHandler(handler)
        logger.setLevel(level)


def _errors(records: List[logging.LogRecord]) -> List[str]:
    return [record.getMessage() for record in records if record.levelno >= logging.ERROR]


def _about_migrations(records: List[logging.LogRecord]) -> List[str]:
    return [record.getMessage() for record in records if "migrat" in record.getMessage().lower()]


@pytest.fixture
def ups(monkeypatch):
    """One entry for each call of MigrationManager.up."""
    calls: List[Any] = []
    real = MigrationManager.up

    async def counted(self, *args, **kwargs):
        calls.append(self.db)
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(MigrationManager, "up", counted)
    return calls


def _write_3_2_0_database(database) -> None:
    _write_3_2_0(database)
    _stamp_3_0_0(database)


def _agent_os(database, **kwargs) -> AgentOS:
    return AgentOS(db=database.db(), company=CompanyConfig(), telemetry=False, **kwargs)


def _goal_ids(client: TestClient) -> List[str]:
    listed = client.get("/company/goals", params={"include_deleted": True, "limit": 100})
    assert listed.status_code == 200, listed.text
    return sorted(goal["id"] for goal in listed.json()["data"])


def _assert_renamed(database) -> None:
    described = database.describe(rows=False)
    assert "agno_company_products" not in described and "agno_company_products_details" not in described
    assert "objective" in described["agno_company_goals"]["columns"]
    for name in ("agno_company_projects", "agno_company_tasks", "agno_company_sources"):
        assert "goal_id" in described[name]["columns"] and "product_id" not in described[name]["columns"]
    versions = database.versions()
    assert {name: versions[name] for name in MIGRATED} == {name: "3.3.0" for name in MIGRATED}


def _assert_refused(response) -> None:
    assert response.status_code == 500, response.text
    body = response.json()
    assert body["error_id"] == "migration_required_error"
    assert "MigrationManager(db).up()" in body["detail"]
    assert "POST /databases/all/migrate" in body["detail"]


@pytest.mark.parametrize("auto_provision_dbs", [True, False])
def test_a_3_2_0_database_is_not_migrated_and_company_waits_for_the_operator(database, ups, logged, auto_provision_dbs):
    _write_3_2_0_database(database)
    before = database.describe()

    with TestClient(_agent_os(database, auto_provision_dbs=auto_provision_dbs).get_app()) as client:
        # One line at the start says Company waits for the migration.
        errors = _errors(logged)
        assert len(errors) == 1, errors
        assert errors[0].startswith("Company is not started: ") and "MigrationManager(db).up()" in errors[0]
        # Everything outside Company works.
        assert client.get("/health").status_code == 200
        assert client.get("/sessions").status_code == 200
        # Company says what it needs.
        _assert_refused(client.get("/company/goals"))
        _assert_refused(client.post("/company/goals", json={"name": "Docs"}))
        _assert_refused(client.get("/company/projects"))
        assert ups == []
        company = [name for name in before if name.startswith("agno_company")]
        after = database.describe()
        assert {name: after[name] for name in company} == {name: before[name] for name in company}

        # The operator migrates, and Company works without a restart.
        assert client.post("/databases/all/migrate").status_code == 200
        assert {GOAL, ARCHIVED_GOAL} <= set(_goal_ids(client))
        assert client.get(f"/company/goals/{GOAL}").json()["objective"] == (
            "Keep this AgentOS current, secure and working."
        )
    _assert_renamed(database)

    # The next start finds nothing to do.
    logged.clear()
    ups.clear()
    with TestClient(_agent_os(database).get_app()) as client:
        assert GOAL in _goal_ids(client)
    assert ups == [] and _errors(logged) == []


def test_without_company_nothing_is_migrated(database, ups, logged):
    _write_3_2_0_database(database)
    before, versions = database.describe(rows=False), database.versions()

    with TestClient(AgentOS(db=database.db(), telemetry=False).get_app()) as client:
        assert client.get("/health").status_code == 200

    # Provisioning can add missing tables, as on agno 3.2. No table that was there changes.
    assert ups == []
    assert _about_migrations(logged) == [] and _errors(logged) == []
    after = database.describe(rows=False)
    assert {name: after[name] for name in before} == before
    assert {name: database.versions()[name] for name in versions} == versions


def test_a_goal_declared_in_code_is_applied_once_the_operator_migrates(database, logged):
    _write_3_2_0_database(database)
    agent_os = AgentOS(
        db=database.db(),
        company=CompanyConfig(goals=[Goal(id="declared", name="Declared in code", objective="Start late.")]),
        telemetry=False,
    )

    with TestClient(agent_os.get_app()) as client:
        _assert_refused(client.get("/company/goals"))
        assert client.post("/databases/all/migrate").status_code == 200
        assert {GOAL, ARCHIVED_GOAL, "declared"} <= set(_goal_ids(client))
        assert client.get("/company/goals/declared").json()["objective"] == "Start late."
    _assert_renamed(database)


def test_a_goals_table_named_by_the_user_is_migrated_by_the_endpoint(database, logged):
    _write_company_3_2_0(database, goals_table="my_products")
    _stamp_3_0_0(database)
    agent_os = AgentOS(db=database.db(products_table="my_products"), company=CompanyConfig(), telemetry=False)

    with TestClient(agent_os.get_app()) as client:
        _assert_refused(client.get(f"/company/goals/{GOAL}"))
        assert client.post("/databases/all/migrate").status_code == 200
        assert client.get(f"/company/goals/{GOAL}").json()["objective"] == (
            "Keep this AgentOS current, secure and working."
        )

    described = database.describe(rows=False)
    assert "objective" in described["my_products"]["columns"] and "agno_company_goals" not in described
    assert database.versions()["my_products"] == "3.3.0"


def test_the_migrate_endpoint_answers_for_the_migration_when_company_cannot_start(database, logged, monkeypatch):
    _write_3_2_0_database(database)

    with TestClient(_agent_os(database).get_app()) as client:

        async def cannot_start(agent_os: Any) -> bool:
            raise ValueError("Routine name is already used by another schedule")

        monkeypatch.setattr("agno.company.bootstrap._start_company", cannot_start)
        logged.clear()

        migrated = client.post("/databases/all/migrate")

        # The migration is done, and that is what the endpoint answers. Company's own problem is logged.
        assert migrated.status_code == 200, migrated.text
        assert _errors(logged) == [
            "Company did not start after the migration: ValueError: Routine name is already used by another schedule"
        ]
    _assert_renamed(database)


def test_a_new_database_starts_with_no_migration(database, ups, logged):
    with TestClient(_agent_os(database).get_app()) as client:
        assert _goal_ids(client) == []
        assert client.post("/company/goals", json={"name": "Docs"}).status_code == 201

    assert ups == []
    assert _about_migrations(logged) == []
    assert _errors(logged) == []
    assert not [name for name in database.describe(rows=False) if "product" in name]

    with TestClient(_agent_os(database).get_app()) as client:
        assert len(_goal_ids(client)) == 1
    assert ups == []
    assert _about_migrations(logged) == []


def test_a_table_another_session_holds_fails_the_migration_and_it_can_be_run_again(database, logged, monkeypatch):
    if not database.postgres:
        pytest.skip("SQLite has no lock on one table; a locked file fails the migration at once")
    _write_3_2_0_database(database)
    monkeypatch.setattr(v3_3_0, "LOCK_TIMEOUT_SECONDS", 1)
    engine = create_engine(database.url)
    reader = engine.connect()
    try:
        # A dump, or a session left open in a transaction, has read the table the migration renames.
        reader.execute(text(f"SELECT count(*) FROM {database._ref('agno_company_products')}"))
        with TestClient(_agent_os(database).get_app(), raise_server_exceptions=False) as client:
            failed = client.post("/databases/all/migrate")
            assert failed.status_code == 207 and "lock timeout" in failed.text, failed.text
            _assert_refused(client.get("/company/goals"))

            reader.rollback()
            assert client.post("/databases/all/migrate").status_code == 200
            assert GOAL in _goal_ids(client)
    finally:
        reader.close()
        engine.dispose()
    _assert_renamed(database)


# ----------------------------------- the Company database is migrated, the schedules are not


def _declared(routines: bool = True) -> List[Goal]:
    routine = Routine(name="weekly", cron_expr="0 9 * * 1", instructions="Review.", enabled=False, auto_accept=False)
    return [Goal(id="docs", name="Docs", objective="Keep the docs accurate.", routines=[routine] if routines else [])]


def _two_databases(databases, goals: List[Goal], **kwargs) -> Any:
    """An AgentOS whose Company database and schedules are two databases, as a new one each call."""
    company, schedules = databases(), databases()

    def build(declared: List[Goal] = goals, **more: Any) -> AgentOS:
        return AgentOS(
            db=schedules.db(),
            company=CompanyConfig(db=company.db(), goals=declared, model=OpenAIResponses(id="offline")),
            telemetry=False,
            **kwargs,
            **more,
        )

    return company, schedules, build


def _store_the_routine_as_3_2_0_did(schedules) -> str:
    """Put the Routine back in the form agno 3.2.0 stored, and stamp its table as 3.2.0 did."""
    db = schedules.sync_db()
    row = db.get_schedule_by_name("docs.weekly")
    metadata = {key: value for key, value in row["payload"]["metadata"].items() if key != "goal_id"}
    payload = json.dumps({**row["payload"], "metadata": {"product_id": "docs", **metadata}})
    cast = "CAST(:payload AS JSONB)" if schedules.postgres else ":payload"
    schedules.execute(
        f"UPDATE {schedules._ref('agno_schedules')} SET payload = {cast} WHERE id = :id", payload=payload, id=row["id"]
    )
    _stamp_3_0_0(schedules)
    return row["id"]


def test_a_routine_declared_in_code_does_not_stop_the_start(databases, logged):
    company, schedules, build = _two_databases(databases, _declared())
    with TestClient(build().get_app()) as client:
        assert [routine["name"] for routine in client.get("/company/routines").json()["data"]] == ["docs.weekly"]
    routine_id = _store_the_routine_as_3_2_0_did(schedules)
    logged.clear()

    # The Company database has nothing to migrate. The schedules were not migrated.
    with TestClient(build().get_app()) as client:
        errors = _errors(logged)
        assert len(errors) == 1, errors
        assert errors[0].startswith("Company is not started: ") and routine_id in errors[0]
        assert client.get("/health").status_code == 200
        _assert_refused(client.get("/company/routines"))
        _assert_refused(client.get(f"/company/routines/{routine_id}"))

        assert client.post("/databases/all/migrate").status_code == 200

        listed = client.get("/company/routines", params={"goal_id": "docs"}).json()["data"]
        assert [(routine["id"], routine["name"]) for routine in listed] == [(routine_id, "docs.weekly")]
        assert client.get(f"/company/routines/{routine_id}").status_code == 200


def test_a_stored_routine_says_the_migration_is_needed(databases, logged):
    company, schedules, build = _two_databases(databases, _declared())
    with TestClient(build().get_app()):
        pass
    routine_id = _store_the_routine_as_3_2_0_did(schedules)

    # The Routine is no longer declared in code, so the start does not touch it.
    with TestClient(build(_declared(routines=False)).get_app()) as client:
        assert client.get("/company/goals/docs").status_code == 200
        _assert_refused(client.get("/company/routines"))
        _assert_refused(client.get("/company/routines", params={"goal_id": "docs"}))
        _assert_refused(client.get(f"/company/routines/{routine_id}"))
        _assert_refused(client.post(f"/company/routines/{routine_id}/trigger"))

        assert client.post("/databases/all/migrate").status_code == 200

        assert [routine["id"] for routine in client.get("/company/routines").json()["data"]] == [routine_id]
        assert client.get(f"/company/routines/{routine_id}").json()["name"] == "docs.weekly"


# ------------------------------------------------------------------- a migration that was interrupted


def test_a_migration_that_stops_before_the_schedules_is_finished_by_the_endpoint(database, logged, monkeypatch):
    _write_3_2_0_database(database)

    def stop(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("stopped partway")

    with monkeypatch.context() as patch:
        patch.setattr(v3_3_0, "_rename_routines", stop)
        with pytest.raises(RuntimeError, match="stopped partway"):
            asyncio.run(MigrationManager(database.db()).up())
    versions = database.versions()
    assert versions["agno_sessions"] == "3.3.0" and versions["agno_schedules"] == "3.0.0"

    with TestClient(_agent_os(database).get_app()) as client:
        _assert_refused(client.get("/company/routines"))

        # The sessions table, which the endpoint reads as the version of the database, is at 3.3.0.
        # The schedules are not.
        migrated = client.post("/databases/all/migrate", params={"target_version": "3.3.0"})

        assert migrated.status_code == 200, migrated.text
        assert client.get("/company/routines").status_code == 200
    _assert_renamed(database)


@pytest.mark.parametrize("stamped_as", ["products", "goals"])
def test_stamps_at_3_3_0_do_not_hide_tables_in_their_3_2_0_shape(database, ups, logged, stamped_as):
    _write_3_2_0(database)
    versions = database._ref("agno_schema_versions")
    database.execute(f"UPDATE {versions} SET version = '3.3.0'")
    if stamped_as == "goals":
        database.execute(
            f"UPDATE {versions} SET table_name = replace(table_name, 'agno_company_products', 'agno_company_goals')"
        )

    with TestClient(_agent_os(database).get_app()) as client:
        _assert_refused(client.get("/company/goals"))
        assert client.post("/databases/all/migrate").status_code == 200
        assert GOAL in _goal_ids(client)

    # The products table held the only copy of the Goals. Nothing said to drop it.
    assert not [record.getMessage() for record in logged if "drop" in record.getMessage()]
    assert len(ups) == 1
    described = database.describe(rows=False)
    assert "agno_company_products" not in described and "objective" in described["agno_company_goals"]["columns"]


def test_agent_os_starts_without_sqlalchemy(monkeypatch):
    import sys

    from agno.db.in_memory import InMemoryDb

    # An AgentOS on a database that is not SQL is installed without SQLAlchemy.
    for name in [name for name in sys.modules if name == "sqlalchemy" or name.startswith("sqlalchemy.")]:
        monkeypatch.setitem(sys.modules, name, None)

    with TestClient(AgentOS(db=InMemoryDb(), telemetry=False).get_app()) as client:
        assert client.get("/health").status_code == 200
