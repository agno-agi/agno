"""AgentOS migrates a database written by agno 3.2 as it starts, and still starts when it cannot.

Each test runs on SQLite and on PostgreSQL, with the sync and the async adapter. The database is the
3.2.0 fixture of the migration tests, stamped the way 3.2.0 stamps it.
"""

import logging
import threading
from typing import Any, List

import pytest
from fastapi.testclient import TestClient

from agno.company import Goal
from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.versions import v3_3_0
from agno.os import AgentOS, CompanyConfig
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
    """Every record agno logs at INFO or above while the test runs."""
    records: List[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collect(level=logging.INFO)
    logger = logging.getLogger("agno")
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield records
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


def test_a_3_2_0_database_is_migrated_when_agent_os_starts(database, ups, logged):
    _write_3_2_0_database(database)

    with TestClient(_agent_os(database).get_app()) as client:
        assert GOAL in _goal_ids(client)
        goal = client.get(f"/company/goals/{GOAL}").json()
        assert goal["objective"] == "Keep this AgentOS current, secure and working."
        created = client.post("/company/goals", json={"name": "Docs", "objective": "Keep the docs accurate."})
        assert created.status_code == 201, created.text

    _assert_renamed(database)
    assert len(ups) == 1
    assert _errors(logged) == []

    # A second start finds nothing to migrate.
    ups.clear()
    logged.clear()
    schema = database.describe(rows=False)
    with TestClient(_agent_os(database).get_app()) as client:
        assert GOAL in _goal_ids(client)
    assert ups == []
    assert _about_migrations(logged) == []
    assert database.describe(rows=False) == schema


def test_a_goals_table_named_by_the_user_is_migrated_when_agent_os_starts(database, ups, logged):
    _write_company_3_2_0(database, goals_table="my_products")
    _stamp_3_0_0(database)
    agent_os = AgentOS(db=database.db(products_table="my_products"), company=CompanyConfig(), telemetry=False)

    with TestClient(agent_os.get_app()) as client:
        assert client.get(f"/company/goals/{GOAL}").json()["objective"] == (
            "Keep this AgentOS current, secure and working."
        )

    described = database.describe(rows=False)
    assert "objective" in described["my_products"]["columns"] and "agno_company_goals" not in described
    assert database.versions()["my_products"] == "3.3.0"
    assert len(ups) == 1 and _errors(logged) == []


def test_two_instances_that_start_together_migrate_once(database, ups, logged):
    _write_3_2_0_database(database)
    apps = [_agent_os(database).get_app() for _ in range(2)]
    together = threading.Barrier(2)
    results: List[Any] = [None, None]

    def start(index: int) -> None:
        together.wait(timeout=30)
        try:
            with TestClient(apps[index]) as client:
                results[index] = _goal_ids(client)
        except BaseException as exc:  # noqa: BLE001
            results[index] = exc

    threads = [threading.Thread(target=start, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert results[0] == results[1], results
    assert {GOAL, ARCHIVED_GOAL} <= set(results[0])
    assert len(ups) == 1
    assert _errors(logged) == []
    _assert_renamed(database)


def test_a_migration_that_stops_partway_is_finished_by_the_endpoint(database, ups, logged, monkeypatch):
    _write_3_2_0_database(database)
    agent_os = AgentOS(
        db=database.db(),
        company=CompanyConfig(goals=[Goal(id="declared", name="Declared in code", objective="Start late.")]),
        telemetry=False,
    )

    def stop(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("stopped partway")

    with monkeypatch.context() as patch:
        patch.setattr(v3_3_0, "_rename_column", stop)
        starting = TestClient(agent_os.get_app())
        client = starting.__enter__()
    try:
        # AgentOS started. One line says which database was not migrated, why, and what to run. The
        # migration manager logs its own failure before it.
        errors = _errors(logged)
        assert errors[0] == "Error running migration to version v3_3_0: stopped partway"
        assert len(errors) == 2, errors
        assert "was not migrated: RuntimeError: stopped partway" in errors[1]
        assert "MigrationManager(db).up()" in errors[1] and "POST /databases/all/migrate" in errors[1]
        # Everything outside Company works.
        assert client.get("/health").status_code == 200
        assert client.get("/sessions").status_code == 200
        # Company says what it needs.
        _assert_refused(client.get("/company/goals"))
        _assert_refused(client.post("/company/goals", json={"name": "Docs"}))

        migrated = client.post("/databases/all/migrate")
        assert migrated.status_code == 200, migrated.text

        # Company works without a restart, with the Goal declared in code.
        assert {GOAL, ARCHIVED_GOAL, "declared"} <= set(_goal_ids(client))
        assert client.get("/company/goals/declared").json()["objective"] == "Start late."
    finally:
        starting.__exit__(None, None, None)
    _assert_renamed(database)


def test_without_auto_provisioning_nothing_is_migrated_and_company_refuses(database, ups, logged):
    _write_3_2_0_database(database)
    before = database.describe()

    with TestClient(_agent_os(database, auto_provision_dbs=False).get_app()) as client:
        # One line at the start says Company waits for the migration.
        errors = _errors(logged)
        assert len(errors) == 1, errors
        assert errors[0].startswith("Company is not started: ") and "MigrationManager(db).up()" in errors[0]
        assert client.get("/health").status_code == 200
        _assert_refused(client.get("/company/goals"))
        _assert_refused(client.get("/company/projects"))
        assert ups == []
        company = [name for name in before if name.startswith("agno_company")]
        after = database.describe()
        assert {name: after[name] for name in company} == {name: before[name] for name in company}

        # The operator migrates, and Company works.
        assert client.post("/databases/all/migrate").status_code == 200
        assert GOAL in _goal_ids(client)
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


def test_a_database_behind_an_older_migration_is_left_for_the_operator(database, ups, logged):
    _write_3_2_0_database(database)
    # A sessions table that never had the 3.0.0 migration, which copies every run into a new table.
    database.sync_db()._get_table(table_type="sessions", create_table_if_not_found=True)
    database.execute(
        f"UPDATE {database._ref('agno_schema_versions')} SET version = '2.5.6' WHERE table_name = 'agno_sessions'"
    )
    before = database.describe(rows=False)

    with TestClient(_agent_os(database).get_app()) as client:
        errors = _errors(logged)
        assert len(errors) == 1, errors
        assert "agno_sessions is at version 2.5.6" in errors[0] and "MigrationManager(db).up()" in errors[0]
        assert client.get("/health").status_code == 200
        _assert_refused(client.get("/company/goals"))

    assert ups == []
    company = [name for name in before if name.startswith("agno_company")]
    after = database.describe(rows=False)
    assert {name: after[name] for name in company} == {name: before[name] for name in company}
