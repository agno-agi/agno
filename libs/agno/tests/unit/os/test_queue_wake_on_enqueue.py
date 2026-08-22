"""The accept seams wake the local worker after a ticket commits - and only
then. Drives the REAL agent router via TestClient with a worker double that
records wakes; the prepare is monkeypatched at the seam and nothing runs.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.schemas.jobs import QueuedJob
from agno.db.sqlite import SqliteDb
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os import AgentOS


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    async def ok_prepare(component, component_type, run_id, session_id, user_id, input):
        return None

    monkeypatch.setattr("agno.os.job_queue.aprepare_queued_run", ok_prepare)
    agent = Agent(id="wake-agent", name="Wake Agent", db=SqliteDb(db_file=str(tmp_path / "t.db")))
    app = AgentOS(agents=[agent], telemetry=False).get_app()
    store = InMemoryQueueStore()
    wakes: list = []
    app.state.queue_worker = SimpleNamespace(
        store=store, config=QueueConfig(durable=True, max_queue_depth=1), wake=lambda: wakes.append(1)
    )
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(app=app, store=store, client=client, wakes=wakes)


def _submit(harness):
    return harness.client.post(
        "/agents/wake-agent/runs", data={"message": "hi", "stream": "false", "background": "true"}
    )


class TestSeamWakes:
    def test_accepted_submission_wakes_once(self, harness):
        resp = _submit(harness)
        assert resp.status_code == 202, resp.text
        assert harness.wakes == [1]

    def test_rejected_submission_does_not_wake(self, harness):
        """A 429 enqueued nothing, so there is nothing to claim: no wake."""
        harness.store._jobs["occupied"] = QueuedJob(
            id="occupied", component_type="agent", component_id="wake-agent", session_id="s-x"
        ).to_dict()
        resp = _submit(harness)
        assert resp.status_code == 429, resp.text
        assert harness.wakes == []

    def test_worker_double_without_wake_is_fine(self, harness):
        """Older doubles / foreign workers without wake(): the seam must not
        care - the helper is duck-typed."""
        harness.app.state.queue_worker = SimpleNamespace(store=harness.store, config=QueueConfig(durable=True))
        resp = _submit(harness)
        assert resp.status_code == 202, resp.text
