"""Behavioral tests for Idempotency-Key component scoping.

The dedup namespace is (idempotency_key, user_id): the queue stores cannot
tell an agent submission from a workflow submission reusing the same key.
The router duplicate branches must therefore verify that the original ticket
belongs to the component the duplicate was submitted against - otherwise a
key reused across components answers with the OTHER component's run (a 202
or stream attach whose ids then 404 through this route's poll endpoint,
because the ticket poll fallback does enforce component identity).

These drive the REAL router endpoints via TestClient - no model calls; the
original ticket is seeded directly in the store and the worker never runs.
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
from agno.team import Team


@pytest.fixture()
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Agent(id="qa-agent", name="QA Agent", db=db)
    team = Team(id="qa-team", name="QA Team", members=[agent], db=db)
    app = AgentOS(agents=[agent], teams=[team], telemetry=False).get_app()
    store = InMemoryQueueStore()
    app.state.queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True))
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(app=app, store=store, client=client)


def seed_agent_ticket(store: InMemoryQueueStore, run_id: str, **overrides) -> dict:
    """Insert a ticket directly (sync): the store's asyncio.Lock must only
    ever be awaited on the TestClient's request loop."""
    fields = dict(
        id=run_id,
        component_type="agent",
        component_id="qa-agent",
        session_id="s-tkt",
        payload={"input": "hi", "kwargs": {}},
        idempotency_key="shared-key",
    )
    fields.update(overrides)
    job = QueuedJob(**fields).to_dict()
    store._jobs[run_id] = job
    return job


class TestCrossComponentReuseRefused:
    def test_non_stream_duplicate_of_other_component_is_409(self, harness):
        """A key first used on an agent submit, replayed against the team
        route, must refuse - not 202 with the agent run's ids (which would
        then 404 through the team poll endpoint)."""
        seed_agent_ticket(harness.store, "run-agent-1")

        resp = harness.client.post(
            "/teams/qa-team/runs",
            data={"message": "hi", "stream": "false", "background": "true"},
            headers={"Idempotency-Key": "shared-key"},
        )

        assert resp.status_code == 409, (
            f"cross-component Idempotency-Key reuse answered {resp.status_code} "
            f"{resp.json() if resp.status_code == 202 else resp.text!r} - it must refuse"
        )
        assert "different component" in resp.json()["detail"]
        # The refusal must not leak the original ticket's identity on the wire:
        # the key namespace is shared across clients in unauthenticated deployments.
        assert "qa-agent" not in resp.json()["detail"]
        # And it must not have enqueued anything new.
        assert list(harness.store._jobs) == ["run-agent-1"]

    def test_stream_duplicate_of_other_component_is_409_before_shape_checks(self, harness):
        """The component check must come before the stream-shape check: a
        non-streaming agent ticket replayed on the team STREAM seam must say
        'different component', not 'non-streaming submission' (which would
        point the caller at polling a run their route cannot see)."""
        seed_agent_ticket(harness.store, "run-agent-2")

        resp = harness.client.post(
            "/teams/qa-team/runs",
            data={"message": "hi", "stream": "true", "background": "true"},
            headers={"Idempotency-Key": "shared-key"},
        )

        assert resp.status_code == 409
        assert "different component" in resp.json()["detail"]


class TestSameComponentReuseStillDedups:
    def test_same_component_duplicate_answers_original_ticket(self, harness):
        """The guard must not break legitimate dedup: replaying the key on
        the SAME component keeps returning the original run's ids."""
        seed_agent_ticket(harness.store, "run-agent-3")

        resp = harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": "hi", "stream": "false", "background": "true"},
            headers={"Idempotency-Key": "shared-key"},
        )

        assert resp.status_code == 202
        assert resp.json()["run_id"] == "run-agent-3"
        assert list(harness.store._jobs) == ["run-agent-3"]
