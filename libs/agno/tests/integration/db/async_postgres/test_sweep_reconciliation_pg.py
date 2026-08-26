"""The reconciling sweep's headline case against real Postgres: crash between
the run row's COMPLETED commit and the ticket settle. The old sweep answered
row=COMPLETED / ticket=failed (and an ERROR stream); the reconciling sweep
finishes the lost bookkeeping instead - through the REAL fenced primitive
and the REAL jobs table."""

import time
import uuid

import pytest

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.job_queue.config import QueueConfig
from agno.os.job_queue import QueueWorker

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
    return AsyncPostgresDb(
        db_url=DB_URL,
        session_table=f"test_swr_{suffix}",
        runs_table=f"test_swr_runs_{suffix}",
        job_table=f"test_swr_jobs_{suffix}",
    )


@pytest.fixture(autouse=True)
def cleanup(db):
    yield
    import sqlalchemy

    engine = sqlalchemy.create_engine(DB_URL)
    with engine.begin() as conn:
        for table in (db.runs_table_name, db.session_table_name, db.job_table_name):
            conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{table}"'))
    engine.dispose()


@pytest.mark.asyncio
async def test_completed_row_reconciles_ticket_on_real_postgres(db):
    from sqlalchemy import select, update

    session_id, run_id = f"s-{uuid.uuid4().hex[:8]}", f"r-{uuid.uuid4().hex[:8]}"
    agent = Agent(id="swr-agent", name="Sweep Agent", db=db)

    # The settled state the crashed worker left: session + COMPLETED run row
    # stamped with its attempt - written through the REAL upsert path so the
    # row carries the full shape session hydration deserializes
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus

    sessions_table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
    await db._get_table(table_type="runs", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(
                sessions_table.insert().values(
                    session_id=session_id, session_type="agent", agent_id="swr-agent", created_at=int(time.time())
                )
            )
    completed = RunOutput(
        run_id=run_id,
        session_id=session_id,
        agent_id="swr-agent",
        status=RunStatus.completed,
        content="the real output",
    )
    run_dict = completed.to_dict()
    run_dict["queue_attempt"] = 1
    await db.upsert_run(run=run_dict, session_id=session_id, run_index=0)
    runs_table = await db._get_table(table_type="runs")

    # The ticket the crash left behind: claimed, stale, never settled
    now = int(time.time())
    ticket = {
        "id": run_id,
        "job_type": "run",
        "status": "queued",
        "component_type": "agent",
        "component_id": "swr-agent",
        "session_id": session_id,
        "user_id": None,
        "payload": {"input": "hi", "stream": False},
        "attempt": 0,
        "max_attempts": 1,
        "available_at": now,
        "created_at": now,
        "updated_at": now,
        "idempotency_key": None,
        "deployment_id": None,
    }
    assert (await db.enqueue_job(ticket))["accepted"]
    claimed = await db.claim_job("dead-worker", 3)
    assert claimed is not None and claimed["attempt"] == 1
    jobs_table = await db._get_table(table_type="jobs")
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(update(jobs_table).where(jobs_table.c.id == run_id).values(locked_at=now - 1000))

    worker = QueueWorker(
        store=db,
        resolve_component=lambda t, i: agent,
        config=QueueConfig(durable=True, lock_grace_seconds=3),
        worker_id="sweeper",
        stop_timeout=0.2,
    )
    await worker._sweep_exhausted()

    # Row untouched, ticket reconciled to match
    async with db.async_session_factory() as sess:
        row = (await sess.execute(select(runs_table.c.run_data).where(runs_table.c.run_id == run_id))).fetchone()
    assert row[0]["status"] == "COMPLETED" and row[0]["content"] == "the real output"
    job = await db.get_job(run_id)
    assert job["status"] == "completed", (
        f"the sweep must finish the lost ticket settle, not contradict the row: {job['status']}"
    )
