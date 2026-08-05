"""Behavioral tests for the acceptance invariant.

After the queue ticket commits, every response must either ACKNOWLEDGE the
durable acceptance (202/tail) or first make the ticket permanently
non-executable. And a poll must never 404 a run whose accepted ticket exists
just because the run row has not landed yet.

These drive the REAL router endpoints via TestClient - no model calls; the
prepare is monkeypatched at the seam and the worker never runs.
"""

import time
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
def harness(tmp_path):
    agent = Agent(id="qa-agent", name="QA Agent", db=SqliteDb(db_file=str(tmp_path / "t.db")))
    app = AgentOS(agents=[agent], telemetry=False).get_app()
    store = InMemoryQueueStore()
    app.state.queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True))
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(app=app, store=store, client=client)


def seed_ticket(store: InMemoryQueueStore, run_id: str, **overrides) -> dict:
    """Insert a ticket directly (sync): the store's asyncio.Lock must only
    ever be awaited on the TestClient's request loop."""
    fields = dict(
        id=run_id,
        component_type="agent",
        component_id="qa-agent",
        session_id="s-tkt",
        payload={"input": "hi", "kwargs": {}},
    )
    fields.update(overrides)
    job = QueuedJob(**fields).to_dict()
    store._jobs[run_id] = job
    return job


class TestPrepareFailureTruthfulness:
    def test_prepare_failure_aborts_ticket_before_500(self, harness, monkeypatch):
        """A 500 is only allowed once the ticket cannot execute: the old
        behavior raised while the queued ticket stayed claimable, so the
        client retried a submission that was already going to run."""

        async def broken_prepare(component, component_type, run_id, session_id, user_id, input):
            raise RuntimeError("session store down")

        monkeypatch.setattr("agno.os.job_queue.aprepare_queued_run", broken_prepare)
        resp = harness.client.post(
            "/agents/qa-agent/runs", data={"message": "hi", "stream": "false", "background": "true"}
        )
        assert resp.status_code == 500
        assert len(harness.store._jobs) == 1
        job = next(iter(harness.store._jobs.values()))
        assert job["status"] == "cancelled", (
            f"a 500 response left the ticket {job['status']!r} - it must be made "
            "permanently non-executable before the failure is reported"
        )

    def test_prepare_failure_after_claim_acknowledges(self, harness, monkeypatch):
        """If a worker claimed the ticket before the prepare failure, the run
        IS executing (and the worker's claim-time ensure owns the row): the
        response must acknowledge with 202, not 500 a run that happens."""
        store = harness.store

        async def racing_prepare(component, component_type, run_id, session_id, user_id, input):
            claimed = await store.claim_job("fast-worker")
            assert claimed is not None and claimed["id"] == run_id
            raise RuntimeError("prepare lost the race to the worker")

        monkeypatch.setattr("agno.os.job_queue.aprepare_queued_run", racing_prepare)
        resp = harness.client.post(
            "/agents/qa-agent/runs", data={"message": "hi", "stream": "false", "background": "true"}
        )
        assert resp.status_code == 202, "the run executes on the worker - a 500 would be a lie"
        assert resp.json()["status"] == "PENDING"
        job = next(iter(store._jobs.values()))
        assert job["status"] == "running"


