"""Integration tests for the atomic run-field patch on real Postgres.

Proves the property the fresh-read mitigation could not: concurrent status
writes to DIFFERENT runs of the SAME session both land (row lock serializes
them), and attempt fencing rejects stale writers.
"""

import asyncio
import uuid

import pytest

from agno.db.postgres import AsyncPostgresDb

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _pg_available() -> bool:
    import socket

    try:
        with socket.create_connection(("localhost", 5532), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="Postgres not available on localhost:5532")


@pytest.fixture()
def db() -> AsyncPostgresDb:
    return AsyncPostgresDb(db_url=DB_URL, session_table=f"test_atomic_{uuid.uuid4().hex[:8]}")


@pytest.fixture(autouse=True)
def cleanup_table(db):
    yield
    import sqlalchemy

    engine = sqlalchemy.create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS agno."{db.session_table_name}"'))
    engine.dispose()


async def seed_session(db: AsyncPostgresDb, session_id: str, run_ids):
    table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
    import time as _time

    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(
                table.insert().values(
                    session_id=session_id,
                    session_type="agent",
                    runs=[{"run_id": rid, "status": "PENDING"} for rid in run_ids],
                    created_at=int(_time.time()),
                )
            )


async def get_runs(db: AsyncPostgresDb, session_id: str):
    from sqlalchemy import select

    table = await db._get_table(table_type="sessions")
    async with db.async_session_factory() as sess:
        row = (await sess.execute(select(table.c.runs).where(table.c.session_id == session_id))).fetchone()
        return {r["run_id"]: r for r in row[0]}


class TestAtomicRunPatch:
    @pytest.mark.asyncio
    async def test_concurrent_writes_to_sibling_runs_both_land(self, db):
        """The lost-update the whole-blob save suffered: N concurrent writers
        patching DIFFERENT runs of one session must all land."""
        run_ids = [f"r{i}" for i in range(6)]
        await seed_session(db, "s1", run_ids)

        await asyncio.gather(*[db.update_run_in_session("s1", rid, {"status": "RUNNING"}) for rid in run_ids])

        runs = await get_runs(db, "s1")
        assert all(runs[rid]["status"] == "RUNNING" for rid in run_ids), runs

    @pytest.mark.asyncio
    async def test_attempt_fencing_rejects_stale_writer(self, db):
        await seed_session(db, "s1", ["r1"])
        # Attempt 2 (the live reclaimed execution) writes first
        assert await db.update_run_in_session("s1", "r1", {"status": "COMPLETED"}, expected_attempt=2)
        # The zombie from attempt 1 arrives late: fenced out
        assert not await db.update_run_in_session("s1", "r1", {"status": "ERROR"}, expected_attempt=1)
        runs = await get_runs(db, "s1")
        assert runs["r1"]["status"] == "COMPLETED"
        assert runs["r1"]["queue_attempt"] == 2

    @pytest.mark.asyncio
    async def test_missing_run_or_session_returns_false(self, db):
        await seed_session(db, "s1", ["r1"])
        assert not await db.update_run_in_session("s1", "nope", {"status": "ERROR"})
        assert not await db.update_run_in_session("no-session", "r1", {"status": "ERROR"})
