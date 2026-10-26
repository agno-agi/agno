"""Company Tasks tables created by v3.1.4 migrate to the v3.1.5 shape.

v3.1.4 shipped the tasks table without origin, routine_id, dedupe_key and
metadata, and without the (product_id, dedupe_key) unique constraint that
Routine evidence deduplication relies on. Those tables were stamped 3.0.0, so
upgrading left them failing validation with no migration to apply.

SQLite cases run locally; Postgres cases run against the live pgvector
container (localhost:5532) with a unique schema per run and skip when absent.
"""

import asyncio
import time
import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.exceptions import MigrationRequiredError

TASKS_TABLE = "agno_company_tasks"
PRODUCTS_TABLE = "agno_company_products"
NEW_COLUMNS = {"origin", "routine_id", "dedupe_key", "metadata"}


def _v3_1_4_tasks_ddl(full_table: str, json_type: str) -> str:
    return f"""
        CREATE TABLE {full_table} (
            id VARCHAR PRIMARY KEY,
            title VARCHAR NOT NULL,
            brief TEXT,
            user_id VARCHAR,
            transitions {json_type},
            created_at BIGINT NOT NULL,
            updated_at BIGINT,
            deleted_at BIGINT,
            product_id VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            project_id VARCHAR,
            executor_type VARCHAR,
            executor_id VARCHAR,
            accepted_by VARCHAR,
            accepted_at BIGINT,
            session_id VARCHAR,
            job_id VARCHAR,
            evidence {json_type},
            result {json_type}
        )
    """


def _legacy_row_sql(full_table: str, product_id: str) -> str:
    return (
        f"INSERT INTO {full_table} (id, title, status, product_id, created_at) "
        f"VALUES ('legacy-task', 'Written by v3.1.4', 'backlog', '{product_id}', {int(time.time())})"
    )


def _evidence_task(product_id: str, task_id: str) -> dict:
    return {
        "id": task_id,
        "product_id": product_id,
        "title": "Routine finding",
        "status": "backlog",
        "origin": "routine",
        "routine_id": "routine-1",
        "dedupe_key": "finding-1",
        "metadata": {"source": "test"},
        "created_at": int(time.time()),
    }


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def _make_v3_1_4_sqlite(db_file: str) -> str:
    """Create a products table through the adapter and a v3.1.4-shaped tasks table beside it."""
    db = SqliteDb(db_file=db_file)
    product_id = db.create_product({"id": str(uuid.uuid4()), "name": "Acme", "created_at": int(time.time())})["id"]
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.begin() as conn:
        conn.execute(text(_v3_1_4_tasks_ddl(TASKS_TABLE, "JSON")))
        conn.execute(text(_legacy_row_sql(TASKS_TABLE, product_id)))
    engine.dispose()
    db.upsert_schema_version(TASKS_TABLE, "3.0.0")
    return product_id


def _sqlite_shape(db_file: str):
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({TASKS_TABLE})"))}
        indexes = {row[1] for row in conn.execute(text(f"PRAGMA index_list({TASKS_TABLE})"))}
    engine.dispose()
    return columns, indexes


def test_sqlite_stale_tasks_table_points_at_the_migration(tmp_path):
    db_file = str(tmp_path / "company.db")
    _make_v3_1_4_sqlite(db_file)

    with pytest.raises(MigrationRequiredError):
        SqliteDb(db_file=db_file).get_tasks()


def test_sqlite_up_migrates_and_preserves_rows(tmp_path):
    db_file = str(tmp_path / "company.db")
    product_id = _make_v3_1_4_sqlite(db_file)

    db = SqliteDb(db_file=db_file)
    asyncio.run(MigrationManager(db).up(table_type="tasks"))

    columns, indexes = _sqlite_shape(db_file)
    assert NEW_COLUMNS <= columns
    assert "uq_company_task_evidence" in indexes
    assert db.get_latest_schema_version(TASKS_TABLE) == "3.1.5"

    fresh = SqliteDb(db_file=db_file)
    assert fresh.get_task("legacy-task")["title"] == "Written by v3.1.4"

    # Evidence deduplication depends on the unique index added by the migration
    first = fresh.create_task(_evidence_task(product_id, "task-a"))
    second = fresh.create_task(_evidence_task(product_id, "task-b"))
    assert first["id"] == second["id"] == "task-a"
    assert first["metadata"] == {"source": "test"}


def test_sqlite_up_is_a_noop_on_a_current_table(tmp_path):
    """Tables created by v3.1.5-v3.1.7 already have the shape but were stamped 3.0.0."""
    db_file = str(tmp_path / "company.db")
    db = SqliteDb(db_file=db_file)
    product_id = db.create_product({"id": str(uuid.uuid4()), "name": "Acme", "created_at": int(time.time())})["id"]
    db.create_task(_evidence_task(product_id, "task-a"))
    db.upsert_schema_version(TASKS_TABLE, "3.0.0")

    from agno.db.migrations.versions import v3_1_5

    assert v3_1_5.up(db, "tasks", TASKS_TABLE) is False
    asyncio.run(MigrationManager(db).up(table_type="tasks"))
    assert db.get_latest_schema_version(TASKS_TABLE) == "3.1.5"


