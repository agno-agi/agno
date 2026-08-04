"""Integration tests for the atomic queued-run prepare on real Postgres.

Phase-3 item 9 (lean): aprepare_queued_run must never whole-session-save.
The fresh-session path used to be an unlocked read-check-save, and a worker
that claimed, created the session, and COMPLETED the run inside that window
was clobbered back to PENDING by the accepting request's stale save. The
prepare now creates a missing session row EMPTY via insert-if-absent and
retries the row-locked append - both steps decline to a concurrent winner.
"""

import time
import uuid

import pytest

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb, PostgresDb

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
    return AsyncPostgresDb(db_url=DB_URL, session_table=f"test_prep_{uuid.uuid4().hex[:8]}")


@pytest.fixture(autouse=True)
def cleanup_table(db):
    yield
    import sqlalchemy

    engine = sqlalchemy.create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.session_table_name}"'))
    engine.dispose()


async def read_runs(db: AsyncPostgresDb, session_id: str):
    from sqlalchemy import select

    table = await db._get_table(table_type="sessions")
    async with db.async_session_factory() as sess:
        row = (await sess.execute(select(table.c.runs).where(table.c.session_id == session_id))).fetchone()
        return list(row[0]) if row is not None and row[0] else []


async def worker_completes_run(db: AsyncPostgresDb, session_id: str, run_id: str) -> None:
    """Simulate the racing worker: session row created with the run already
    COMPLETED (claim + execute + terminal save, all inside the accepting
    request's read-save window)."""
    table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(
                table.insert().values(
                    session_id=session_id,
                    session_type="agent",
                    agent_id="prep-agent",
                    runs=[{"run_id": run_id, "status": "COMPLETED", "content": "done"}],
                    created_at=int(time.time()),
                )
            )


class TestPrepareNeverClobbersConcurrentCompletion:
    @pytest.mark.asyncio
    async def test_fresh_session_prepare_loses_to_completed_run(self, db, monkeypatch):
        """The exact TOCTOU the accept grace only narrowed: no session row
        exists when the prepare starts, and the worker's completed session
        lands right after the prepare's read. The stale save used to
        overwrite runs wholesale - COMPLETED back to PENDING, silently.

        The injection point sits inside aread_or_create_session, which both
        the old fallback and the new atomic path pass through: the real read
        happens (session missing -> fresh in-memory object), then the
        worker's completed row lands, then the stale object is returned."""
        from agno.os.job_queue import aprepare_queued_run

        session_id = f"s-{uuid.uuid4().hex[:8]}"
        run_id = f"r-{uuid.uuid4().hex[:8]}"
        agent = Agent(id="prep-agent", name="Prep Agent", db=db)
        await db._get_table(table_type="sessions", create_table_if_not_found=True)

        import agno.agent._storage as _storage

        real_read = _storage.aread_or_create_session

        async def read_then_lose_race(component, session_id=None, user_id=None):
            session = await real_read(component, session_id=session_id, user_id=user_id)
            await worker_completes_run(db, session_id, run_id)
            return session

        monkeypatch.setattr("agno.agent._storage.aread_or_create_session", read_then_lose_race)

        await aprepare_queued_run(agent, "agent", run_id, session_id, None, "hello")

        runs = await read_runs(db, session_id)
        assert len(runs) == 1, f"expected exactly the worker's run, got {runs}"
        assert runs[0]["run_id"] == run_id
        assert str(runs[0]["status"]).upper() == "COMPLETED", (
            "the accepting request's prepare clobbered a concurrently completed run back to "
            f"{runs[0]['status']} - the prepare must never whole-session-save"
        )

    @pytest.mark.asyncio
    async def test_prepare_lands_pending_row_when_unraced(self, db):
        """The happy path still works end to end: no session row, no racing
        worker - the prepare creates the empty session and appends PENDING."""
        from agno.os.job_queue import aprepare_queued_run

        session_id = f"s-{uuid.uuid4().hex[:8]}"
        run_id = f"r-{uuid.uuid4().hex[:8]}"
        agent = Agent(id="prep-agent", name="Prep Agent", db=db)

        await aprepare_queued_run(agent, "agent", run_id, session_id, None, "hello")

        runs = await read_runs(db, session_id)
        assert len(runs) == 1 and runs[0]["run_id"] == run_id
        assert str(runs[0]["status"]).upper() == "PENDING"


class TestInsertSessionIfAbsentContract:
    @pytest.mark.asyncio
    async def test_insert_then_decline_async(self, db):
        from agno.session import AgentSession

        sid = f"s-{uuid.uuid4().hex[:8]}"
        session = AgentSession(session_id=sid, agent_id="a1", runs=[], created_at=int(time.time()))
        assert await db.insert_session_if_absent(session) is True
        assert await db.insert_session_if_absent(session) is False, "an existing row must never be touched"

    def test_insert_then_decline_sync(self, db):
        from agno.session import AgentSession

        sync_db = PostgresDb(db_url=DB_URL, session_table=db.session_table_name)
        sid = f"s-{uuid.uuid4().hex[:8]}"
        session = AgentSession(session_id=sid, agent_id="a1", runs=[], created_at=int(time.time()))
        assert sync_db.insert_session_if_absent(session) is True
        assert sync_db.insert_session_if_absent(session) is False
