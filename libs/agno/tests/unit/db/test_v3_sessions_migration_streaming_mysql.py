"""The v3.0.0 sessions migration must not hold the whole legacy table in memory on MySQL.

up() moves every run out of the sessions `runs` column into the runs table. The
sync adapter streams the read on its own connection, because an unbuffered MySQL
result blocks its connection until fully read; the async adapter pages by primary
key, because asyncmy buffers a streamed result anyway. These tests pin bounded
memory, every run copied and the inserts still all-or-nothing, on both adapters.

Runs against a live MySQL (localhost:3306, see cookbook/scripts/run_mysql.sh) with
unique table names per test; skips cleanly when the drivers or the server are absent.
"""

import json
import subprocess
import sys
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text

from agno.db.migrations.manager import MigrationManager

pytest.importorskip("pymysql")
pytest.importorskip("asyncmy")

from agno.db.migrations.versions import v3_0_0  # noqa: E402
from agno.db.mysql import AsyncMySQLDb, MySQLDb  # noqa: E402

DB_URL = "mysql+pymysql://ai:ai@localhost:3306/ai"
ASYNC_DB_URL = "mysql+asyncmy://ai:ai@localhost:3306/ai"
DB_SCHEMA = "ai"
RUNS_PER_SESSION = 20

# More than two migration batches.
SMALL_SESSIONS = 120
# Streaming holds a few batches whatever the table size; buffering holds the whole table.
MEMORY_SMALL_SESSIONS = 500
MEMORY_LARGE_SESSIONS = 2000
RUN_BYTES = 10_000
MAX_GROWTH_PER_EXTRA_BYTE = 0.5


def _server_reachable() -> bool:
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
def _mysql_server():
    if not _server_reachable():
        pytest.skip(f"MySQL server not reachable at {DB_URL}")


def _new_tables() -> dict:
    suffix = uuid.uuid4().hex[:8]
    return {
        "session_table": f"v3s_sessions_{suffix}",
        "runs_table": f"v3s_runs_{suffix}",
        "versions_table": f"v3s_versions_{suffix}",
    }


def _drop_tables(tables: dict) -> None:
    engine = create_engine(DB_URL)
    try:
        with engine.begin() as conn:
            for name in (tables["runs_table"], tables["session_table"], tables["versions_table"]):
                conn.execute(text(f"DROP TABLE IF EXISTS `{DB_SCHEMA}`.`{name}`"))
    finally:
        engine.dispose()


@pytest.fixture
def tables(_mysql_server):
    names = _new_tables()
    yield names
    _drop_tables(names)


def _db(mode: str, tables: dict):
    if mode == "async":
        return AsyncMySQLDb(db_url=ASYNC_DB_URL, db_schema=DB_SCHEMA, **tables)
    return MySQLDb(db_url=DB_URL, db_schema=DB_SCHEMA, **tables)


