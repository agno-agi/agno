"""The starved-loop lease regression against real Postgres.

Twin of tests/unit/os/test_heartbeat_thread.py's starvation case, on the
store the field reports came from: a run blocking the event loop past
lock_grace, a peer sweeper on its own connection, and the requirement that
the run completes instead of being falsely failed by its own dead
heartbeat. See the unit file for the full doctrine.
"""

import asyncio
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Any, List

import pytest

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.config import QueueConfig
from agno.run.base import RunStatus

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _port_open(port: int) -> bool:
    import socket

    try:
        with socket.create_connection(("localhost", port), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _port_open(5532), reason="Postgres not available on localhost:5532")


class BlockingAgent:
    def __init__(self, block_seconds: float):
        self.id = "agent-1"
        self.block_seconds = block_seconds

    async def arun(self, **kwargs: Any) -> SimpleNamespace:
        time.sleep(self.block_seconds)  # deliberately sync: starves the loop
        return SimpleNamespace(status=RunStatus.completed, content="done")


@pytest.fixture(autouse=True)
def _stub_run_row_persist(monkeypatch: pytest.MonkeyPatch):
    from agno.session import AgentSession

    async def fake_read(component, session_id=None, user_id=None):
        return AgentSession(session_id=session_id or "s1", runs=[])

    async def fake_save(component, session=None):
        pass

    async def fake_save_run(component, run=None, session_id=None, user_id=None, run_index=None):
        pass

    monkeypatch.setattr("agno.agent._storage.aread_or_create_session", fake_read)
    monkeypatch.setattr("agno.agent._session.asave_session", fake_save)
    monkeypatch.setattr("agno.agent._session.asave_run", fake_save_run)


@pytest.mark.asyncio
async def test_sync_blocked_run_completes_on_postgres():
    import sqlalchemy

    from agno.db.postgres import PostgresDb
    from agno.os.job_queue import QueueWorker, _SyncStoreAdapter

    job_table = f"hb_{uuid.uuid4().hex[:8]}"
    worker_db = PostgresDb(db_url=PG_URL, job_table=job_table)
    peer_db = PostgresDb(db_url=PG_URL, job_table=job_table)

    swept: List[str] = []
    stop_probe = threading.Event()

    def probe() -> None:
        while not stop_probe.wait(0.25):
            try:
                for job in peer_db.sweep_exhausted_jobs(lock_grace_seconds=3):
                    if peer_db.acquire_sweep(job["id"], "peer-sweeper", 3):
                        peer_db.settle_swept_job(job["id"], "peer-sweeper", "failed", "stale lease swept by peer")
                        swept.append(job["id"])
            except Exception:  # pragma: no cover - probe must never die silently
                pass

    store = _SyncStoreAdapter(worker_db)
    agent = BlockingAgent(block_seconds=6.0)
    config = QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=3, timeout_seconds=None)
    worker = QueueWorker(
        store=store,
        resolve_component=lambda ctype, cid: agent if (ctype, cid) == ("agent", "agent-1") else None,
        config=config,
        worker_id="live-worker",
        stop_timeout=2,
    )

    probe_thread = threading.Thread(target=probe, daemon=True)
    try:
        await store.enqueue_job(
            QueuedJob(
                id="r1",
                component_type="agent",
                component_id="agent-1",
                session_id="s1",
                payload={"input": "hello", "kwargs": {}},
                max_attempts=1,
            ).to_dict()
        )
        probe_thread.start()
        await worker.start()

        async def until_terminal() -> dict:
            while True:
                job = await store.get_job("r1")
                if job is not None and job["status"] in ("completed", "failed", "cancelled"):
                    return job
                await asyncio.sleep(0.05)

        job = await asyncio.wait_for(until_terminal(), timeout=25)
    finally:
        stop_probe.set()
        probe_thread.join(timeout=5)
        await worker.stop()
        engine = sqlalchemy.create_engine(PG_URL)
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {worker_db.db_schema}."{worker_db.job_table_name}"'))
        engine.dispose()

    assert swept == [], "the peer sweeper reclaimed a HEALTHY run - the lease went stale while the loop was blocked"
    assert job["status"] == "completed", f"the run finished but was reported {job['status']!r}"