class TestTicketPollFallback:
    def test_poll_answers_from_ticket_when_row_missing(self, harness):
        """The window between ticket commit and run-row landing (or a dead
        router that never prepared): the poll must answer PENDING from the
        accepted ticket, never 404 a real run."""
        seed_ticket(harness.store, "r-poll-1")
        resp = harness.client.get("/agents/qa-agent/runs/r-poll-1", params={"session_id": "s-tkt"})
        assert resp.status_code == 200, "an accepted run must never poll as nonexistent"
        body = resp.json()
        assert body == {"run_id": "r-poll-1", "session_id": "s-tkt", "status": "PENDING"}

    def test_failed_ticket_reports_error_with_reason(self, harness):
        seed_ticket(harness.store, "r-poll-2", status="failed", error="worker lost")
        resp = harness.client.get("/agents/qa-agent/runs/r-poll-2", params={"session_id": "s-tkt"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ERROR" and body["content"] == "worker lost"

    def test_tenant_mismatch_stays_404(self, harness):
        """A guessable run_id must not leak another tenant's run existence:
        a ticket owned by a user is invisible to an unscoped caller."""
        seed_ticket(harness.store, "r-poll-3", user_id="alice")
        resp = harness.client.get("/agents/qa-agent/runs/r-poll-3", params={"session_id": "s-tkt"})
        assert resp.status_code == 404

    def test_session_mismatch_stays_404(self, harness):
        seed_ticket(harness.store, "r-poll-4")
        resp = harness.client.get("/agents/qa-agent/runs/r-poll-4", params={"session_id": "other-session"})
        assert resp.status_code == 404

    def test_foreign_component_ticket_stays_404(self, harness):
        seed_ticket(harness.store, "r-poll-5", component_type="team", component_id="some-team")
        resp = harness.client.get("/agents/qa-agent/runs/r-poll-5", params={"session_id": "s-tkt"})
        assert resp.status_code == 404

    def test_no_queue_worker_keeps_plain_404(self, harness):
        harness.app.state.queue_worker = None
        resp = harness.client.get("/agents/qa-agent/runs/r-nope", params={"session_id": "s-tkt"})
        assert resp.status_code == 404


class TestHelperUnits:
    """Direct unit coverage of aticket_poll_fallback's status mapping (the
    router tests above cover the wiring)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "ticket_status,expected",
        [
            ("queued", "PENDING"),
            ("running", "RUNNING"),
            ("paused", "PAUSED"),
            ("completed", "COMPLETED"),
            ("cancelled", "CANCELLED"),
        ],
    )
    async def test_status_mapping(self, ticket_status, expected):
        from agno.os.job_queue import aticket_poll_fallback

        store = InMemoryQueueStore()
        job = QueuedJob(
            id="r1",
            component_type="agent",
            component_id="a1",
            session_id="s1",
            payload={},
            status=ticket_status,
            completed_at=int(time.time()) if ticket_status in ("completed", "cancelled") else None,
        ).to_dict()
        store._jobs["r1"] = job
        worker = SimpleNamespace(store=store)
        view = await aticket_poll_fallback(worker, "r1", "s1", "agent", "a1", None)
        assert view is not None and view["status"] == expected

    @pytest.mark.asyncio
    async def test_scoped_user_sees_own_ticket(self):
        from agno.os.job_queue import aticket_poll_fallback

        store = InMemoryQueueStore()
        store._jobs["r1"] = QueuedJob(
            id="r1", component_type="agent", component_id="a1", session_id="s1", payload={}, user_id="alice"
        ).to_dict()
        worker = SimpleNamespace(store=store)
        assert await aticket_poll_fallback(worker, "r1", "s1", "agent", "a1", "alice") is not None
        assert await aticket_poll_fallback(worker, "r1", "s1", "agent", "a1", "bob") is None


class TestBackgroundContinueRequiresDurableDoor:
    """continue(background=true, stream=false) previously
    diverged three ways - 202 with a ticket, a silent INLINE-BLOCKING 200 on
    agents/teams without one, and a 409 on workflows. The silent inline run
    was the lie: the caller asked for background semantics and got a request
    that blocked for the whole continuation leg. Now all three components
    refuse identically without a ticket; the durable 202 body was already
    uniform (cbeb8e8)."""

    @pytest.fixture()
    def continue_harness(self, tmp_path):
        from fastapi.testclient import TestClient

        from agno.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.os import AgentOS
        from agno.team import Team

        db = SqliteDb(db_file=str(tmp_path / "t.db"))
        agent = Agent(id="qa-agent", name="QA Agent", db=db)
        team = Team(id="qa-team", name="QA Team", members=[], db=db)
        app = AgentOS(agents=[agent], teams=[team], telemetry=False).get_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_agent_background_continue_without_ticket_409s(self, continue_harness):
        resp = continue_harness.post(
            "/agents/qa-agent/runs/r-nope/continue",
            data={"background": "true", "stream": "false", "session_id": "s1"},
        )
        assert resp.status_code == 409, (
            f"got {resp.status_code} - the old fallthrough ran the continuation inline while "
            "claiming background semantics"
        )
        assert "durably-submitted" in resp.json()["detail"]

    def test_team_background_continue_without_ticket_409s(self, continue_harness):
        resp = continue_harness.post(
            "/teams/qa-team/runs/r-nope/continue",
            data={"background": "true", "stream": "false", "session_id": "s1"},
        )
        assert resp.status_code == 409
        assert "durably-submitted" in resp.json()["detail"]

    def test_inline_continue_without_background_is_not_refused(self, continue_harness):
        """background=false continues keep the inline path: whatever the
        inline machinery does with this run, the durable-door refusal must
        not fire - it is scoped strictly to the background flag."""
        resp = continue_harness.post(
            "/agents/qa-agent/runs/r-nope/continue",
            data={"background": "false", "stream": "false", "session_id": "s1"},
        )
        assert resp.status_code != 409, f"the 409 must key on background=true only: {resp.json()}"
