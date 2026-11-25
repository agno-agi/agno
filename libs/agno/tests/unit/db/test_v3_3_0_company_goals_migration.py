"""A Company database written by agno 3.2.0 carries over through the v3.3.0 migration.

agno 3.2.0 stored a Goal as a Product. The fixture here is a database in the 3.2.0 shape: its
Company tables are built from the table definitions at the v3.2.0 tag, and its rows are the rows
agno 3.2.0 writes for the same records. Every test runs on SQLite and on PostgreSQL, with the
sync and the async adapter.

PostgreSQL is the pgvector container on localhost:5532. Each test uses its own schema, and the
PostgreSQL cases skip when the server is absent.
"""

import inspect as python_inspect
import json
import uuid
from typing import Any, Dict, List, Optional

import httpx
import pytest
from sqlalchemy import BigInteger, String, Text, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.types import JSON

import agno.db.postgres.schemas as postgres_schemas
import agno.db.sqlite.schemas as sqlite_schemas
from agno.company import AsyncCompanyManager, CompanyManager
from agno.company.automation_history import _task_state, aautomation_failures
from agno.company.routines import _check_automatic_policy, _require_routine_goal
from agno.company.scheduler import CompanyScheduleExecutor
from agno.company.summary import _summary_state_filesystem
from agno.db.base import AsyncBaseDb
from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.startup import migrate_at_startup
from agno.db.migrations.versions import v3_3_0
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID, Schedule
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.exceptions import MigrationRequiredError
from agno.fs import FileSystem
from agno.os.authz.run_context import restore_authorization
from agno.run.authorization import AUTHORIZATION_HEADER, AUTHORIZATION_KEY, authorization_scope

POSTGRES_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
BACKENDS = ["sqlite", "async_sqlite", "postgres", "async_postgres"]

NOW = 1795519649
GOAL = "this-agentos"
ARCHIVED_GOAL = "old-docs"
SOURCE = "e0a4b0f6-5a0c-5d0f-9d2a-3d4d7c2a9b10"
ROUTINE = "55b6acba-4edb-4c7c-abcc-439915ee2047"
ARCHIVED_ROUTINE = "0c3f6f0e-7e7f-4a50-9d43-0d5b3a6f2f11"
ACTIVE_PROJECT = "868a8565-b369-4d44-8773-31de9d13170c"
ARCHIVED_PROJECT = "86b2216a-9d2e-446b-8e18-6b9228bf87d1"
BACKLOG_TASK = "09697494-c213-428b-8905-1851e9d61f71"
ACCEPTED_TASK = "5b1f0a57-0a53-4d0e-8a35-6f3a1e0f7c12"
ARCHIVED_TASK = "8cda2648-9edc-4cf5-b9d6-ef4c54adba5c"

# The auto-accept policy as agno 3.2.0 stores it, and the fingerprint 3.2.0 computes for it.
POLICY = {
    "default_executor": "miniagent",
    "executors": None,
    "source_ids": None,
    "work_scope": {"product_ids": [GOAL], "project_ids": None},
    "required_checks": ["executor_registered"],
    "limits": None,
    "complete_projects": False,
    "approve_projects": True,
    "max_open": 5,
}
POLICY_FINGERPRINT = "e54fecae71893ab6d02b2275ddb09a74d6576485667fa742678fd4aa55405e09"
# The authority a Routine run holds, as 3.2.0 saves it on a Task it accepts.
ROUTINE_SNAPSHOT = {
    "context": {"principal_id": None},
    "service_account": True,
    "enforce_tools": True,
    "company_routine": True,
    "company_routine_unscoped": True,
    "company_routine_id": ROUTINE,
    "company_product_id": GOAL,
}
ARCHIVE = {"type": "product", "id": ARCHIVED_GOAL}


def _schemas_3_2_0(json_type: Any, name_nullable: bool) -> Dict[str, Dict[str, Any]]:
    """The Company table definitions at the v3.2.0 tag, by the name the schema module gives each.

    Copied from db/sqlite/schemas.py and db/postgres/schemas.py. The two differ in the JSON type
    and in whether a name or a title may be null.
    """
    return {
        "SOURCES_TABLE_SCHEMA": {
            "id": {"type": String, "primary_key": True},
            "product_id": {"type": String, "nullable": False, "index": True},
            "reference": {"type": Text, "nullable": False},
            "type": {"type": String, "nullable": False},
            "credential_ref": {"type": String, "nullable": True},
            "user_id": {"type": String, "nullable": True, "index": True},
            "config": {"type": json_type, "nullable": True},
            "created_at": {"type": BigInteger, "nullable": False, "index": True},
            "updated_at": {"type": BigInteger, "nullable": True},
            "deleted_at": {"type": BigInteger, "nullable": True},
        },
        "GOALS_TABLE_SCHEMA": {
            "id": {"type": String, "primary_key": True},
            "name": {"type": String, "nullable": name_nullable, "index": True},
            "purpose": {"type": Text, "nullable": True},
            "user_id": {"type": String, "nullable": True, "index": True},
            "metadata": {"type": json_type, "nullable": True},
            "created_at": {"type": BigInteger, "nullable": False, "index": True},
            "updated_at": {"type": BigInteger, "nullable": True},
            "deleted_at": {"type": BigInteger, "nullable": True},
        },
        "TASKS_TABLE_SCHEMA": {
            "id": {"type": String, "primary_key": True},
            "product_id": {"type": String, "nullable": False, "index": True},
            "project_id": {"type": String, "nullable": True, "index": True},
            "title": {"type": String, "nullable": name_nullable, "index": True},
            "brief": {"type": Text, "nullable": True},
            "status": {"type": String, "nullable": False, "index": True},
            "user_id": {"type": String, "nullable": True, "index": True},
            "executor_type": {"type": String, "nullable": True},
            "executor_id": {"type": String, "nullable": True},
            "accepted_by": {"type": String, "nullable": True},
            "accepted_at": {"type": BigInteger, "nullable": True},
            "session_id": {"type": String, "nullable": True, "index": True},
            "job_id": {"type": String, "nullable": True, "index": True},
            "evidence": {"type": json_type, "nullable": True},
            "result": {"type": json_type, "nullable": True},
            "origin": {"type": String, "nullable": True},
            "routine_id": {"type": String, "nullable": True},
            "dedupe_key": {"type": String, "nullable": True},
            "transitions": {"type": json_type, "nullable": True},
            "metadata": {"type": json_type, "nullable": True},
            "created_at": {"type": BigInteger, "nullable": False, "index": True},
            "updated_at": {"type": BigInteger, "nullable": True},
            "deleted_at": {"type": BigInteger, "nullable": True},
            "_unique_constraints": [
                {"name": "uq_company_task_evidence", "columns": ["product_id", "dedupe_key"]},
            ],
        },
        "PROJECTS_TABLE_SCHEMA": {
            "id": {"type": String, "primary_key": True},
            "name": {"type": String, "nullable": name_nullable, "index": True},
            "outcome": {"type": Text, "nullable": True},
            "user_id": {"type": String, "nullable": True, "index": True},
            "transitions": {"type": json_type, "nullable": True},
            "created_at": {"type": BigInteger, "nullable": False, "index": True},
            "updated_at": {"type": BigInteger, "nullable": True},
            "deleted_at": {"type": BigInteger, "nullable": True},
            "product_id": {"type": String, "nullable": False, "index": True},
            "status": {"type": String, "nullable": False, "index": True},
            "target_date": {"type": BigInteger, "nullable": True},
        },
    }


