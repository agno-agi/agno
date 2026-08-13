"""The requeue zombie gate.

A job FAILED within the last lock_grace was, in the worst case, swept while
its worker was actually alive (a sweep proves lost heartbeats, not stopped
execution). Requeueing inside that window can put a second live producer on
the same run row and event stream - unfenced until the P1 program's items
4/5 land. The endpoint refuses with 409 until the grace elapses, unless the
operator explicitly forces. Cancelled jobs skip the gate: cancellation only
tombstones waiting tickets, so no zombie attempt can exist.
"""

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.routers.job_queue import get_queue_router


@pytest.fixture()
def harness():
    app = FastAPI()
    app.include_router(get_queue_router(SimpleNamespace()))
    store = InMemoryQueueStore()
    app.state.queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True, lock_grace_seconds=60))
    return SimpleNamespace(store=store, client=TestClient(app, raise_server_exceptions=False))


def seed_terminal(store, job_id, status, completed_at):
    job = QueuedJob(
        id=job_id,
        component_type="agent",
        component_id="a1",
        session_id="s1",
        payload={"input": "hi"},
        status=status,
        attempt=1,
        completed_at=completed_at,
    ).to_dict()
    store._jobs[job_id] = job


class TestRequeueZombieGate:
    def test_recently_failed_refused_without_force(self, harness):
        seed_terminal(harness.store, "j1", "failed", int(time.time()))
        resp = harness.client.post("/queue/jobs/j1/requeue")
        assert resp.status_code == 409, (
            f"a job failed inside the lock grace may still be executing - got {resp.status_code}"
        )
        assert "force=true" in resp.json()["detail"]
        assert harness.store._jobs["j1"]["status"] == "failed", "the refusal must not mutate the ticket"

    def test_recently_failed_forced_through(self, harness):
        seed_terminal(harness.store, "j2", "failed", int(time.time()))
        resp = harness.client.post("/queue/jobs/j2/requeue", params={"force": "true"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        assert resp.json()["max_attempts"] == 2, "requeue grants exactly one more execution"

    def test_failed_outside_grace_requeues_without_force(self, harness):
        seed_terminal(harness.store, "j3", "failed", int(time.time()) - 120)
        resp = harness.client.post("/queue/jobs/j3/requeue")
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_recently_cancelled_skips_the_gate(self, harness):
        """No zombie can exist behind a cancelled ticket - only waiting
        states are tombstoned - so the gate must not tax that path."""
        seed_terminal(harness.store, "j4", "cancelled", int(time.time()))
        resp = harness.client.post("/queue/jobs/j4/requeue")
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"


class TestNoWorkerAnswers503:
    """One operational condition, one status: with no active queue worker,
    every /queue endpoint answers 503 (service availability) - the old
    _get_store 404 made the same state a missing resource on read
    endpoints while the requeue path already said 503."""

    def test_queue_endpoints_answer_503_without_worker(self):
        app = FastAPI()
        app.include_router(get_queue_router(SimpleNamespace()))
        client = TestClient(app, raise_server_exceptions=False)

        for path in ("/queue/jobs", "/queue/jobs/some-id", "/queue/stats"):
            resp = client.get(path)
            assert resp.status_code == 503, f"{path}: expected 503, got {resp.status_code}"
            assert "not enabled" in resp.json()["detail"]
