"""Behavioral tests for Idempotency-Key component scoping.

The dedup namespace is (idempotency_key, user_id): the queue stores cannot
tell an agent submission from a workflow submission reusing the same key.
The router duplicate branches must therefore verify that the duplicate is a
retry of the original submission: same component, input, options and session.
Otherwise a reused key answers with a run the client did not ask for.

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
from agno.workflow import Workflow


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    async def ok_prepare(component, component_type, run_id, session_id, user_id, input):
        return None

    monkeypatch.setattr("agno.os.job_queue.aprepare_queued_run", ok_prepare)
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Agent(id="qa-agent", name="QA Agent", db=db)
    team = Team(id="qa-team", name="QA Team", members=[agent], db=db)
    workflow = Workflow(id="qa-workflow", name="QA Workflow", steps=[agent], db=db)
    app = AgentOS(agents=[agent], teams=[team], workflows=[workflow], telemetry=False).get_app()
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
    def test_non_stream_duplicate_of_other_component_is_422(self, harness):
        """A key first used on an agent submit, replayed against the team
        route, must refuse - not 202 with the agent run's ids (which would
        then 404 through the team poll endpoint)."""
        seed_agent_ticket(harness.store, "run-agent-1")

        resp = harness.client.post(
            "/teams/qa-team/runs",
            data={"message": "hi", "stream": "false", "background": "true"},
            headers={"Idempotency-Key": "shared-key"},
        )

        assert resp.status_code == 422, (
            f"cross-component Idempotency-Key reuse answered {resp.status_code} "
            f"{resp.json() if resp.status_code == 202 else resp.text!r} - it must refuse"
        )
        assert "different component" in resp.json()["detail"]
        # The refusal must not leak the original ticket's identity on the wire:
        # the key namespace is shared across clients in unauthenticated deployments.
        assert "qa-agent" not in resp.json()["detail"]
        # And it must not have enqueued anything new.
        assert list(harness.store._jobs) == ["run-agent-1"]

    def test_stream_duplicate_of_other_component_is_422_before_shape_checks(self, harness):
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

        assert resp.status_code == 422
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


ROUTES = [
    ("agent", "/agents/qa-agent/runs"),
    ("team", "/teams/qa-team/runs"),
    ("workflow", "/workflows/qa-workflow/runs"),
]


def seed_ticket(store: InMemoryQueueStore, component_type: str, stream: bool) -> dict:
    payload: dict = {"input": "hi", "kwargs": {}, "session_seq": 1}
    if stream:
        payload["stream"] = True
    return seed_agent_ticket(
        store,
        "run-original",
        component_type=component_type,
        component_id=f"qa-{component_type}",
        payload=payload,
    )


def submit(harness, path: str, stream: bool = False, **fields):
    data = {"message": "hi", "session_id": "s-tkt", "stream": str(stream).lower(), "background": "true", **fields}
    return harness.client.post(path, data=data, headers={"Idempotency-Key": "shared-key"})


class TestReuseWithDifferentRequestRefused:
    @pytest.mark.parametrize("component_type,path", ROUTES)
    def test_identical_retry_answers_original_run(self, harness, component_type, path):
        """Fields the store stamps on its copy (session_seq) must not fail an identical retry."""
        seed_ticket(harness.store, component_type, stream=False)

        resp = submit(harness, path)

        assert resp.status_code == 202, resp.text
        assert resp.json()["run_id"] == "run-original"
        assert list(harness.store._jobs) == ["run-original"]

    def test_retry_that_omits_session_answers_original_run(self, harness):
        """The door generates a session for a submission that names none, so
        the generated id is not part of the comparison."""
        seed_ticket(harness.store, "agent", stream=False)

        resp = harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": "hi", "stream": "false", "background": "true"},
            headers={"Idempotency-Key": "shared-key"},
        )

        assert resp.status_code == 202, resp.text
        assert resp.json()["run_id"] == "run-original"

    @pytest.mark.parametrize("stream", [False, True])
    @pytest.mark.parametrize("component_type,path", ROUTES)
    @pytest.mark.parametrize(
        "change",
        [{"message": "bye"}, {"metadata": '{"tag": "other"}'}, {"session_id": "s-other"}],
        ids=["message", "options", "session"],
    )
    def test_changed_request_is_422(self, harness, component_type, path, stream, change):
        seed_ticket(harness.store, component_type, stream=stream)

        resp = submit(harness, path, stream=stream, **change)

        assert resp.status_code == 422, resp.text
        assert "different request" in resp.json()["detail"]
        assert "run-original" not in resp.text
        assert list(harness.store._jobs) == ["run-original"]

    def test_different_user_is_an_independent_run(self, harness):
        seed_ticket(harness.store, "agent", stream=False)

        resp = submit(harness, "/agents/qa-agent/runs", message="bye", user_id="bob")

        assert resp.status_code == 202, resp.text
        assert resp.json()["run_id"] != "run-original"
        assert len(harness.store._jobs) == 2
