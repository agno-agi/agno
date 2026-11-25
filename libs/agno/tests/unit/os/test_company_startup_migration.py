"""AgentOS migrates a database written by agno 3.2 as it starts, and still starts when it cannot.

Each test runs on SQLite and on PostgreSQL, with the sync and the async adapter. The database is the
3.2.0 fixture of the migration tests, stamped the way 3.2.0 stamps it.
"""

import asyncio
import json
import logging
import threading
from typing import Any, List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from agno.company import Goal, Routine
from agno.db.migrations import startup
from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.startup import StartupMigration, _call, _sqlite_lock_path, migrate_at_startup
from agno.db.migrations.versions import v3_3_0
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
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


def test_a_migration_that_stops_partway_is_finished_by_the_next_start(database, ups, logged, monkeypatch):
    _write_3_2_0_database(database)

    def stop(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("stopped partway")

    # SQLite keeps the table rename that ran before the stop; PostgreSQL takes it back.
    with monkeypatch.context() as patch:
        patch.setattr(v3_3_0, "_rename_column", stop)
        with TestClient(_agent_os(database).get_app()) as client:
            _assert_refused(client.get("/company/goals"))
    ups.clear()
    logged.clear()

    with TestClient(_agent_os(database).get_app()) as client:
        assert GOAL in _goal_ids(client)

    assert len(ups) == 1
    assert _errors(logged) == []
    _assert_renamed(database)


def test_a_table_another_session_holds_does_not_keep_agent_os_from_starting(database, logged, monkeypatch):
    if not database.postgres:
        pytest.skip("SQLite has no lock on one table; a locked file fails the migration at once")
    _write_3_2_0_database(database)
    monkeypatch.setattr(v3_3_0, "LOCK_TIMEOUT_SECONDS", 1)
    engine = create_engine(database.url)
    reader = engine.connect()
    try:
        # A dump, or a session left open in a transaction, has read the table the migration renames.
        reader.execute(text(f"SELECT count(*) FROM {database._ref('agno_company_products')}"))
        with TestClient(_agent_os(database).get_app()) as client:
            errors = _errors(logged)
            assert any("was not migrated" in error and "lock timeout" in error for error in errors), errors
            assert client.get("/health").status_code == 200
            _assert_refused(client.get("/company/goals"))

            reader.rollback()
            assert client.post("/databases/all/migrate").status_code == 200
            assert GOAL in _goal_ids(client)
    finally:
        reader.close()
        engine.dispose()
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


def test_the_migrate_endpoint_answers_for_the_migration_when_company_cannot_start(database, logged, monkeypatch):
    _write_3_2_0_database(database)

    with TestClient(_agent_os(database, auto_provision_dbs=False).get_app()) as client:

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
    company, schedules, build = _two_databases(databases, _declared(), auto_provision_dbs=False)
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
    company, schedules, build = _two_databases(databases, _declared(), auto_provision_dbs=False)
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


# ------------------------------------------------------------------------------ the migration lock


@pytest.mark.parametrize("use_async", [False, True])
async def test_a_pool_of_one_connection_is_migrated(database, use_async):
    if not database.postgres:
        pytest.skip("The PostgreSQL lock takes a connection; the SQLite lock takes a file")
    _write_3_2_0_database(database)
    make_engine, adapter = (create_async_engine, AsyncPostgresDb) if use_async else (create_engine, PostgresDb)
    engine = make_engine(database.url, pool_size=1, max_overflow=0, pool_timeout=5)
    db = adapter(db_engine=engine, db_schema=database.schema)

    assert await migrate_at_startup(db) == StartupMigration("migrated")

    _assert_renamed(database)
    await _call(engine.dispose)


async def test_every_name_of_a_sqlite_file_shares_its_lock(tmp_path):
    path = str((tmp_path / "company.db").resolve())
    link = tmp_path / "link.db"
    SqliteDb(db_file=path)._create_all_tables()
    link.symlink_to(path)
    uri = f"file:{path}?uri=true"

    for db in (
        SqliteDb(db_file=path),
        SqliteDb(db_url=f"sqlite:///{uri}"),
        AsyncSqliteDb(db_url=f"sqlite+aiosqlite:///{uri}"),
        SqliteDb(db_url=f"sqlite:///{link}"),
    ):
        assert await _sqlite_lock_path(db) == path + ".migration-lock"
        await _call(db.close)


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///file:shared?mode=memory&cache=shared&uri=true"])
async def test_a_sqlite_database_in_memory_has_no_lock_file(url):
    assert await _sqlite_lock_path(SqliteDb(db_url=url)) is None


@pytest.mark.parametrize("route", ["all", "one"])
def test_the_migrate_endpoint_takes_the_lock_of_the_start(database, ups, monkeypatch, route):
    _write_3_2_0_database(database)
    monkeypatch.setattr(startup, "REQUEST_LOCK_WAIT_SECONDS", 0.5)
    agent_os = _agent_os(database, auto_provision_dbs=False)
    db_id = agent_os.db.id
    taken, release = threading.Event(), threading.Event()

    def hold() -> None:
        async def run() -> None:
            async with startup.migration_lock(database.db(), 5) as held:
                assert held
                taken.set()
                while not release.is_set():
                    await asyncio.sleep(0.05)

        asyncio.run(run())

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert taken.wait(10)
        with TestClient(agent_os.get_app(), raise_server_exceptions=False) as client:
            path = "/databases/all/migrate" if route == "all" else f"/databases/{db_id}/migrate"
            refused = client.post(path)
            assert refused.status_code == (207 if route == "all" else 409), refused.text
            assert "Another process is migrating" in refused.text
            assert ups == []

            release.set()
            holder.join(10)
            assert client.post(path).status_code == 200
            assert ARCHIVED_GOAL in _goal_ids(client)
    finally:
        release.set()
        holder.join(10)


async def test_a_lock_on_a_removed_sqlite_file_is_not_taken(tmp_path, monkeypatch):
    path = str(tmp_path / "company.db.migration-lock")
    connect = startup.sqlite3.connect
    removed = []

    def connect_then_remove(*args, **kwargs):
        conn = connect(*args, **kwargs)
        if not removed:
            # SQLite opens the file at the first statement.
            conn.execute("PRAGMA schema_version")
            startup.os.unlink(path)
            removed.append(path)
        return conn

    monkeypatch.setattr(startup.sqlite3, "connect", connect_then_remove)

    async with startup._sqlite_lock(path, 5) as held:
        assert held and removed
        async with startup._sqlite_lock(path, 0) as second:
            assert second is False
    assert not startup.os.path.exists(path)
