"""Fixtures for the DbFileSystem integration suite: same matrix on both dialects.

The Postgres lane targets the pgvector container from cookbook/scripts/run_pgvector.sh
(host port 5532, db/user/pass all `ai`) with an eager-connect fixture — no skip
markers. Everything lives in `test_schema`, dropped at session end.
"""

import pytest
from sqlalchemy import create_engine, text

from agno.fs.db import DbFileSystem

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
DIALECTS = ["sqlite", "postgresql"]


@pytest.fixture(scope="session")
def pg_engine():
    """Eager-connect Postgres engine (tests/integration/conftest.py pattern)."""
    engine = create_engine(PG_URL)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.commit()
    yield engine
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS test_schema CASCADE"))
        conn.commit()
    engine.dispose()


@pytest.fixture(params=DIALECTS)
def db_fs(request, tmp_path):
    """A DbFileSystem per dialect. Postgres rows are wiped after each test."""
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path}/agent_fs.db", connect_args={"timeout": 30})
        yield DbFileSystem(db_engine=engine)
        engine.dispose()
    else:
        engine = request.getfixturevalue("pg_engine")
        fs = DbFileSystem(db_engine=engine, db_schema="test_schema")
        yield fs
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS test_schema.{fs.table_name}"))
