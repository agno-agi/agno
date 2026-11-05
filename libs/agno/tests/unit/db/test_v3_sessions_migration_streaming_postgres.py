"""The v3.0.0 sessions migration must not hold the whole legacy table in memory.

up() moves every run out of the sessions `runs` column into the runs table. The
legacy table can be tens of GB, so the read has to stream: memory is bounded by
one batch of sessions, never by the table. These tests pin that on the sync and
the async PostgreSQL adapter, and pin that streaming still copies every run.

Runs against the live pgvector container (localhost:5532) with a unique schema per
test; skips cleanly when psycopg or the server is absent.
"""

import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, event, text

from agno.db.migrations.manager import MigrationManager

pytest.importorskip("psycopg")

from agno.db.postgres import AsyncPostgresDb, PostgresDb  # noqa: E402

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
SESSIONS_TABLE = "agno_sessions"
RUNS_PER_SESSION = 20

# More than two migration batches, so cursors are observed while rows remain unread.
SMALL_SESSIONS = 120
# ~300 MB of runs JSON: far above one batch, well within a CI runner's memory.
LARGE_SESSIONS = 1500
RUN_BYTES = 10_000
# Streaming costs a few batches of rows; buffering costs the whole table (>1x).
MAX_GROWTH_FRACTION = 0.5


def _server_reachable() -> bool:
    # A raw probe, not an adapter call: adapter methods catch and log
    # connection errors, so they cannot signal an absent server.
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _postgres_server():
    if not _server_reachable():
        pytest.skip(f"Postgres server not reachable at {DB_URL}")


@pytest.fixture
def schema(_postgres_server):
    name = f"v3_stream_{uuid.uuid4().hex[:8]}"
    yield name
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
        conn.commit()
    engine.dispose()