def _seed_legacy_sessions(tables: dict, sessions: int, run_bytes: int = 1_000) -> int:
    """Build a 2.x-shaped sessions table (runs JSON column, no version stamp).

    Returns:
        The size in bytes of the runs JSON the migration has to move.
    """
    MySQLDb(db_url=DB_URL, db_schema=DB_SCHEMA, **tables)._get_table(
        table_type="sessions", create_table_if_not_found=True
    )
    sessions_table = f"`{DB_SCHEMA}`.`{tables['session_table']}`"
    engine = create_engine(DB_URL)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {sessions_table} ADD COLUMN runs JSON"))
            conn.execute(text("SET SESSION cte_max_recursion_depth = 100000"))
            conn.execute(
                text(
                    f"INSERT INTO {sessions_table} (session_id, session_type, user_id, created_at, runs) "
                    "WITH RECURSIVE s(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM s WHERE n < :sessions), "
                    "r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < :runs) "
                    "SELECT CONCAT('s', s.n), 'agent', CONCAT('u', s.n % 50), 1700000000, "
                    "  (SELECT JSON_ARRAYAGG(JSON_OBJECT("
                    "      'run_id', CONCAT('r', s.n, '_', r.n), 'agent_id', 'a1', 'status', 'COMPLETED', "
                    "      'created_at', 1700000000 + r.n, "
                    "      'content', REPEAT(MD5(RAND()), :reps))) FROM r) "
                    "FROM s"
                ),
                {"reps": max(run_bytes // 32, 1), "runs": RUNS_PER_SESSION, "sessions": sessions},
            )
            # A table created by this version is stamped current; a 2.x one has no stamp.
            conn.execute(
                text(f"DELETE FROM `{DB_SCHEMA}`.`{tables['versions_table']}` WHERE table_name = :t"),
                {"t": tables["session_table"]},
            )
            payload = conn.execute(text(f"SELECT SUM(LENGTH(CAST(runs AS CHAR))) FROM {sessions_table}")).scalar()
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


def _runs_copied(tables: dict) -> int:
    return _scalar(f"SELECT COUNT(*) FROM `{DB_SCHEMA}`.`{tables['runs_table']}`")


def _legacy_runs_kept(tables: dict) -> int:
    return _scalar(f"SELECT COUNT(*) FROM `{DB_SCHEMA}`.`{tables['session_table']}` WHERE runs IS NOT NULL")


# ---------------------------------------------------------------------------
# Every run is still copied, in one transaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_mysql_migration_copies_every_run_and_keeps_the_legacy_column(tables, mode):
    _seed_legacy_sessions(tables, SMALL_SESSIONS)

    await MigrationManager(_db(mode, tables)).up(table_type="sessions")

    assert _runs_copied(tables) == SMALL_SESSIONS * RUNS_PER_SESSION
    assert _legacy_runs_kept(tables) == SMALL_SESSIONS


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_mysql_migration_failure_mid_copy_leaves_no_runs(tables, mode):
    """The read moved to its own connection; the inserts must still commit or roll back together."""
    _seed_legacy_sessions(tables, SMALL_SESSIONS)
    build_run_rows = v3_0_0._build_run_rows
    calls = {"n": 0}

    def fail_in_second_batch(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > v3_0_0.BATCH_SIZE:
            raise RuntimeError("boom")
        return build_run_rows(*args, **kwargs)

    with patch.object(v3_0_0, "_build_run_rows", side_effect=fail_in_second_batch), pytest.raises(RuntimeError):
        await MigrationManager(_db(mode, tables)).up(table_type="sessions")

    assert calls["n"] > v3_0_0.BATCH_SIZE, "the failure never fired"
    assert _runs_copied(tables) == 0


# ---------------------------------------------------------------------------
# Memory is bounded by the batch, not the table
# ---------------------------------------------------------------------------

# Peak RSS is a process-wide high-water mark, so each migration runs in a fresh process.
_CHILD = """
import asyncio, json, resource, sys

from agno.db.migrations.manager import MigrationManager
from agno.db.mysql import AsyncMySQLDb, MySQLDb

mode, url, schema, tables = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4])
db = (AsyncMySQLDb if mode == "async" else MySQLDb)(db_url=url, db_schema=schema, **tables)


def peak_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # macOS reports bytes, Linux KiB


before = peak_bytes()
asyncio.run(MigrationManager(db).up(table_type="sessions"))
print(peak_bytes() - before)
"""


def _migration_growth(mode: str, sessions: int) -> tuple:
    """Seed a legacy table, migrate it in a fresh process, and return (payload bytes, peak growth bytes)."""
    tables = _new_tables()
    try:
        payload = _seed_legacy_sessions(tables, sessions, run_bytes=RUN_BYTES)
        done = subprocess.run(
            [
                sys.executable,
                "-c",
                _CHILD,
                mode,
                ASYNC_DB_URL if mode == "async" else DB_URL,
                DB_SCHEMA,
                json.dumps(tables),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert done.returncode == 0, done.stderr[-2000:]
        assert _runs_copied(tables) == sessions * RUNS_PER_SESSION
        return payload, int(done.stdout.strip().splitlines()[-1])
    finally:
        _drop_tables(tables)


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_mysql_migration_memory_does_not_grow_with_the_legacy_table(_mysql_server, mode):
    small_payload, small_growth = _migration_growth(mode, MEMORY_SMALL_SESSIONS)
    large_payload, large_growth = _migration_growth(mode, MEMORY_LARGE_SESSIONS)

    extra_payload = large_payload - small_payload
    extra_growth = large_growth - small_growth
    assert extra_growth < extra_payload * MAX_GROWTH_PER_EXTRA_BYTE, (
        f"{mode} migration peak memory grew {extra_growth / 1e6:.0f} MB more for "
        f"{extra_payload / 1e6:.0f} MB more runs; the read is buffering the table instead of streaming it"
    )
