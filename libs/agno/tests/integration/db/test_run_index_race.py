"""Cross-adapter regression tests for the run_index backfill race.

Every SQL adapter's ``upsert_run`` (and the Postgres append primitive)
backfills a missing run_index as MAX(run_index)+1. Read-then-insert as two
statements meant two concurrent first-saves into one session could read the
same MAX and land DUPLICATE indexes - permanently nondeterministic
``ORDER BY run_index`` hydration for that session.

The fix is per-engine, each using the strongest primitive available:
- Postgres: transaction-scoped advisory lock keyed on session_id
- MySQL:    GET_LOCK named lock, released after commit
- SQLite:   the MAX is computed inside the INSERT statement itself (atomic
            under SQLite's statement-level write lock)
- SingleStore: same inline computation via a derived table (best effort -
            the engine has no user-level locks); not covered here, no server

The hammers gather N concurrent no-index saves and assert the landed indexes
are exactly 0..N-1.
"""

import asyncio
import socket
import threading
import time
import uuid

import pytest

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
MYSQL_URL = "mysql+pymysql://ai:ai@localhost:3306/ai"
MYSQL_ASYNC_URL = "mysql+asyncmy://ai:ai@localhost:3306/ai"

N_WRITERS = 24


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=2):
            return True
    except OSError:
        return False


def _run_dict(run_id: str, session_id: str) -> dict:
    # No run_index anywhere: forces the backfill path
    return {
        "run_id": run_id,
        "session_id": session_id,
        "agent_id": "race-agent",
        "status": "PENDING",
        "content": "x",
    }


def _assert_contiguous(indexes, n: int) -> None:
    assert sorted(indexes) == list(range(n)), (
        f"concurrent backfills landed duplicate/gapped run indexes: {sorted(indexes)} - "
        "the MAX+1 read must be serialized against sibling writers"
    )


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------

pg_required = pytest.mark.skipif(not _port_open(5532), reason="Postgres not available on localhost:5532")


@pytest.fixture()
def pg_db():
    from agno.db.postgres import AsyncPostgresDb

    suffix = uuid.uuid4().hex[:8]
    db = AsyncPostgresDb(db_url=PG_URL, session_table=f"test_rir_{suffix}", runs_table=f"test_rir_runs_{suffix}")
    yield db
    import sqlalchemy

    engine = sqlalchemy.create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.runs_table_name}"'))
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.session_table_name}"'))
    engine.dispose()


