"""Projected run-preview reads against live Postgres and MySQL (see the unit twin for the corpus)."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from tests.unit.db.test_session_run_previews import check_backend, check_projected_query

PG_URL = os.getenv("AGNO_TEST_PG_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")
MYSQL_URL = os.getenv("AGNO_TEST_MYSQL_URL", "mysql+pymysql://ai:ai@localhost:3306/ai")

pytestmark = pytest.mark.integration


def _reachable(url: str) -> bool:
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _tables() -> dict:
    suffix = uuid.uuid4().hex[:8]
    return {"session_table": f"previews_sessions_{suffix}", "runs_table": f"previews_runs_{suffix}"}


@pytest.fixture
def pg_schema():
    if not _reachable(PG_URL):
        pytest.skip("Postgres not reachable")
    schema = f"previews_{uuid.uuid4().hex[:8]}"
    yield schema
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
    engine.dispose()


@pytest.fixture
def mysql_tables():
    if not _reachable(MYSQL_URL):
        pytest.skip("MySQL not reachable")
    tables = _tables()
    yield tables
    engine = create_engine(MYSQL_URL)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {tables['runs_table']}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {tables['session_table']}"))
    engine.dispose()


def _pg_sync(schema: str):
    from agno.db.postgres import PostgresDb

    return PostgresDb(db_url=PG_URL, db_schema=schema)


def _pg_async(schema: str):
    from agno.db.postgres import AsyncPostgresDb

    return AsyncPostgresDb(db_url=PG_URL.replace("+psycopg:", "+psycopg_async:"), db_schema=schema)


def _mysql_sync(tables: dict):
    from agno.db.mysql import MySQLDb

    return MySQLDb(db_url=MYSQL_URL, **tables)


def _mysql_async(tables: dict):
    from agno.db.mysql import AsyncMySQLDb

    return AsyncMySQLDb(db_url=MYSQL_URL.replace("+pymysql:", "+asyncmy:"), **tables)


async def test_postgres_previews_match_full_path(pg_schema):
    await check_backend(_pg_sync(pg_schema))


async def test_postgres_previews_are_projected_in_sql(pg_schema):
    db = _pg_sync(pg_schema)
    await check_projected_query(db, db.db_engine)


async def test_async_postgres_previews_match_full_path(pg_schema):
    await check_backend(_pg_async(pg_schema))


async def test_async_postgres_previews_are_projected_in_sql(pg_schema):
    db = _pg_async(pg_schema)
    await check_projected_query(db, db.db_engine)


async def test_mysql_previews_match_full_path(mysql_tables):
    await check_backend(_mysql_sync(mysql_tables))


async def test_mysql_previews_are_projected_in_sql(mysql_tables):
    db = _mysql_sync(mysql_tables)
    await check_projected_query(db, db.db_engine)


async def test_async_mysql_previews_match_full_path(mysql_tables):
    await check_backend(_mysql_async(mysql_tables))


async def test_async_mysql_previews_are_projected_in_sql(mysql_tables):
    db = _mysql_async(mysql_tables)
    await check_projected_query(db, db.db_engine)