async def _call(function: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a sync or an async adapter method."""
    result = function(*args, **kwargs)
    return await result if python_inspect.isawaitable(result) else result


class _Database:
    """One database, reached through the adapter under test and through a plain engine."""

    def __init__(self, kind: str, location: str):
        self.kind = kind
        self.postgres = "postgres" in kind
        self.location = location
        self.schema = location if self.postgres else None
        self.url = POSTGRES_URL if self.postgres else "sqlite:///" + location
        # PostgreSQL keeps every database's files in one shared schema, so the Goal that owns this
        # database's files has an id no other test uses.
        self.files_goal = f"docs-{uuid.uuid4().hex[:10]}"
        self._opened: List[Any] = []
        self._patch = pytest.MonkeyPatch()

    def _open(self, cls: Any, **tables: Any) -> Any:
        where = {"db_url": POSTGRES_URL, "db_schema": self.location} if self.postgres else {"db_file": self.location}
        db = cls(**where, **tables)
        self._opened.append(db)
        return db

    def db(self, **tables: Any) -> Any:
        """The adapter under test, with its default table names unless some are given."""
        if self.postgres:
            return self._open(AsyncPostgresDb if self.kind.startswith("async") else PostgresDb, **tables)
        return self._open(AsyncSqliteDb if self.kind.startswith("async") else SqliteDb, **tables)

    def sync_db(self, **tables: Any) -> Any:
        return self._open(PostgresDb if self.postgres else SqliteDb, **tables)

    async def close(self) -> None:
        self._patch.undo()
        for db in self._opened:
            await _call(db.close)
        self._opened.clear()
        if self.postgres:
            engine = create_engine(POSTGRES_URL)
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.location}" CASCADE'))
                if inspect(conn).has_table("agno_fs", schema="fs"):
                    files = {"namespace": f"company/products/{self.files_goal}/%"}
                    conn.execute(text("DELETE FROM fs.agno_fs WHERE namespace LIKE :namespace"), files)
            engine.dispose()

    def _ref(self, name: str) -> str:
        return f'"{self.schema}"."{name}"' if self.schema else f'"{name}"'

    def describe(self, rows: bool = True, versions: bool = True) -> Dict[str, Any]:
        """Every table with its columns, indexes and constraints, and its rows when asked."""
        engine = create_engine(self.url)
        try:
            inspector = inspect(engine)
            described: Dict[str, Any] = {}
            for name in sorted(inspector.get_table_names(schema=self.schema)):
                if name == "agno_schema_versions" and not versions:
                    continue
                table: Dict[str, Any] = {
                    "columns": [column["name"] for column in inspector.get_columns(name, schema=self.schema)],
                    "indexes": sorted(
                        (index["name"], tuple(index["column_names"]))
                        for index in inspector.get_indexes(name, schema=self.schema)
                    ),
                    "unique": sorted(
                        (unique["name"], tuple(unique["column_names"]))
                        for unique in inspector.get_unique_constraints(name, schema=self.schema)
                    ),
                    "primary_key": inspector.get_pk_constraint(name, schema=self.schema).get("name"),
                }
                if rows:
                    with engine.connect() as conn:
                        found = conn.execute(text(f"SELECT * FROM {self._ref(name)}")).mappings().all()
                    table["rows"] = sorted(json.dumps(dict(row), sort_keys=True, default=str) for row in found)
                described[name] = table
            return described
        finally:
            engine.dispose()

    def versions(self) -> Dict[str, str]:
        engine = create_engine(self.url)
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(f"SELECT table_name, version FROM {self._ref('agno_schema_versions')}"))
                return {row[0]: row[1] for row in rows}
        finally:
            engine.dispose()

    def execute(self, statement: str, **params: Any) -> None:
        engine = create_engine(self.url)
        try:
            with engine.begin() as conn:
                conn.execute(text(statement), params)
        finally:
            engine.dispose()


def _postgres_reachable() -> bool:
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def postgres_available():
    return _postgres_reachable()


@pytest.fixture(params=BACKENDS)
async def databases(request, tmp_path, postgres_available):
    """A factory of empty databases of one kind. Each is removed when the test ends."""
    kind = request.param
    if "postgres" in kind and not postgres_available:
        pytest.skip(f"Postgres server not reachable at {POSTGRES_URL}")
    made: List[_Database] = []

    def make() -> _Database:
        if "postgres" in kind:
            location = f"goals_{uuid.uuid4().hex[:10]}"
        else:
            location = str(tmp_path / f"company_{len(made)}.db")
        made.append(_Database(kind, location))
        return made[-1]

    yield make
    for database in made:
        await database.close()


@pytest.fixture
async def database(databases):
    return databases()


def _write_company_3_2_0(database: _Database, goals_table: str = "agno_company_products") -> None:
    """Write the Company tables, rows and files agno 3.2.0 leaves in the Company database."""
    with pytest.MonkeyPatch.context() as patch:
        for module, json_type, name_nullable in ((sqlite_schemas, JSON, False), (postgres_schemas, JSONB, True)):
            for attribute, schema in _schemas_3_2_0(json_type, name_nullable).items():
                patch.setattr(module, attribute, schema)
        # In 3.2.0 the goals table was the products table.
        db = database.sync_db(goals_table=goals_table)
        tables = {
            kind: db._get_table(table_type=kind, create_table_if_not_found=True)
            for kind in ("goals", "company", "sources", "projects", "tasks")
        }
        archive = {
            "action": "archive",
            "reason": "Parent archived",
            "created_at": NOW,
            "user_id": None,
            "archived_by": ARCHIVE,
        }
        accepted = {
            "from": "backlog",
            "target": "ready",
            "reason": "Accepted by the Routine's policy",
            "user_id": None,
            "created_at": NOW,
            "auto_accept": {"routine_id": ROUTINE, "policy": POLICY_FINGERPRINT, "declared": True, "max_open": 5},
            AUTHORIZATION_KEY: ROUTINE_SNAPSHOT,
        }
        dates = {"created_at": NOW, "updated_at": NOW}
        task = {
            "brief": None,
            "user_id": None,
            "origin": "human",
            "routine_id": None,
            "executor_type": None,
            "executor_id": None,
            "dedupe_key": None,
            **dates,
        }
        with db.Session() as sess, sess.begin():
            sess.execute(tables["company"].insert().values(id="company", name="Company", description=None, **dates))
            sess.execute(
                tables["goals"].insert(),
                [
                    {
                        "id": GOAL,
                        "name": "AgentOS",
                        "purpose": "Keep this AgentOS current, secure and working.",
                        "user_id": None,
                        "metadata": {"archive_window_days": 14, "routine_ids": [ROUTINE]},
                        "deleted_at": None,
                        **dates,
                    },
                    {
                        "id": ARCHIVED_GOAL,
                        "name": "Old docs",
                        "purpose": "Retired.",
                        "user_id": None,
                        "metadata": {"archive_window_days": 14, "routine_ids": [ARCHIVED_ROUTINE]},
                        "deleted_at": NOW,
                        **dates,
                    },
                    {
                        "id": database.files_goal,
                        "name": "Docs",
                        "purpose": "Keep the docs accurate.",
                        "user_id": None,
                        "metadata": {"archive_window_days": 14},
                        "deleted_at": None,
                        **dates,
                    },
                ],
            )
            sess.execute(
                tables["sources"]
                .insert()
                .values(
                    id=SOURCE,
                    product_id=GOAL,
                    reference="https://example.com/releases",
                    type="website",
                    config={},
                    **dates,
                )
            )
            sess.execute(
                tables["projects"].insert(),
                [
                    {
                        "id": ACTIVE_PROJECT,
                        "name": "Upgrade agno",
                        "product_id": GOAL,
                        "status": "active",
                        "transitions": [{"from": "proposed", "target": "active", "reason": "Approved", **dates}],
                        "deleted_at": None,
                        **dates,
                    },
                    {
                        "id": ARCHIVED_PROJECT,
                        "name": "Rewrite the guide",
                        "product_id": ARCHIVED_GOAL,
                        "status": "proposed",
                        "transitions": [{**archive, "from": "proposed", "target": "proposed"}],
                        "deleted_at": NOW,
                        **dates,
                    },
                ],
            )
            sess.execute(
                tables["tasks"].insert(),
                [
                    {
                        **task,
                        "id": BACKLOG_TASK,
                        "product_id": GOAL,
                        "project_id": ACTIVE_PROJECT,
                        "title": "Read the release notes",
                        "status": "backlog",
                        "transitions": [],
                        "dedupe_key": "release-notes",
                        "deleted_at": None,
                    },
                    {
                        **task,
                        "id": ACCEPTED_TASK,
                        "product_id": GOAL,
                        "project_id": ACTIVE_PROJECT,
                        "title": "Raise the agno pin",
                        "status": "ready",
                        "origin": "routine",
                        "routine_id": ROUTINE,
                        "executor_type": "agent",
                        "executor_id": "miniagent",
                        "transitions": [accepted],
                        "deleted_at": None,
                    },
                    {
                        **task,
                        "id": ARCHIVED_TASK,
                        "product_id": ARCHIVED_GOAL,
                        "project_id": ARCHIVED_PROJECT,
                        "title": "Draft chapter one",
                        "status": "backlog",
                        "transitions": [{**archive, "from": "backlog", "target": "backlog"}],
                        "deleted_at": NOW,
                    },
                ],
            )
        FileSystem(db, namespace=f"company/products/{database.files_goal}/wiki", user_scoped=False).write(
            "research.md", "# Research\n\nFound on 3.2.0.\n", expected_version=0
        )
        _summary_state_filesystem(db, database.files_goal).write(
            "baseline.md", "delivered on 3.2.0\n", expected_version=0
        )
    _stamp_3_0_0(database)


def _write_schedules_3_2_0(database: _Database) -> None:
    """Write the Routines and the failure history agno 3.2.0 leaves in the AgentOS database."""
    db = database.sync_db()
    schedules = db._get_table(table_type="schedules", create_table_if_not_found=True)
    runs = db._get_table(table_type="schedule_runs", create_table_if_not_found=True)
    routine = {
        "method": "POST",
        "endpoint": "/agents/miniagent/runs",
        "cron_expr": "0 9 * * 1",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "user_id": None,
        "managed_by": "company",
        "target_type": "agent",
        "target_id": "miniagent",
        "created_at": NOW,
        "updated_at": NOW,
    }
    # The Task the Routine accepted has not changed since its run failed.
    state = _task_state(
        {
            "status": "ready",
            "project_id": ACTIVE_PROJECT,
            "updated_at": NOW,
            "transitions": [
                {
                    "from": "backlog",
                    "target": "ready",
                    "reason": "Accepted by the Routine's policy",
                    "user_id": None,
                    "created_at": NOW,
                    "auto_accept": {
                        "routine_id": ROUTINE,
                        "policy": POLICY_FINGERPRINT,
                        "declared": True,
                        "max_open": 5,
                    },
                    AUTHORIZATION_KEY: ROUTINE_SNAPSHOT,
                }
            ],
            "result": None,
            "deleted_at": None,
        }
    )
    with db.Session() as sess, sess.begin():
        sess.execute(
            schedules.insert(),
            [
                {
                    **routine,
                    "id": ROUTINE,
                    "name": f"{GOAL}.maintenance",
                    "enabled": True,
                    "disabled_reason": None,
                    "payload": {
                        "message": f'Operate only on Product "{GOAL}".\n\nRead the Product status and propose work.',
                        "metadata": {"product_id": GOAL, "template": None, "auto_accept": POLICY},
                        "_agno_company_acceptance": {"declared": True},
                    },
                },
                {
                    **routine,
                    "id": ARCHIVED_ROUTINE,
                    "name": f"{ARCHIVED_GOAL}.review",
                    "enabled": False,
                    "disabled_reason": "company_product_archived",
                    "payload": {
                        "message": f'Operate only on Product "{ARCHIVED_GOAL}".\n\nReview the guide.',
                        "metadata": {"product_id": ARCHIVED_GOAL, "template": None, "auto_accept": False},
                    },
                },
                {
                    **routine,
                    "id": COMPANY_AUTOMATION_SCHEDULE_ID,
                    "name": "Company automation",
                    "method": "GET",
                    "endpoint": "/company/attention",
                    "cron_expr": "0 * * * *",
                    "target_type": None,
                    "target_id": None,
                    "enabled": True,
                    "disabled_reason": None,
                    "payload": None,
                },
                {
                    **routine,
                    "id": "a-persons-schedule",
                    "name": "nightly-report",
                    "managed_by": None,
                    "enabled": True,
                    "disabled_reason": None,
                    # Not a Routine: its payload is the person's own and is left as it is.
                    "payload": {"message": "Report", "metadata": {"product_id": "sku-1"}},
                },
            ],
        )
        sess.execute(
            runs.insert().values(
                id="failure-1",
                schedule_id=COMPANY_AUTOMATION_SCHEDULE_ID,
                attempt=1,
                triggered_at=NOW,
                status="failed",
                output={
                    "automation_failure": {
                        "task_id": ACCEPTED_TASK,
                        "product_id": GOAL,
                        "state": state,
                        "active": True,
                        "count": 2,
                        "reason": "The executor is not registered",
                    }
                },
                created_at=NOW,
            )
        )
    _stamp_3_0_0(database)


def _stamp_3_0_0(database: _Database) -> None:
    # 3.2.0 stamps every table it creates with 3.0.0, its newest migration.
    database.execute(f"UPDATE {database._ref('agno_schema_versions')} SET version = '3.0.0'")


def _write_3_2_0(database: _Database) -> None:
    _write_company_3_2_0(database)
    _write_schedules_3_2_0(database)


async def _start_before_migrating(database: _Database) -> None:
    """What a start before the migration wrote, when nothing yet refused to create the goals tables."""
    database._patch.setattr("agno.db.utils.legacy_company_table", lambda db, table_type: None)
    db = database.db()
    await _call(db.initialize_company, "Company", None)
    await _call(
        db.create_goal,
        {
            "id": GOAL,
            "name": "AgentOS",
            "objective": "Keep this AgentOS current, secure and working.",
            "metadata": None,
            "user_id": None,
            "created_at": NOW + 60,
            "updated_at": None,
            "deleted_at": None,
        },
    )
    await _call(db.close)


def _manager(db: Any) -> Any:
    return AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db)


async def _assert_carried_over(database: _Database) -> None:
    """Every 3.2.0 record is present under the new names, with the id it had."""
    described = database.describe(rows=False)
    assert "agno_company_products" not in described
    assert "agno_company_products_details" not in described
    assert "objective" in described["agno_company_goals"]["columns"]
    assert "purpose" not in described["agno_company_goals"]["columns"]
    for name in ("agno_company_projects", "agno_company_tasks", "agno_company_sources"):
        assert "goal_id" in described[name]["columns"] and "product_id" not in described[name]["columns"]
    unique = described["agno_company_tasks"]["unique"]
    assert unique == [("agno_company_tasks_uq_company_task_evidence", ("goal_id", "dedupe_key"))]

    db = database.db()
    goal = await _call(db.get_goal, GOAL)
    assert goal["objective"] == "Keep this AgentOS current, secure and working."
    assert goal["metadata"] == {"archive_window_days": 14, "routine_ids": [ROUTINE]}
    assert goal["created_at"] == NOW
    assert (await _call(db.get_goal, ARCHIVED_GOAL, include_deleted=True))["deleted_at"] == NOW
    assert (await _call(db.get_company))["name"] == "Company"
    sources, _ = await _call(db.get_sources, goal_id=GOAL)
    assert [source["id"] for source in sources] == [SOURCE]
    projects, _ = await _call(db.get_projects, goal_id=GOAL)
    assert [project["id"] for project in projects] == [ACTIVE_PROJECT]
    tasks, _ = await _call(db.get_tasks, goal_id=GOAL)
    assert sorted(task["id"] for task in tasks) == sorted([BACKLOG_TASK, ACCEPTED_TASK])
    assert {task["goal_id"] for task in tasks} == {GOAL}


# ------------------------------------------------------------------------------------- the rename


async def test_a_3_2_0_database_carries_over(database):
    _write_3_2_0(database)

    await MigrationManager(database.db()).up()

    await _assert_carried_over(database)
    versions = database.versions()
    assert "agno_company_products" not in versions and "agno_company_products_details" not in versions
    for name in ("agno_company_goals", "agno_company_sources", "agno_company_projects", "agno_company_tasks"):
        assert versions[name] == "3.3.0"
    assert versions["agno_schedules"] == "3.3.0" and versions["agno_schedule_runs"] == "3.3.0"
    assert versions["agno_company_goals_details"] == "3.0.0"


async def test_before_the_migration_the_new_code_asks_for_it(database):
    _write_3_2_0(database)

    with pytest.raises(MigrationRequiredError, match="MigrationManager"):
        await _call(database.db().get_sources, goal_id=GOAL)


async def test_restoring_an_archived_goal_restores_its_project_and_task(database):
    _write_3_2_0(database)
    db = database.db()
    await MigrationManager(db).up()

    restored = await _call(_manager(db).restore, ARCHIVED_GOAL)

    assert restored["deleted_at"] is None
    project = await _call(db.get_project, ARCHIVED_PROJECT)
    task = await _call(db.get_task, ARCHIVED_TASK)
    assert project is not None and project["deleted_at"] is None
    assert task is not None and task["deleted_at"] is None
    assert project["transitions"][0]["archived_by"] == {"type": "goal", "id": ARCHIVED_GOAL}


async def test_the_routine_fires_and_its_run_resolves_the_goal(database):
    _write_3_2_0(database)
    db = database.db()
    await MigrationManager(db).up()

    routine = await _call(db.get_schedule, ROUTINE)
    assert routine["payload"]["metadata"]["goal_id"] == GOAL
    assert "product_id" not in routine["payload"]["metadata"]
    assert routine["payload"]["metadata"]["auto_accept"]["work_scope"] == {"goal_ids": [GOAL], "project_ids": None}
    assert routine["payload"]["_agno_company_acceptance"] == {"declared": True}
    assert routine["updated_at"] == NOW
    archived = await _call(db.get_schedule, ARCHIVED_ROUTINE)
    assert archived["disabled_reason"] == "company_goal_archived"
    assert archived["payload"]["metadata"]["goal_id"] == ARCHIVED_GOAL
    # A schedule that is not a Routine keeps its own payload.
    assert (await _call(db.get_schedule, "a-persons-schedule"))["payload"]["metadata"] == {"product_id": "sku-1"}

    sent: List[httpx.Request] = []

    def receive(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(503, text="not served in this test")

    executor = CompanyScheduleExecutor(
        company_db=db, schedule_db=db, base_url="http://agentos.test", internal_service_token="token"
    )
    executor._client = httpx.AsyncClient(transport=httpx.MockTransport(receive))
    try:
        await executor._call_endpoint(Schedule.from_dict(routine))
    finally:
        await executor.close()

    # The scheduler sent the run to the Routine's executor, as an authority bound to the Goal.
    assert sent and sent[0].url.path == "/agents/miniagent/runs"
    authority = restore_authorization(None, json.loads(sent[0].headers[AUTHORIZATION_HEADER]))
    assert authority.goal_id == GOAL
    with authorization_scope(lambda: authority):
        _require_routine_goal(GOAL)
        with pytest.raises(PermissionError):
            _require_routine_goal(ARCHIVED_GOAL)
        assert (await _call(_manager(db).get, GOAL))["id"] == GOAL


async def test_a_task_accepted_before_the_upgrade_keeps_its_acceptance(database):
    _write_3_2_0(database)
    db = database.db()
    await MigrationManager(db).up()
    task = await _call(db.get_task, ACCEPTED_TASK)

    # The receipt holds the fingerprint 3.2.0 computed for the Routine's policy.
    await _check_automatic_policy(db, task)

    # The authority saved on the acceptance still names its Goal.
    authority = restore_authorization(None, task["transitions"][-1][AUTHORIZATION_KEY])
    assert authority.goal_id == GOAL


async def test_a_recorded_failure_is_still_listed_for_its_goal(database):
    _write_3_2_0(database)
    db = database.db()
    await MigrationManager(db).up()

    failures = await aautomation_failures(db, db, goal_id=GOAL)

    assert failures == [{"task_id": ACCEPTED_TASK, "reason": "The executor is not registered", "count": 2}]
    assert await aautomation_failures(db, db, goal_id=ARCHIVED_GOAL) == []


async def test_stored_files_read_through_the_goal(database):
    _write_3_2_0(database)
    db = database.db()
    await MigrationManager(db).up()
    manager = _manager(db)
    goal = database.files_goal

    page = await _call(manager.read_wiki, goal, "research.md")
    listed, total = await _call(manager.list_wiki, goal)

    assert page.content == "# Research\n\nFound on 3.2.0.\n"
    assert "research.md" in [row.path for row in listed]
    # The files stay in the namespaces 3.2.0 wrote them to.
    sync_db = database.sync_db()
    assert FileSystem(sync_db, namespace=f"company/products/{goal}/wiki", user_scoped=False).read("research.md")
    assert _summary_state_filesystem(sync_db, goal).read("baseline.md") == "delivered on 3.2.0\n"


async def test_a_migrated_database_has_the_indexes_of_a_new_one(databases):
    migrated, new = databases(), databases()
    _write_3_2_0(migrated)
    await MigrationManager(migrated.db()).up()
    kinds = ("goals", "company", "sources", "projects", "tasks")
    for target in (migrated, new):
        # Using a table creates any index the adapter does not find by name.
        db = target.sync_db()
        for kind in kinds:
            db._get_table(table_type=kind, create_table_if_not_found=True)

    after, fresh = migrated.describe(rows=False), new.describe(rows=False)

    for name in (
        "agno_company_goals",
        "agno_company_goals_details",
        "agno_company_sources",
        "agno_company_projects",
        "agno_company_tasks",
    ):
        assert after[name]["indexes"] == fresh[name]["indexes"], name
        assert after[name]["unique"] == fresh[name]["unique"], name
        assert after[name]["primary_key"] == fresh[name]["primary_key"], name
        assert sorted(after[name]["columns"]) == sorted(fresh[name]["columns"]), name


def _index_sql(database: _Database, table_name: str) -> Dict[str, str]:
    """The statement that defines each index of a table, by index name."""
    engine = create_engine(database.url)
    try:
        with engine.connect() as conn:
            if database.postgres:
                rows = conn.execute(
                    text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = :schema AND tablename = :name"),
                    {"schema": database.schema, "name": table_name},
                )
            else:
                rows = conn.execute(
                    text("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = :name"),
                    {"name": table_name},
                )
            return {row[0]: row[1] or "" for row in rows}
    finally:
        engine.dispose()


@pytest.mark.parametrize("quoted", [False, True], ids=["bare-name", "quoted-name"])
async def test_an_index_the_user_added_keeps_its_definition(database, quoted):
    _write_3_2_0(database)
    products = database._ref("agno_company_products")
    framework_like = '"idx_agno_company_products_active_name"' if quoted else "idx_agno_company_products_active_name"
    # One active Goal for each name. The first index is named the way the framework names its own.
    database.execute(f"CREATE UNIQUE INDEX {framework_like} ON {products} (name) WHERE deleted_at IS NULL")
    database.execute(f"CREATE UNIQUE INDEX active_product_names ON {products} (name, user_id) WHERE deleted_at IS NULL")
    database.execute(f"CREATE INDEX idx_agno_company_products_newest ON {products} (created_at DESC)")

    await MigrationManager(database.db()).up()

    await _assert_carried_over(database)
    indexes = _index_sql(database, "agno_company_goals")
    assert "idx_agno_company_products_active_name" not in indexes
    assert "idx_agno_company_products_newest" not in indexes
    for name in ("idx_agno_company_goals_active_name", "active_product_names"):
        assert "UNIQUE" in indexes[name].upper(), indexes[name]
        assert "deleted_at IS NULL" in indexes[name].replace('"', ""), indexes[name]
    assert "DESC" in indexes["idx_agno_company_goals_newest"].upper()
    goals = database._ref("agno_company_goals")
    insert = f"INSERT INTO {goals} (id, name, created_at, deleted_at) VALUES (:id, 'AgentOS', {NOW}, :deleted_at)"
    # An archived Goal may share the name. A second active Goal may not.
    database.execute(insert, id="archived-copy", deleted_at=NOW)
    with pytest.raises(IntegrityError):
        database.execute(insert, id="active-copy", deleted_at=None)

    # A second run finds nothing left to rename.
    described = database.describe(rows=False)
    await MigrationManager(database.db()).up()
    assert database.describe(rows=False) == described


@pytest.mark.parametrize("taken_by", ["another table", "the same table, another definition"])
async def test_an_index_whose_new_name_is_taken_keeps_its_old_name(database, taken_by):
    if database.postgres:
        pytest.skip("PostgreSQL names an index within its schema and renames it in place")
    _write_3_2_0(database)
    products = database._ref("agno_company_products")
    database.execute(
        f"CREATE UNIQUE INDEX idx_agno_company_products_active_name ON {products} (name) WHERE deleted_at IS NULL"
    )
    # SQLite names an index within the whole database, so the new name can already be in use.
    if taken_by == "another table":
        database.execute(
            f"CREATE INDEX idx_agno_company_goals_active_name ON {database._ref('agno_company_tasks')} (title)"
        )
    else:
        database.execute(f"CREATE INDEX idx_agno_company_goals_active_name ON {products} (name)")

    await MigrationManager(database.db()).up()

    await _assert_carried_over(database)
    goals = _index_sql(database, "agno_company_goals")
    # The unique index is still there, under the name it had.
    assert "UNIQUE" in goals["idx_agno_company_products_active_name"].upper()
    assert "deleted_at IS NULL" in goals["idx_agno_company_products_active_name"].replace('"', "")
    owner = "agno_company_tasks" if taken_by == "another table" else "agno_company_goals"
    assert "UNIQUE" not in _index_sql(database, owner)["idx_agno_company_goals_active_name"].upper()
    insert = f"INSERT INTO {database._ref('agno_company_goals')} (id, name, created_at) VALUES (:id, 'AgentOS', {NOW})"
    with pytest.raises(IntegrityError):
        database.execute(insert, id="active-copy")

    described = database.describe(rows=False)
    await MigrationManager(database.db()).up()
    assert database.describe(rows=False) == described


async def test_a_second_run_changes_nothing(database):
    _write_3_2_0(database)
    await MigrationManager(database.db()).up()
    first = database.describe()

    await MigrationManager(database.db()).up()

    assert database.describe() == first


async def test_a_database_stamped_by_a_development_build_moves_to_the_release_stamp(database):
    _write_3_2_0(database)
    await MigrationManager(database.db()).up()
    migrated = database.describe(versions=False)
    # Before the release was numbered, a build of this migration stamped the tables 3.2.3.
    stamped = [name for name, version in database.versions().items() if version == "3.3.0"]
    assert "agno_company_goals" in stamped and "agno_schedules" in stamped
    for name in stamped:
        await _call(database.db().upsert_schema_version, name, "3.2.3")

    await MigrationManager(database.db()).up()

    assert database.describe(versions=False) == migrated
    versions = database.versions()
    for name in ("goals", "sources", "projects", "tasks"):
        assert versions[f"agno_company_{name}"] == "3.3.0"
    assert versions["agno_schedules"] == "3.3.0" and versions["agno_schedule_runs"] == "3.3.0"
    # A table the manager does not migrate keeps the stamp it has. Nothing reads that stamp.
    assert versions["agno_runs"] == "3.2.3"


async def test_a_new_database_gets_only_the_goal_names(database):
    db = database.db()

    await MigrationManager(db).up()
    await _call(db.initialize_company, "Company", None)
    created = await _call(_manager(db).create, name="Docs", objective="Keep the docs accurate.")

    tables = database.describe(rows=False)
    assert "agno_company_goals" in tables and "agno_company_goals_details" in tables
    assert not [name for name in tables if "product" in name]
    assert (await _call(db.get_goal, created["id"]))["objective"] == "Keep the docs accurate."


async def test_one_table_type_renames_every_company_table(database):
    _write_3_2_0(database)

    await MigrationManager(database.db()).up(table_type="projects")

    await _assert_carried_over(database)
    company = [name for name in database.describe(rows=False) if name.startswith("agno_company")]
    renamed = database.describe(versions=False)
    await MigrationManager(database.db()).up()
    after = database.describe(versions=False)
    assert {name: after[name] for name in company} == {name: renamed[name] for name in company}
    # The Routines are not a Company table: they change when their own table type is migrated.
    assert renamed["agno_schedules"] != after["agno_schedules"]


async def test_a_table_named_by_the_user_keeps_its_name(database):
    _write_company_3_2_0(database, goals_table="my_products")
    db = database.db(products_table="my_products")

    await MigrationManager(db).up()

    tables = database.describe(rows=False)
    assert "objective" in tables["my_products"]["columns"]
    assert "my_products_details" in tables and "agno_company_goals" not in tables
    assert "goal_id" in tables["agno_company_tasks"]["columns"]
    assert (await _call(db.get_goal, GOAL))["objective"] == "Keep this AgentOS current, secure and working."
    assert (await _call(db.get_company))["name"] == "Company"


async def test_down_leaves_a_migrated_database_as_it_is(database):
    _write_3_2_0(database)
    await MigrationManager(database.db()).up()
    migrated = database.describe()

    await MigrationManager(database.db()).down("3.2.2")

    assert database.describe() == migrated


@pytest.mark.parametrize("create", [False, True])
@pytest.mark.parametrize("table_type", ["goals", "company"])
async def test_before_the_migration_the_goals_tables_are_refused(database, table_type, create):
    _write_3_2_0(database)
    before = database.describe()

    with pytest.raises(MigrationRequiredError, match="MigrationManager"):
        await _call(database.db()._get_table, table_type, create_table_if_not_found=create)

    assert database.describe() == before
    await MigrationManager(database.db()).up()
    assert await _call(database.db().get_goal, GOAL) is not None


async def test_stamped_tables_do_not_hide_a_pending_rename(database):
    _write_3_2_0(database)
    for name in ("goals", "sources", "projects", "tasks"):
        await _call(database.db().upsert_schema_version, f"agno_company_{name}", "3.3.0")

    await MigrationManager(database.db()).up()

    await _assert_carried_over(database)


# -------------------------------------------------------------------- a start before the migration


async def test_two_tables_with_rows_stop_the_migration(database):
    """Before the migration has run, either table could be the one to keep."""
    _write_3_2_0(database)
    await _start_before_migrating(database)
    before = database.describe()

    with pytest.raises(v3_3_0.CompanyGoalsMigrationError) as stopped:
        await MigrationManager(database.db()).up()

    message = str(stopped.value)
    assert "agno_company_products" in message and "agno_company_goals" in message
    assert database.describe() == before


async def test_two_details_tables_with_rows_stop_the_migration(database):
    _write_3_2_0(database)
    database._patch.setattr("agno.db.utils.legacy_company_table", lambda db, table_type: None)
    await _call(database.db().initialize_company, "Company", None)
    before = database.describe()

    with pytest.raises(v3_3_0.CompanyGoalsMigrationError, match="agno_company_products_details"):
        await MigrationManager(database.db()).up()

    assert database.describe() == before


async def test_an_empty_table_beside_the_3_2_0_table_is_not_dropped(database):
    """Another session could add a Goal between a check that the table is empty and its drop."""
    _write_3_2_0(database)
    database._patch.setattr("agno.db.utils.legacy_company_table", lambda db, table_type: None)
    await _call(database.db()._get_table, "goals", create_table_if_not_found=True)
    database._patch.undo()
    before = database.describe()

    with pytest.raises(v3_3_0.CompanyGoalsMigrationError, match="agno_company_goals"):
        await MigrationManager(database.db()).up()

    assert database.describe() == before


@pytest.mark.parametrize("children", [None, "product_id", "goal_id"])
async def test_two_goals_tables_with_no_record_are_never_taken_as_migrated(database, children):
    _write_3_2_0(database)
    await _start_before_migrating(database)
    database._patch.undo()
    for name in ("sources", "projects", "tasks"):
        if children is None:
            database.execute(f"DROP TABLE {database._ref(f'agno_company_{name}')}")
        elif children == "goal_id":
            database.execute(f"ALTER TABLE {database._ref(f'agno_company_{name}')} RENAME COLUMN product_id TO goal_id")

    with pytest.raises(MigrationRequiredError):
        await _call(database.db().get_goals)
    with pytest.raises(v3_3_0.CompanyGoalsMigrationError):
        await MigrationManager(database.db()).up()


@pytest.mark.parametrize("creates", ["goals", "company"])
async def test_creating_one_company_table_does_not_settle_the_other(database, creates):
    _write_3_2_0(database)
    kept, other = ("", "_details") if creates == "company" else ("_details", "")
    # The table under test has only its 3.2.0 predecessor removed, so it is created new.
    database.execute(f"DROP TABLE {database._ref('agno_company_products' + other)}")
    database._patch.setattr("agno.db.utils.legacy_company_table", lambda db, table_type: None)
    unsettled = "goals" if creates == "company" else "company"
    await _call(database.db()._get_table, unsettled, create_table_if_not_found=True)
    database._patch.undo()
    if unsettled == "company":
        database.execute(
            f"INSERT INTO {database._ref('agno_company_goals_details')} (id, name, created_at, updated_at) "
            "VALUES ('company', 'New', 1, 1)"
        )
    with pytest.raises(v3_3_0.CompanyGoalsMigrationError):
        await MigrationManager(database.db()).up()

    await _call(database.db()._get_table, creates, create_table_if_not_found=True)

    with pytest.raises(MigrationRequiredError):
        await _call(database.db()._get_table, unsettled)
    with pytest.raises(v3_3_0.CompanyGoalsMigrationError, match=f"agno_company_products{kept}"):
        await MigrationManager(database.db()).up()


@pytest.mark.parametrize("name", ["record", "agno_company_goals_rename"])
async def test_the_stamp_of_a_configured_table_is_not_a_rename_record(database, name):
    _write_3_2_0(database)
    await _start_before_migrating(database)
    database._patch.undo()
    if name == "record":
        # The stamp alone: no database creates a table with this name.
        name = v3_3_0._rename_record("agno_company_products", "agno_company_goals")
    else:
        await _call(database.db(memory_table=name)._get_table, "memories", create_table_if_not_found=True)
    await _call(database.db().upsert_schema_version, name, "3.3.0")

    with pytest.raises(MigrationRequiredError):
        await _call(database.db().get_goals)
    with pytest.raises(v3_3_0.CompanyGoalsMigrationError):
        await MigrationManager(database.db()).up()


async def test_tables_3_2_creates_beside_those_of_a_new_database_are_not_used(database):
    """A database that never needed the migration records that too."""
    await _call(database.db()._get_table, "goals", create_table_if_not_found=True)
    await _recreate_3_2_0_tables(database)

    assert (await _call(database.db().get_goals))[1] == 0
    await MigrationManager(database.db()).up()
    assert (await _call(database.db().get_goals))[1] == 0


# -------------------------------------------------------- agno 3.2 started again after the migration


async def _recreate_3_2_0_tables(database: _Database) -> None:
    """What an agno 3.2 process writes when it starts on a migrated database."""
    engine = create_engine(database.url)
    name = database._ref("agno_company_products")
    details = database._ref("agno_company_products_details")
    json_type = "JSONB" if database.postgres else "JSON"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {name} (id VARCHAR PRIMARY KEY, name VARCHAR, purpose TEXT, user_id VARCHAR, "
                f"metadata {json_type}, created_at BIGINT, updated_at BIGINT, deleted_at BIGINT)"
            )
        )
        conn.execute(text(f"INSERT INTO {name} (id, name, purpose, created_at) VALUES ('{GOAL}', 'AgentOS', 'x', 1)"))
        conn.execute(
            text(
                f"CREATE TABLE {details} (id VARCHAR PRIMARY KEY, name VARCHAR, description TEXT, "
                "created_at BIGINT, updated_at BIGINT)"
            )
        )
        conn.execute(text(f"INSERT INTO {details} VALUES ('company', 'Other', NULL, 1, 1)"))
        versions = database._ref("agno_schema_versions")
        for table in ("agno_company_products", "agno_company_products_details"):
            statement = f"INSERT INTO {versions} (table_name, version, created_at) VALUES (:name, '3.0.0', :now)"
            conn.execute(text(statement), {"name": table, "now": "2026-11-25T00:00:00"})
    engine.dispose()


@pytest.mark.parametrize("force", [False, True])
async def test_tables_3_2_creates_again_do_not_replace_the_stored_ones(database, force):
    _write_3_2_0(database)
    await MigrationManager(database.db()).up()
    before = {name: table for name, table in database.describe().items() if name.startswith("agno_company_goals")}
    await _recreate_3_2_0_tables(database)

    outcome = await migrate_at_startup(database.db())
    await MigrationManager(database.db()).up(force=force)

    assert outcome.status == "current"
    described = database.describe()
    assert {name: table for name, table in described.items() if name.startswith("agno_company_goals")} == before
    # Nothing 3.2 wrote is dropped either.
    assert described["agno_company_products"]["rows"] and described["agno_company_products_details"]["rows"]
    db = database.db()
    assert (await _call(db.get_goal, GOAL))["objective"] == "Keep this AgentOS current, secure and working."
    assert (await _call(db.get_company))["name"] == "Company"


async def test_a_subclassed_adapter_is_migrated(database):
    _write_3_2_0(database)
    db = database.db()
    subclass = type("MyDb", (type(db),), {})

    await MigrationManager(database._open(subclass)).up()

    await _assert_carried_over(database)


# ----------------------------------------------------------------------------- a run that stops


@pytest.mark.parametrize("stop_at", ["CREATE INDEX", "DROP INDEX"])
async def test_a_run_that_stops_while_renaming_an_index(databases, monkeypatch, stop_at):
    database, fresh = databases(), databases()
    if database.postgres:
        pytest.skip("PostgreSQL renames an index in one transaction")
    _write_3_2_0(database)
    real_text = v3_3_0.text

    def stop(statement: str) -> Any:
        if statement.startswith(stop_at):
            raise RuntimeError("stopped at the index")
        return real_text(statement)

    with monkeypatch.context() as patch:
        patch.setattr(v3_3_0, "text", stop)
        with pytest.raises(RuntimeError, match="stopped at the index"):
            await MigrationManager(database.db()).up()

    await MigrationManager(database.db()).up()

    await _assert_carried_over(database)
    db = fresh.db()
    for table_type in ("goals", "sources", "projects", "tasks"):
        await _call(db._get_table, table_type, create_table_if_not_found=True)
    described, expected = database.describe(rows=False), fresh.describe(rows=False)
    for name in ("goals", "sources", "projects", "tasks"):
        name = f"agno_company_{name}"
        assert described[name]["indexes"] == expected[name]["indexes"]


async def test_a_run_that_stops_after_the_table_rename(database, monkeypatch):
    _write_3_2_0(database)
    before = database.describe()

    def stop(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("stopped after the table rename")

    with monkeypatch.context() as patch:
        patch.setattr(v3_3_0, "_rename_column", stop)
        with pytest.raises(RuntimeError, match="stopped after the table rename"):
            await MigrationManager(database.db()).up()

    stopped = database.describe()
    if database.postgres:
        # One transaction: nothing changed.
        assert stopped == before
    else:
        # SQLite keeps the rename, with the columns still under their 3.2.0 names.
        assert "agno_company_products" not in stopped
        assert "purpose" in stopped["agno_company_goals"]["columns"]
        assert "product_id" in stopped["agno_company_tasks"]["columns"]

    await MigrationManager(database.db()).up()

    await _assert_carried_over(database)
    restored = await _call(_manager(database.db()).restore, ARCHIVED_GOAL)
    assert restored is not None
    assert (await _call(database.db().get_task, ARCHIVED_TASK))["deleted_at"] is None


# ----------------------------------------------------------------------------- two databases


@pytest.mark.parametrize("company_first", [True, False], ids=["company-first", "schedules-first"])
async def test_the_company_and_the_schedules_migrate_in_either_order(databases, company_first):
    company, agent_os = databases(), databases()
    _write_company_3_2_0(company)
    _write_schedules_3_2_0(agent_os)

    for target in (company, agent_os) if company_first else (agent_os, company):
        await MigrationManager(target.db()).up()

    await _assert_carried_over(company)
    company_db, schedule_db = company.db(), agent_os.db()
    routine = await _call(schedule_db.get_schedule, ROUTINE)
    assert routine["payload"]["metadata"]["goal_id"] == GOAL
    task = await _call(company_db.get_task, ACCEPTED_TASK)
    await _check_automatic_policy(schedule_db, task)
    assert await aautomation_failures(schedule_db, company_db, goal_id=GOAL) != []


# ---------------------------------------------------------------- Routines kept outside SQL


class MongoDb:
    """Stands in for the MongoDB adapter: schedules and their runs, read and written by method."""

    def __init__(self, schedules: List[Dict[str, Any]], runs: List[Dict[str, Any]], writes: bool = True):
        self.schedules = {schedule["id"]: schedule for schedule in schedules}
        self.runs = {run["id"]: run for run in runs}
        self.writes = writes
        self.kept_updated_at: List[bool] = []

    def get_schedules(self, limit: int = 100, page: int = 1, raise_on_error: bool = False):
        rows = list(self.schedules.values())
        return rows[(page - 1) * limit : page * limit], len(rows)

    def update_schedule(self, schedule_id: str, *, preserve_updated_at: bool = False, **changes: Any):
        if not self.writes:
            return None
        self.kept_updated_at.append(preserve_updated_at)
        self.schedules[schedule_id] = {**self.schedules[schedule_id], **changes}
        return self.schedules[schedule_id]

    def get_schedule_runs(self, schedule_id: str, limit: int = 20, page: int = 1, raise_on_error: bool = False):
        rows = [run for run in self.runs.values() if run["schedule_id"] == schedule_id]
        return rows[(page - 1) * limit : page * limit], len(rows)

    def update_schedule_run(self, run_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
        self.runs[run_id] = {**self.runs[run_id], **changes}
        return self.runs[run_id]


def _stored_routine(index: int) -> Dict[str, Any]:
    return {
        "id": f"routine-{index}",
        "managed_by": "company",
        "disabled_reason": "company_product_archived",
        "payload": {"metadata": {"product_id": GOAL, "auto_accept": POLICY}},
    }


def _stored_failure(index: int) -> Dict[str, Any]:
    failure = {"task_id": f"task-{index}", "product_id": GOAL, "active": True}
    return {
        "id": f"run-{index}",
        "schedule_id": COMPANY_AUTOMATION_SCHEDULE_ID,
        "output": {"automation_failure": failure},
    }


def test_routines_in_mongodb_are_renamed_through_the_adapter():
    # More than one page of each.
    db = MongoDb([_stored_routine(index) for index in range(150)], [_stored_failure(index) for index in range(150)])

    assert v3_3_0.up(db, "schedules", "agno_schedules") is True
    assert v3_3_0.up(db, "schedule_runs", "agno_schedule_runs") is True

    for routine in db.schedules.values():
        assert routine["payload"]["metadata"]["goal_id"] == GOAL
        assert routine["payload"]["metadata"]["auto_accept"]["work_scope"] == {"goal_ids": [GOAL], "project_ids": None}
        assert routine["disabled_reason"] == "company_goal_archived"
    assert db.kept_updated_at == [True] * 150
    for run in db.runs.values():
        assert run["output"]["automation_failure"]["goal_id"] == GOAL
        assert "product_id" not in run["output"]["automation_failure"]
    # A second run finds nothing to rename.
    assert v3_3_0.up(db, "schedules", "agno_schedules") is False
    assert v3_3_0.up(db, "schedule_runs", "agno_schedule_runs") is False
    assert v3_3_0.up(db, "goals", "agno_company_goals") is False


def test_a_routine_that_cannot_be_written_fails_the_migration():
    db = MongoDb([_stored_routine(0)], [], writes=False)

    with pytest.raises(RuntimeError, match="could not update schedule routine-0"):
        v3_3_0.up(db, "schedules", "agno_schedules")