async def _pg_seed_session(db, session_id: str) -> None:
    table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
    await db._get_table(table_type="runs", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(
                table.insert().values(session_id=session_id, session_type="agent", created_at=int(time.time()))
            )


async def _pg_indexes(db, session_id: str):
    from sqlalchemy import select

    runs_table = await db._get_table(table_type="runs")
    async with db.async_session_factory() as sess:
        rows = (
            await sess.execute(select(runs_table.c.run_index).where(runs_table.c.session_id == session_id))
        ).fetchall()
    return [r[0] for r in rows]


@pg_required
class TestPostgresBackfillRace:
    @pytest.mark.asyncio
    async def test_concurrent_upsert_run_backfills_are_contiguous(self, pg_db):
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        await _pg_seed_session(pg_db, session_id)
        await asyncio.gather(
            *[pg_db.upsert_run(run=_run_dict(f"r{i}", session_id), session_id=session_id) for i in range(N_WRITERS)]
        )
        _assert_contiguous(await _pg_indexes(pg_db, session_id), N_WRITERS)

    @pytest.mark.asyncio
    async def test_concurrent_append_primitive_backfills_are_contiguous(self, pg_db):
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        await _pg_seed_session(pg_db, session_id)
        results = await asyncio.gather(
            *[
                pg_db.append_run_to_session_if_absent(session_id=session_id, run_dict=_run_dict(f"r{i}", session_id))
                for i in range(N_WRITERS)
            ]
        )
        assert all(r is True for r in results)
        _assert_contiguous(await _pg_indexes(pg_db, session_id), N_WRITERS)

    @pytest.mark.asyncio
    async def test_concurrent_sync_upsert_run_backfills_are_contiguous(self, pg_db):
        from agno.db.postgres import PostgresDb

        session_id = f"s-{uuid.uuid4().hex[:8]}"
        await _pg_seed_session(pg_db, session_id)
        sync_db = PostgresDb(db_url=PG_URL, session_table=pg_db.session_table_name, runs_table=pg_db.runs_table_name)
        # Prime the lazy table cache once before fanning out: _get_table's
        # first-call construction is not thread-safe (a sibling thread can
        # observe a partially-built Table object) - a separate latent issue,
        # not what this test targets.
        await asyncio.to_thread(sync_db._get_table, table_type="runs", create_table_if_not_found=True)
        await asyncio.gather(
            *[
                asyncio.to_thread(sync_db.upsert_run, run=_run_dict(f"r{i}", session_id), session_id=session_id)
                for i in range(N_WRITERS)
            ]
        )
        _assert_contiguous(await _pg_indexes(pg_db, session_id), N_WRITERS)


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


class TestSqliteBackfillRace:
    def test_threaded_upsert_run_backfills_are_contiguous(self, tmp_path):
        from sqlalchemy import select

        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "race.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        sessions_table = db._get_table(table_type="sessions", create_table_if_not_found=True)
        db._get_table(table_type="runs", create_table_if_not_found=True)
        # SQLite enforces the runs->sessions FK: seed the parent row
        with db.Session() as sess, sess.begin():
            sess.execute(
                sessions_table.insert().values(session_id=session_id, session_type="agent", created_at=int(time.time()))
            )

        barrier = threading.Barrier(8)
        errors: list = []

        def writer(i: int) -> None:
            try:
                barrier.wait(timeout=10)
                db.upsert_run(run=_run_dict(f"r{i}", session_id), session_id=session_id)
            except Exception as e:  # surface, don't swallow
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors, f"writers raised: {errors}"

        runs_table = db._get_table(table_type="runs")
        with db.Session() as sess:
            indexes = [
                r[0]
                for r in sess.execute(
                    select(runs_table.c.run_index).where(runs_table.c.session_id == session_id)
                ).fetchall()
            ]
        _assert_contiguous(indexes, 8)

    @pytest.mark.asyncio
    async def test_async_upsert_run_sequential_indexes(self, tmp_path):
        """aiosqlite serializes on one connection - concurrency is not the
        threat here; this pins that the inline-subquery backfill still
        produces 0..N-1 through the async adapter."""
        from sqlalchemy import select

        from agno.db.sqlite import AsyncSqliteDb

        db = AsyncSqliteDb(db_file=str(tmp_path / "race_async.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        sessions_table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
        await db._get_table(table_type="runs", create_table_if_not_found=True)
        async with db.async_session_factory() as sess:
            async with sess.begin():
                await sess.execute(
                    sessions_table.insert().values(
                        session_id=session_id, session_type="agent", created_at=int(time.time())
                    )
                )
        for i in range(4):
            await db.upsert_run(run=_run_dict(f"r{i}", session_id), session_id=session_id)

        runs_table = await db._get_table(table_type="runs")
        async with db.async_session_factory() as sess:
            rows = (
                await sess.execute(select(runs_table.c.run_index).where(runs_table.c.session_id == session_id))
            ).fetchall()
        _assert_contiguous([r[0] for r in rows], 4)


# ---------------------------------------------------------------------------
# MySQL (runs only where a server is available, e.g. CI)
# ---------------------------------------------------------------------------

mysql_required = pytest.mark.skipif(not _port_open(3306), reason="MySQL not available on localhost:3306")


@mysql_required
class TestMysqlBackfillRace:
    def test_threaded_upsert_run_backfills_are_contiguous(self):
        from sqlalchemy import select

        from agno.db.mysql import MySQLDb

        suffix = uuid.uuid4().hex[:8]
        db = MySQLDb(db_url=MYSQL_URL, session_table=f"test_rir_{suffix}", runs_table=f"test_rir_runs_{suffix}")
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        sessions_table = db._get_table(table_type="sessions", create_table_if_not_found=True)
        db._get_table(table_type="runs", create_table_if_not_found=True)
        with db.Session() as sess, sess.begin():
            sess.execute(
                sessions_table.insert().values(session_id=session_id, session_type="agent", created_at=int(time.time()))
            )

        barrier = threading.Barrier(8)
        errors: list = []

        def writer(i: int) -> None:
            try:
                barrier.wait(timeout=10)
                db.upsert_run(run=_run_dict(f"r{i}", session_id), session_id=session_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors, f"writers raised: {errors}"

        runs_table = db._get_table(table_type="runs")
        with db.Session() as sess:
            indexes = [
                r[0]
                for r in sess.execute(
                    select(runs_table.c.run_index).where(runs_table.c.session_id == session_id)
                ).fetchall()
            ]
        _assert_contiguous(indexes, 8)