def test_sqlite_down_reverts(tmp_path):
    db_file = str(tmp_path / "company.db")
    _make_v3_1_4_sqlite(db_file)
    db = SqliteDb(db_file=db_file)
    asyncio.run(MigrationManager(db).up(table_type="tasks"))

    asyncio.run(MigrationManager(db).down(target_version="3.0.0", table_type="tasks"))

    columns, indexes = _sqlite_shape(db_file)
    assert not (NEW_COLUMNS & columns)
    assert "uq_company_task_evidence" not in indexes
    assert db.get_latest_schema_version(TASKS_TABLE) == "3.0.0"


def test_async_sqlite_up_migrates(tmp_path):
    pytest.importorskip("aiosqlite")
    db_file = str(tmp_path / "company.db")
    product_id = _make_v3_1_4_sqlite(db_file)

    async def run():
        db = AsyncSqliteDb(db_file=db_file)
        await MigrationManager(db).up(table_type="tasks")
        assert await db.get_latest_schema_version(TASKS_TABLE) == "3.1.5"
        first = await db.create_task(_evidence_task(product_id, "task-a"))
        second = await db.create_task(_evidence_task(product_id, "task-b"))
        assert first["id"] == second["id"] == "task-a"

    asyncio.run(run())
    columns, indexes = _sqlite_shape(db_file)
    assert NEW_COLUMNS <= columns
    assert "uq_company_task_evidence" in indexes


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _pg_reachable() -> bool:
    try:
        engine = create_engine(PG_URL)
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
def pg_schema():
    pytest.importorskip("psycopg")
    if not _pg_reachable():
        pytest.skip(f"Postgres server not reachable at {PG_URL}")
    name = f"v315_mig_{uuid.uuid4().hex[:8]}"
    yield name
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    engine.dispose()


def _make_v3_1_4_postgres(schema: str) -> str:
    from agno.db.postgres import PostgresDb

    db = PostgresDb(db_url=PG_URL, db_schema=schema)
    product_id = db.create_product({"id": str(uuid.uuid4()), "name": "Acme", "created_at": int(time.time())})["id"]
    full_table = f'"{schema}"."{TASKS_TABLE}"'
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text(_v3_1_4_tasks_ddl(full_table, "JSONB")))
        conn.execute(text(_legacy_row_sql(full_table, product_id)))
    engine.dispose()
    db.upsert_schema_version(TASKS_TABLE, "3.0.0")
    return product_id


def _pg_shape(schema: str):
    engine = create_engine(PG_URL)
    with engine.connect() as conn:
        params = {"schema": schema, "table": TASKS_TABLE}
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=:schema AND table_name=:table"
                ),
                params,
            )
        }
        constraints = {
            row[0]
            for row in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname=:schema AND tablename=:table"), params
            )
        }
    engine.dispose()
    return columns, constraints


def test_postgres_up_and_down(pg_schema):
    from agno.db.postgres import PostgresDb

    product_id = _make_v3_1_4_postgres(pg_schema)
    with pytest.raises(MigrationRequiredError):
        PostgresDb(db_url=PG_URL, db_schema=pg_schema).get_tasks()

    db = PostgresDb(db_url=PG_URL, db_schema=pg_schema)
    asyncio.run(MigrationManager(db).up(table_type="tasks"))
    columns, constraints = _pg_shape(pg_schema)
    assert NEW_COLUMNS <= columns
    assert "uq_company_task_evidence" in constraints
    assert db.get_latest_schema_version(TASKS_TABLE) == "3.1.5"

    fresh = PostgresDb(db_url=PG_URL, db_schema=pg_schema)
    assert fresh.get_task("legacy-task") is not None
    first = fresh.create_task(_evidence_task(product_id, "task-a"))
    second = fresh.create_task(_evidence_task(product_id, "task-b"))
    assert first["id"] == second["id"] == "task-a"

    asyncio.run(MigrationManager(fresh).down(target_version="3.0.0", table_type="tasks"))
    columns, constraints = _pg_shape(pg_schema)
    assert not (NEW_COLUMNS & columns)
    assert "uq_company_task_evidence" not in constraints


def test_async_postgres_up_migrates(pg_schema):
    from agno.db.postgres import AsyncPostgresDb

    product_id = _make_v3_1_4_postgres(pg_schema)

    async def run():
        db = AsyncPostgresDb(db_url=PG_URL.replace("psycopg", "psycopg_async"), db_schema=pg_schema)
        await MigrationManager(db).up(table_type="tasks")
        assert await db.get_latest_schema_version(TASKS_TABLE) == "3.1.5"
        first = await db.create_task(_evidence_task(product_id, "task-a"))
        second = await db.create_task(_evidence_task(product_id, "task-b"))
        assert first["id"] == second["id"] == "task-a"

    asyncio.run(run())
    columns, constraints = _pg_shape(pg_schema)
    assert NEW_COLUMNS <= columns
    assert "uq_company_task_evidence" in constraints
