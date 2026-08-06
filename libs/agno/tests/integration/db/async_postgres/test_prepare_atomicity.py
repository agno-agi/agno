"""Integration tests for the atomic queued-run prepare on real Postgres.

aprepare_queued_run must never whole-session-save.
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
    # Unique RUNS table too: its FK binds to the session table name at
    # creation time, so a shared default runs table would reference a
    # previous test's dropped session table
    suffix = uuid.uuid4().hex[:8]
    return AsyncPostgresDb(db_url=DB_URL, session_table=f"test_prep_{suffix}", runs_table=f"test_prep_runs_{suffix}")


@pytest.fixture(autouse=True)
def cleanup_table(db):
    yield
    import sqlalchemy

    engine = sqlalchemy.create_engine(DB_URL)
    with engine.begin() as conn:
        # Runs first: it FKs the session table
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.runs_table_name}"'))
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.session_table_name}"'))
    engine.dispose()


async def read_runs(db: AsyncPostgresDb, session_id: str):
    from sqlalchemy import select

    runs_table = await db._get_table(table_type="runs")
    async with db.async_session_factory() as sess:
        rows = (
            await sess.execute(
                select(runs_table.c.run_data)
                .where(runs_table.c.session_id == session_id)
                .order_by(runs_table.c.run_index)
            )
        ).fetchall()
        return [dict(r[0]) for r in rows]


async def worker_completes_run(db: AsyncPostgresDb, session_id: str, run_id: str) -> None:
    """Simulate the racing worker on the v3 substrate: session row plus a
    COMPLETED run in the runs table (claim + execute + terminal save, all
    inside the accepting request's read window)."""
    import time as _time

    table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(
                table.insert().values(
                    session_id=session_id,
                    session_type="agent",
                    agent_id="prep-agent",
                    created_at=int(_time.time()),
                )
            )
            await sess.execute(
                runs_table.insert().values(
                    run_id=run_id,
                    session_id=session_id,
                    run_type="agent",
                    agent_id="prep-agent",
                    status="COMPLETED",
                    run_index=0,
                    run_data={"run_id": run_id, "status": "COMPLETED", "content": "done"},
                    created_at=int(_time.time()),
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

        sync_db = PostgresDb(db_url=DB_URL, session_table=db.session_table_name, runs_table=db.runs_table_name)
        sid = f"s-{uuid.uuid4().hex[:8]}"
        session = AgentSession(session_id=sid, agent_id="a1", runs=[], created_at=int(time.time()))
        assert sync_db.insert_session_if_absent(session) is True
        assert sync_db.insert_session_if_absent(session) is False


class TestLegacyFallbackOrdersSessionBeforeRun:
    """Adapters WITHOUT the atomic primitives (hidden here via monkeypatch)
    take the legacy create-and-save path. On the FK-backed v3 runs table the
    run insert is rejected until its session row exists - and the per-run
    save helpers only LOG that failure, so the old run-first order left the
    202'd run unpollable while the response claimed acceptance."""

    def _hide_primitives(self, monkeypatch, db):
        monkeypatch.setattr(db, "append_run_to_session_if_absent", None)
        monkeypatch.setattr(db, "insert_session_if_absent", None)

    @pytest.mark.asyncio
    async def test_agent_fallback_lands_pending_run_row(self, db, monkeypatch):
        from agno.os.job_queue import aprepare_queued_run

        self._hide_primitives(monkeypatch, db)
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        run_id = f"r-{uuid.uuid4().hex[:8]}"
        agent = Agent(id="prep-agent", name="Prep Agent", db=db)

        await aprepare_queued_run(agent, "agent", run_id, session_id, None, "hello")

        runs = await read_runs(db, session_id)
        assert len(runs) == 1 and runs[0]["run_id"] == run_id, (
            "legacy fallback must save the session row BEFORE the run row - "
            "run-first FK-fails silently and the accepted run is unpollable"
        )
        assert str(runs[0]["status"]).upper() == "PENDING"

    @pytest.mark.asyncio
    async def test_team_fallback_lands_pending_run_row(self, db, monkeypatch):
        from agno.os.job_queue import aprepare_queued_run
        from agno.team import Team

        self._hide_primitives(monkeypatch, db)
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        run_id = f"r-{uuid.uuid4().hex[:8]}"
        team = Team(id="prep-team", name="Prep Team", members=[], db=db)

        await aprepare_queued_run(team, "team", run_id, session_id, None, "hello")

        runs = await read_runs(db, session_id)
        assert len(runs) == 1 and runs[0]["run_id"] == run_id
        assert str(runs[0]["status"]).upper() == "PENDING"

    @pytest.mark.asyncio
    async def test_workflow_fallback_lands_pending_run_row(self, db, monkeypatch):
        from agno.os.job_queue import aprepare_queued_run
        from agno.workflow import Workflow

        self._hide_primitives(monkeypatch, db)
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        run_id = f"r-{uuid.uuid4().hex[:8]}"
        workflow = Workflow(id="prep-wf", name="Prep Workflow", db=db, steps=[])

        await aprepare_queued_run(workflow, "workflow", run_id, session_id, None, "hello")

        runs = await read_runs(db, session_id)
        assert len(runs) == 1 and runs[0]["run_id"] == run_id
        assert str(runs[0]["status"]).upper() == "PENDING"
