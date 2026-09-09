"""Fixtures for the DbFileSystem integration suite: same matrix on both dialects.

The Postgres lane targets the pgvector container from cookbook/scripts/run_pgvector.sh
(host port 5532, db/user/pass all `ai`) with an eager-connect fixture — no skip
markers.

Isolation: this suite gets its OWN Postgres schema, unique per process
(`agentfs_test_<pid>`). A dozen other integration suites share and repeatedly
`DROP SCHEMA test_schema CASCADE`; a shared schema (or table) means two concurrent
pytest processes — cross-suite, or `-p xdist`, or the same suite run twice — clobber
each other's table between a `create_all(checkfirst=True)` and the DML that follows,
surfacing as `relation "…agno_fs" does not exist`. A per-process schema removes
every such cross-process race; it is created once and dropped CASCADE at session end.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from agno.fs.db import DbFileSystem

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
PG_SCHEMA = f"agentfs_test_{os.getpid()}"
DIALECTS = ["sqlite", "postgresql"]


@pytest.fixture(scope="session")
def pg_engine():
    """Eager-connect Postgres engine with a private, per-process schema.

    Skips when no server is reachable. CI runs this directory in a job with no
    database service (the release workflow's `test-remaining`, which excludes the
    other db-dependent suites by path), so an unguarded connect fails the whole
    job. Skipping keeps the SQLite half of every matrix running there while the
    Postgres half still runs for anyone with the container up. The skip is loud
    in pytest output, so a genuinely broken local Postgres is still visible.
    """
    engine = create_engine(PG_URL)
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as e:
        engine.dispose()
        pytest.skip(f"Postgres not reachable at {PG_URL} ({type(e).__name__}); run cookbook/scripts/run_pgvector.sh")
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{PG_SCHEMA}"'))
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{PG_SCHEMA}" CASCADE'))
    engine.dispose()


@pytest.fixture(params=DIALECTS)
def db_fs(request, tmp_path):
    """A DbFileSystem per dialect. Postgres state is wiped after each test."""
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path}/agent_fs.db", connect_args={"timeout": 30})
        yield DbFileSystem(db_engine=engine)
        engine.dispose()
    else:
        engine = request.getfixturevalue("pg_engine")
        fs = DbFileSystem(db_engine=engine, db_schema=PG_SCHEMA)
        yield fs
        # Drop the table (not the schema) between tests: only this process uses this
        # schema, so this is race-free, and the next test's DbFileSystem re-creates it.
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{PG_SCHEMA}".{fs.table_name}'))
