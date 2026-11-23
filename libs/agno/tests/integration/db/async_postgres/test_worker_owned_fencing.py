"""On real Postgres: the zombie-clobber the save fence exists to stop.

A worker declared dead (but still executing) writes its result AFTER a newer
attempt has claimed and completed the run. Before the fence, that write went
through bare ``upsert_run`` and overwrote the newer attempt's terminal row
wholesale. Now the save helpers route worker-owned runs through the
row-locked ``update_run_in_session`` with ``expected_attempt`` - the zombie
is typed STALE_ATTEMPT (or TERMINAL_REFUSED) and dropped.
"""

import time
import uuid

import pytest

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.concurrency import mark_worker_managed, unmark_worker_managed

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
    suffix = uuid.uuid4().hex[:8]
    return AsyncPostgresDb(db_url=DB_URL, session_table=f"test_wof_{suffix}", runs_table=f"test_wof_runs_{suffix}")


@pytest.fixture(autouse=True)
def cleanup(db):
    registered: list = []
    yield registered
    for rid in registered:
        unmark_worker_managed(rid)
    import sqlalchemy

    engine = sqlalchemy.create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.runs_table_name}"'))
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.session_table_name}"'))
    engine.dispose()


async def seed_completed_run(db, session_id: str, run_id: str, attempt: int) -> None:
    """The NEWER attempt's settled state: COMPLETED row stamped with its
    queue_attempt, exactly as the worker's up-front stamp + fenced terminal
    save leave it."""
    table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(
                table.insert().values(session_id=session_id, session_type="agent", created_at=int(time.time()))
            )
            await sess.execute(
                runs_table.insert().values(
                    run_id=run_id,
                    session_id=session_id,
                    run_type="agent",
                    status="COMPLETED",
                    run_index=0,
                    run_data={
                        "run_id": run_id,
                        "status": "COMPLETED",
                        "content": "the real output",
                        "queue_attempt": attempt,
                    },
                    created_at=int(time.time()),
                )
            )


async def read_run(db, run_id: str) -> dict:
    from sqlalchemy import select

    runs_table = await db._get_table(table_type="runs")
    async with db.async_session_factory() as sess:
        row = (await sess.execute(select(runs_table.c.run_data).where(runs_table.c.run_id == run_id))).fetchone()
    return dict(row[0]) if row else {}


class TestZombieSaveCannotClobber:
    @pytest.mark.asyncio
    async def test_stale_attempt_terminal_save_is_dropped(self, db, cleanup):
        """The canonical zombie: attempt 1 was swept, attempt 2 completed.
        Attempt 1's late ERROR save must bounce off the fence."""
        from agno.agent._session import asave_run

        session_id, run_id = f"s-{uuid.uuid4().hex[:8]}", f"r-{uuid.uuid4().hex[:8]}"
        await seed_completed_run(db, session_id, run_id, attempt=2)
        agent = Agent(id="fence-agent", name="Fence Agent", db=db)

        mark_worker_managed(run_id, worker_id="zombie", attempt=1)
        cleanup.append(run_id)
        zombie_result = RunOutput(
            run_id=run_id, session_id=session_id, status=RunStatus.error, content="zombie garbage"
        )
        await asave_run(agent, run=zombie_result, session_id=session_id)

        row = await read_run(db, run_id)
        assert row["status"] == "COMPLETED", (
            f"zombie attempt 1 clobbered the newer attempt's terminal row: {row['status']}"
        )
        assert row["content"] == "the real output"
        assert row["queue_attempt"] == 2

    @pytest.mark.asyncio
    async def test_stale_attempt_midrun_flush_is_dropped(self, db, cleanup):
        """Not just terminal saves: a zombie's mid-run RUNNING flush landing
        after the newer attempt completed must also be refused - bare
        upsert_run overwrites status unconditionally, so an unfenced flush
        is the same clobber as an unfenced terminal write."""
        from agno.agent._session import asave_run

        session_id, run_id = f"s-{uuid.uuid4().hex[:8]}", f"r-{uuid.uuid4().hex[:8]}"
        await seed_completed_run(db, session_id, run_id, attempt=2)
        agent = Agent(id="fence-agent", name="Fence Agent", db=db)

        mark_worker_managed(run_id, worker_id="zombie", attempt=1)
        cleanup.append(run_id)
        midrun = RunOutput(run_id=run_id, session_id=session_id, status=RunStatus.running, content="partial")
        await asave_run(agent, run=midrun, session_id=session_id)

        row = await read_run(db, run_id)
        assert row["status"] == "COMPLETED" and row["content"] == "the real output"

    @pytest.mark.asyncio
    async def test_live_attempt_save_applies(self, db, cleanup):
        """The fence must not block the CURRENT attempt: a newer attempt's
        own terminal save goes through and restamps the row."""
        from agno.agent._session import asave_run

        session_id, run_id = f"s-{uuid.uuid4().hex[:8]}", f"r-{uuid.uuid4().hex[:8]}"
        await seed_completed_run(db, session_id, run_id, attempt=2)
        agent = Agent(id="fence-agent", name="Fence Agent", db=db)

        mark_worker_managed(run_id, worker_id="live", attempt=3)
        cleanup.append(run_id)
        newer = RunOutput(run_id=run_id, session_id=session_id, status=RunStatus.completed, content="attempt 3 output")
        await asave_run(agent, run=newer, session_id=session_id)

        row = await read_run(db, run_id)
        assert row["content"] == "attempt 3 output"
        assert row["queue_attempt"] == 3

    @pytest.mark.asyncio
    async def test_owned_save_with_missing_row_creates_stamped_row(self, db, cleanup):
        """MISSING falls to the atomic append, which stamps queue_attempt so
        the very next fence compare is armed."""
        from agno.agent._session import asave_run
        from agno.session import AgentSession

        session_id, run_id = f"s-{uuid.uuid4().hex[:8]}", f"r-{uuid.uuid4().hex[:8]}"
        agent = Agent(id="fence-agent", name="Fence Agent", db=db)
        await db._get_table(table_type="runs", create_table_if_not_found=True)
        assert await db.insert_session_if_absent(
            AgentSession(session_id=session_id, agent_id="fence-agent", runs=[], created_at=int(time.time()))
        )

        mark_worker_managed(run_id, worker_id="w1", attempt=1)
        cleanup.append(run_id)
        result = RunOutput(run_id=run_id, session_id=session_id, status=RunStatus.completed, content="first landing")
        await asave_run(agent, run=result, session_id=session_id)

        row = await read_run(db, run_id)
        assert row.get("content") == "first landing"
        assert row.get("queue_attempt") == 1, "fresh row must carry the attempt stamp"
