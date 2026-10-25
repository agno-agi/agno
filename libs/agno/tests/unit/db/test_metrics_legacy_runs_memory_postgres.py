"""A metrics refresh must not load the legacy sessions `runs` column into memory.

The v3.0.0 migration copies runs into the runs table but keeps the legacy `runs` column
until cleanup_legacy_runs_column() is called. Metrics only need each run's model and
provider, so a refresh must not pull those blobs into the process. These tests pin that
on the sync and the async PostgreSQL adapter, and pin that runs are still counted once
whether they live in the runs table, only in the legacy column, or in both.

Runs against the live pgvector container (localhost:5532) with a unique schema per
test; skips cleanly when psycopg or the server is absent.
"""

import subprocess
import sys
import time
import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.db.migrations.manager import MigrationManager

pytest.importorskip("psycopg")

from agno.db.postgres import AsyncPostgresDb, PostgresDb  # noqa: E402
from agno.session.agent import AgentSession  # noqa: E402

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
SESSIONS_TABLE = "agno_sessions"
RUNS_PER_SESSION = 20

SMALL_SESSIONS = 10
# ~300 MB of runs JSON: far above what a refresh needs, well within a CI runner's memory.
LARGE_SESSIONS = 1500
RUN_BYTES = 10_000
# Loading the legacy column costs the whole payload (>1x); reading model and provider costs a fraction.
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
    name = f"v3_metrics_{uuid.uuid4().hex[:8]}"
    yield name
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
        conn.commit()
    engine.dispose()


def _seed_legacy_sessions(schema: str, sessions: int, first: int = 1, run_bytes: int = 1_000) -> int:
    """Add 2.x-shaped sessions (runs held in the legacy JSONB column), created yesterday.

    Returns:
        The size in bytes of the legacy runs JSON on the sessions table.
    """
    PostgresDb(db_url=DB_URL, db_schema=schema, session_table=SESSIONS_TABLE)._get_table(
        table_type="sessions", create_table_if_not_found=True
    )
    engine = create_engine(DB_URL)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE "{schema}"."{SESSIONS_TABLE}" ADD COLUMN IF NOT EXISTS runs jsonb'))
            conn.execute(
                text(
                    f'INSERT INTO "{schema}"."{SESSIONS_TABLE}" (session_id, session_type, user_id, created_at, runs) '
                    "SELECT 's' || s, 'agent', 'u1', CAST(:created_at AS bigint), "
                    "  (SELECT jsonb_agg(jsonb_build_object("
                    "      'run_id', 'r' || s || '_' || r, 'agent_id', 'a1', 'status', 'COMPLETED', "
                    "      'created_at', CAST(:created_at AS bigint) + r, 'model', 'gpt-5.5', 'model_provider', 'OpenAI', "
                    "      'content', repeat(md5(random()::text), CAST(:reps AS int)))) "
                    "   FROM generate_series(1, CAST(:runs AS int)) r) "
                    "FROM generate_series(CAST(:first AS int), CAST(:last AS int)) s"
                ),
                {
                    "created_at": int(time.time()) - 86400,
                    "reps": max(run_bytes // 32, 1),
                    "runs": RUNS_PER_SESSION,
                    "first": first,
                    "last": first + sessions - 1,
                },
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


async def _migrate(schema: str) -> None:
    await MigrationManager(PostgresDb(db_url=DB_URL, db_schema=schema, session_table=SESSIONS_TABLE)).up(
        table_type="sessions"
    )


def _db(mode: str, schema: str):
    return (AsyncPostgresDb if mode == "async" else PostgresDb)(
        db_url=DB_URL, db_schema=schema, session_table=SESSIONS_TABLE
    )


async def _calculate_metrics(db):
    if isinstance(db, AsyncPostgresDb):
        return await db.calculate_metrics()
    return db.calculate_metrics()


# ---------------------------------------------------------------------------
# Every run is counted once, wherever it is stored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_metrics_count_migrated_and_unmigrated_runs_once(schema, mode):
    """Migrated sessions count from the runs table, unmigrated ones from the legacy column."""
    _seed_legacy_sessions(schema, SMALL_SESSIONS)
    await _migrate(schema)
    # Added after the migration, so these runs exist only in the legacy column
    _seed_legacy_sessions(schema, SMALL_SESSIONS, first=SMALL_SESSIONS + 1)
    # Written by v3 after the upgrade, so its legacy runs column is NULL
    PostgresDb(db_url=DB_URL, db_schema=schema, session_table=SESSIONS_TABLE).upsert_session(
        AgentSession(session_id="v3_session", agent_id="a1", user_id="u1", created_at=int(time.time()) - 86400)
    )

    result = await _calculate_metrics(_db(mode, schema))

    assert result is not None and len(result) == 1
    expected_runs = 2 * SMALL_SESSIONS * RUNS_PER_SESSION
    assert result[0]["agent_sessions_count"] == 2 * SMALL_SESSIONS + 1
    assert result[0]["agent_runs_count"] == expected_runs
    assert result[0]["model_metrics"] == [{"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": expected_runs}]


@pytest.mark.asyncio
@pytest.mark.parametrize("migrated", [True, False], ids=["migrated", "unmigrated"])
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_metrics_default_missing_model_provider_to_empty(schema, mode, migrated):
    """A run without model_provider is reported with an empty provider, not "None", before and after migration."""
    _seed_legacy_sessions(schema, 1)
    engine = create_engine(DB_URL)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(f'UPDATE "{schema}"."{SESSIONS_TABLE}" SET runs = :runs'),
                {"runs": '[{"run_id": "r1", "model": "test-model"}]'},
            )
    finally:
        engine.dispose()
    if migrated:
        await _migrate(schema)

    result = await _calculate_metrics(_db(mode, schema))

    assert result is not None and len(result) == 1
    assert result[0]["model_metrics"] == [{"model_id": "test-model", "model_provider": "", "count": 1}]


# ---------------------------------------------------------------------------
# Memory is bounded by what metrics need, not by the legacy column
# ---------------------------------------------------------------------------

# Peak RSS is a process-wide high-water mark, so the refresh runs in a fresh process.
_CHILD = """
import asyncio, resource, sys

from agno.db.postgres import AsyncPostgresDb, PostgresDb

mode, url, schema, table = sys.argv[1:5]
db = (AsyncPostgresDb if mode == "async" else PostgresDb)(db_url=url, db_schema=schema, session_table=table)


def peak_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # macOS reports bytes, Linux KiB


before = peak_bytes()
result = asyncio.run(db.calculate_metrics()) if mode == "async" else db.calculate_metrics()
print(sum(row["agent_runs_count"] for row in result or []))
print(peak_bytes() - before)
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("migrated", [True, False], ids=["migrated", "unmigrated"])
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_metrics_refresh_memory_does_not_grow_with_the_legacy_column(schema, mode, migrated):
    payload = _seed_legacy_sessions(schema, LARGE_SESSIONS, run_bytes=RUN_BYTES)
    if migrated:
        await _migrate(schema)

    done = subprocess.run(
        [sys.executable, "-c", _CHILD, mode, DB_URL, schema, SESSIONS_TABLE],
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert done.returncode == 0, done.stderr[-2000:]
    runs_counted, growth = (int(line) for line in done.stdout.strip().splitlines()[-2:])
    assert runs_counted == LARGE_SESSIONS * RUNS_PER_SESSION
    assert growth < payload * MAX_GROWTH_FRACTION, (
        f"{mode} metrics refresh grew peak memory by {growth / 1e6:.0f} MB with "
        f"{payload / 1e6:.0f} MB of legacy runs; the refresh is loading the legacy runs column"
    )