def _seed_legacy_sessions(schema: str, sessions: int, run_bytes: int = 1_000) -> int:
    """Build a 2.x-shaped sessions table (runs JSONB column, no version stamp).

    Returns:
        The size in bytes of the runs JSON the migration has to move.
    """
    PostgresDb(db_url=DB_URL, db_schema=schema, session_table=SESSIONS_TABLE)._get_table(
        table_type="sessions", create_table_if_not_found=True
    )
    engine = create_engine(DB_URL)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE "{schema}"."{SESSIONS_TABLE}" ADD COLUMN runs jsonb'))
            conn.execute(
                text(
                    f'INSERT INTO "{schema}"."{SESSIONS_TABLE}" (session_id, session_type, user_id, created_at, runs) '
                    "SELECT 's' || s, 'agent', 'u' || (s % 50), 1700000000, "
                    "  (SELECT jsonb_agg(jsonb_build_object("
                    "      'run_id', 'r' || s || '_' || r, 'agent_id', 'a1', 'status', 'COMPLETED', "
                    "      'created_at', 1700000000 + r, "
                    "      'content', repeat(md5(random()::text), :reps))) "
                    "   FROM generate_series(1, :runs) r) "
                    "FROM generate_series(1, :sessions) s"
                ),
                {"reps": max(run_bytes // 32, 1), "runs": RUNS_PER_SESSION, "sessions": sessions},
            )
            # A table created by this version is stamped current; a 2.x one has no stamp.
            conn.execute(
                text(f'DELETE FROM "{schema}"."agno_schema_versions" WHERE table_name = :t'),
                {"t": SESSIONS_TABLE},
            )
            payload = conn.execute(
                text(f'SELECT sum(octet_length(runs::text)) FROM "{schema}"."{SESSIONS_TABLE}"')
            ).scalar()
    finally:
        engine.dispose()
    return int(payload)


def _scalar(query: str) -> int:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            return int(conn.execute(text(query)).scalar())
    finally:
        engine.dispose()


def _runs_copied(schema: str) -> int:
    return _scalar(f'SELECT count(*) FROM "{schema}"."agno_runs"')


def _legacy_runs_kept(schema: str) -> int:
    return _scalar(f'SELECT count(*) FROM "{schema}"."{SESSIONS_TABLE}" WHERE runs IS NOT NULL')


def _watch_open_cursors_at_insert(engine) -> list:
    """Record how many cursors on the sessions table are open each time a run row is inserted.

    pg_cursors lists the cursors of the current database session, so the probe runs on the
    migration's own connection. A server-side cursor stays open while its rows are consumed;
    a client-side read has already been fully buffered and left none open.
    """
    seen: list = []

    @event.listens_for(engine, "before_cursor_execute")
    def _probe(conn, cursor, statement, parameters, context, executemany):
        if not statement.lstrip().upper().startswith("INSERT INTO") or "agno_runs" not in statement:
            return
        open_cursors = conn.exec_driver_sql(
            f"SELECT count(*) FROM pg_cursors WHERE position('{SESSIONS_TABLE}' in statement) > 0"
        ).scalar()
        seen.append(open_cursors)

    return seen


# ---------------------------------------------------------------------------
# Every run is still copied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_migration_copies_every_run_and_keeps_the_legacy_column(schema):
    _seed_legacy_sessions(schema, SMALL_SESSIONS)
    db = PostgresDb(db_url=DB_URL, db_schema=schema, session_table=SESSIONS_TABLE)

    await MigrationManager(db).up(table_type="sessions")

    assert _runs_copied(schema) == SMALL_SESSIONS * RUNS_PER_SESSION
    assert _legacy_runs_kept(schema) == SMALL_SESSIONS


@pytest.mark.asyncio
async def test_async_postgres_migration_copies_every_run_and_keeps_the_legacy_column(schema):
    _seed_legacy_sessions(schema, SMALL_SESSIONS)
    db = AsyncPostgresDb(db_url=DB_URL, db_schema=schema, session_table=SESSIONS_TABLE)

    await MigrationManager(db).up(table_type="sessions")

    assert _runs_copied(schema) == SMALL_SESSIONS * RUNS_PER_SESSION
    assert _legacy_runs_kept(schema) == SMALL_SESSIONS


# ---------------------------------------------------------------------------
# The read is a server-side cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_migration_reads_sessions_through_a_server_side_cursor(schema):
    """While runs are being inserted, the SELECT over the sessions table is still an open cursor."""
    _seed_legacy_sessions(schema, SMALL_SESSIONS)
    db = PostgresDb(db_url=DB_URL, db_schema=schema, session_table=SESSIONS_TABLE)
    open_cursors = _watch_open_cursors_at_insert(db.db_engine)

    await MigrationManager(db).up(table_type="sessions")

    assert len(open_cursors) > 1, f"expected one insert per batch, saw {open_cursors}"
    assert all(n >= 1 for n in open_cursors), (
        f"the sessions SELECT was fully buffered client-side before the first insert: open cursors {open_cursors}"
    )


@pytest.mark.asyncio
async def test_async_postgres_migration_reads_sessions_through_a_server_side_cursor(schema):
    _seed_legacy_sessions(schema, SMALL_SESSIONS)
    db = AsyncPostgresDb(db_url=DB_URL, db_schema=schema, session_table=SESSIONS_TABLE)
    open_cursors = _watch_open_cursors_at_insert(db.db_engine.sync_engine)

    await MigrationManager(db).up(table_type="sessions")

    assert len(open_cursors) > 1, f"expected one insert per batch, saw {open_cursors}"
    assert all(n >= 1 for n in open_cursors), (
        f"the sessions SELECT was fully buffered client-side before the first insert: open cursors {open_cursors}"
    )


# ---------------------------------------------------------------------------
# Memory is bounded by the batch, not the table
# ---------------------------------------------------------------------------

# Peak RSS is a process-wide high-water mark, so the migration runs in a fresh process.
_CHILD = """
import asyncio, resource, sys

from agno.db.migrations.manager import MigrationManager
from agno.db.postgres import AsyncPostgresDb, PostgresDb

mode, url, schema, table = sys.argv[1:5]
db = (AsyncPostgresDb if mode == "async" else PostgresDb)(db_url=url, db_schema=schema, session_table=table)


def peak_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # macOS reports bytes, Linux KiB


before = peak_bytes()
asyncio.run(MigrationManager(db).up(table_type="sessions"))
print(peak_bytes() - before)
"""


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_migration_memory_does_not_grow_with_the_legacy_table(schema, mode):
    payload = _seed_legacy_sessions(schema, LARGE_SESSIONS, run_bytes=RUN_BYTES)

    done = subprocess.run(
        [sys.executable, "-c", _CHILD, mode, DB_URL, schema, SESSIONS_TABLE],
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert done.returncode == 0, done.stderr[-2000:]
    growth = int(done.stdout.strip().splitlines()[-1])
    assert _runs_copied(schema) == LARGE_SESSIONS * RUNS_PER_SESSION
    assert growth < payload * MAX_GROWTH_FRACTION, (
        f"{mode} migration grew peak memory by {growth / 1e6:.0f} MB while moving "
        f"{payload / 1e6:.0f} MB of runs; the read is buffering the table instead of streaming it"
    )
