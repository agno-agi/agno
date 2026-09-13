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

    def test_unscoped_poll_sees_user_owned_ticket(self, harness):
        """No user-scope middleware means get_scoped_user_id is None: NO
        filtering, exactly like the session read. A user-owned ticket must
        answer the poll - treating the None as an anonymous owner value
        404ed accepted user-owned runs for every admin/unscoped poll inside
        the ticket-before-run-row window. (Tenant isolation between SCOPED
        principals is pinned at the helper level: a scoped caller with a
        different user_id stays 404.)"""
        seed_ticket(harness.store, "r-poll-3", user_id="alice")
        resp = harness.client.get("/agents/qa-agent/runs/r-poll-3", params={"session_id": "s-tkt"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "PENDING"

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


class TestDurabilityBypassIsLoud:
    """A worker is present, the client gets its 202/stream - but the run is
    executing on the accepting replica, not the durable queue. EVERY bypass
    reason must warn: the payload/media reasons always did, while
    factory-backed / off-registry / version-pinned submissions dropped to
    the non-durable path with no log line at all."""

    @pytest.fixture()
    def factory_harness(self, tmp_path):
        from agno.agent.factory import AgentFactory

        db = SqliteDb(db_file=str(tmp_path / "f.db"))
        produced = Agent(id="fx-agent", name="Produced Agent", db=db)
        factory = AgentFactory(id="fx-agent", db=db, factory=lambda ctx: produced)
        app = AgentOS(agents=[factory], telemetry=False).get_app()
        store = InMemoryQueueStore()
        app.state.queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True))
        client = TestClient(app, raise_server_exceptions=False)
        return SimpleNamespace(app=app, store=store, client=client)

    def test_factory_backed_submission_warns(self, factory_harness, caplog):
        with caplog.at_level("WARNING"):
            factory_harness.client.post(
                "/agents/fx-agent/runs", data={"message": "hi", "stream": "false", "background": "true"}
            )
        assert any("bypasses the durable queue" in r.message for r in caplog.records), (
            "a factory-backed background submission silently lost durability - it must warn"
        )
        assert len(factory_harness.store._jobs) == 0, "the bypass must not have enqueued anything"

    def test_durable_path_does_not_warn(self, harness, monkeypatch):
        """No false alarms: a queueable registry submission rides the queue
        and must NOT log the bypass warning."""

        async def ok_prepare(component, component_type, run_id, session_id, user_id, input):
            return None

        monkeypatch.setattr("agno.os.job_queue.aprepare_queued_run", ok_prepare)
        import logging

        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record)  # type: ignore[method-assign]
        logging.getLogger().addHandler(handler)
        try:
            resp = harness.client.post(
                "/agents/qa-agent/runs", data={"message": "hi", "stream": "false", "background": "true"}
            )
        finally:
            logging.getLogger().removeHandler(handler)
        assert resp.status_code == 202
        assert not any("bypasses the durable queue" in str(r.getMessage()) for r in records)


class TestDuplicate202Vocabulary:
    """The duplicate-202 body speaks the SAME status vocabulary as the run
    poll: no invented "FAILED" (the API's error value is "ERROR"), and a
    currently-RUNNING original answers RUNNING, not PENDING - a client
    switch on status must never see a value the run endpoints cannot also
    produce."""

    def _duplicate(self, harness):
        return harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": "hi", "stream": "false", "background": "true"},
            headers={"Idempotency-Key": "dup-key"},
        )

    def test_failed_original_answers_error_not_failed(self, harness):
        seed_ticket(harness.store, "r-dup-1", status="failed", idempotency_key="dup-key")
        resp = self._duplicate(harness)
        assert resp.status_code == 202
        assert resp.json()["status"] == "ERROR", (
            f"poll vocabulary is ERROR; got {resp.json()['status']!r} (FAILED exists nowhere else in the API)"
        )

    def test_running_original_answers_running_not_pending(self, harness):
        seed_ticket(harness.store, "r-dup-2", status="running", idempotency_key="dup-key")
        resp = self._duplicate(harness)
        assert resp.status_code == 202
        assert resp.json()["status"] == "RUNNING", (
            "a poll of the same run says RUNNING; the duplicate must not flatten it to PENDING"
        )

    def test_queued_original_still_answers_pending(self, harness):
        seed_ticket(harness.store, "r-dup-3", status="queued", idempotency_key="dup-key")
        resp = self._duplicate(harness)
        assert resp.status_code == 202
        assert resp.json()["status"] == "PENDING"


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
        view = await aticket_poll_fallback(worker, "r1", "s1", "agent", "a1", None, user_scoped=False)
        assert view is not None and view["status"] == expected

    @pytest.mark.asyncio
    async def test_scoped_user_sees_own_ticket(self):
        from agno.os.job_queue import aticket_poll_fallback

        store = InMemoryQueueStore()
        store._jobs["r1"] = QueuedJob(
            id="r1", component_type="agent", component_id="a1", session_id="s1", payload={}, user_id="alice"
        ).to_dict()
        worker = SimpleNamespace(store=store)
        assert await aticket_poll_fallback(worker, "r1", "s1", "agent", "a1", "alice", user_scoped=True) is not None
        assert await aticket_poll_fallback(worker, "r1", "s1", "agent", "a1", "bob", user_scoped=True) is None

    @pytest.mark.asyncio
    async def test_unscoped_mode_sees_user_owned_ticket(self):
        """get_scoped_user_id returns None for admins and unscoped
        deployments - NO filtering, exactly like the session read this
        fallback mirrors. Treating that None as an anonymous owner value
        404ed accepted user-owned runs for every admin poll inside the
        ticket-before-run-row window."""
        from agno.os.job_queue import aticket_poll_fallback

        store = InMemoryQueueStore()
        store._jobs["r1"] = QueuedJob(
            id="r1", component_type="agent", component_id="a1", session_id="s1", payload={}, user_id="alice"
        ).to_dict()
        worker = SimpleNamespace(store=store)
        view = await aticket_poll_fallback(worker, "r1", "s1", "agent", "a1", None, user_scoped=False)
        assert view is not None and view["status"] == "PENDING"


class TestBackgroundContinueCompatFallthrough:
    """continue(background=true, stream=false) without a durable ticket.

    Agents and teams keep their PRE-QUEUE behavior for back-compat: the
    background form param predates the durable queue on those endpoints and
    its non-stream branch always ran the continuation INLINE-BLOCKING, so
    existing clients depend on it. The fallthrough now logs a loud warning
    pointing at QueueConfig(durable=True) - real background continuation is
    the durable door. Workflows differ deliberately: their continue endpoint
    never had the param, so the durable door is its only contract and it
    refuses with 409 instead."""

    @pytest.fixture()
    def continue_harness(self, tmp_path):
        from fastapi.testclient import TestClient

        from agno.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.os import AgentOS
        from agno.team import Team
        from agno.workflow import Workflow

        db = SqliteDb(db_file=str(tmp_path / "t.db"))
        agent = Agent(id="qa-agent", name="QA Agent", db=db)
        team = Team(id="qa-team", name="QA Team", members=[], db=db)
        workflow = Workflow(id="qa-wf", name="QA Workflow", db=db, steps=[])
        app = AgentOS(agents=[agent], teams=[team], workflows=[workflow], telemetry=False).get_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_agent_background_continue_without_ticket_runs_inline(self, continue_harness, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="agno"):
            resp = continue_harness.post(
                "/agents/qa-agent/runs/r-nope/continue",
                data={"background": "true", "stream": "false", "session_id": "s1"},
            )
        assert resp.status_code != 409, (
            f"got 409 - the legacy inline fallthrough must survive for back-compat: {resp.json()}"
        )
        assert any("INLINE-BLOCKING" in r.message for r in caplog.records), (
            "the compat fallthrough must warn that background semantics are not real here"
        )

    def test_team_background_continue_without_ticket_runs_inline(self, continue_harness, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="agno"):
            resp = continue_harness.post(
                "/teams/qa-team/runs/r-nope/continue",
                data={"background": "true", "stream": "false", "session_id": "s1"},
            )
        assert resp.status_code != 409
        assert any("INLINE-BLOCKING" in r.message for r in caplog.records)

    def test_workflow_background_continue_without_ticket_409s(self, continue_harness, tmp_path):
        """The workflow continue endpoint gained the background param WITH
        the durable queue - there is no legacy client to protect, so the
        honest refusal stands. A real PAUSED run is seeded (the endpoint
        404s nonexistent runs before the gate)."""
        import json as _json
        import time as _time

        from agno.db.sqlite import SqliteDb

        seed_db = SqliteDb(db_file=str(tmp_path / "t.db"))
        sessions_table = seed_db._get_table(table_type="sessions", create_table_if_not_found=True)
        runs_table = seed_db._get_table(table_type="runs", create_table_if_not_found=True)
        with seed_db.Session() as sess, sess.begin():
            sess.execute(
                sessions_table.insert().values(session_id="s1", session_type="workflow", created_at=int(_time.time()))
            )
            sess.execute(
                runs_table.insert().values(
                    run_id="r-paused",
                    session_id="s1",
                    run_type="workflow",
                    workflow_id="qa-wf",
                    status="PAUSED",
                    run_index=0,
                    run_data=_json.dumps(
                        {"run_id": "r-paused", "session_id": "s1", "workflow_id": "qa-wf", "status": "PAUSED"}
                    ),
                    created_at=int(_time.time()),
                )
            )

        resp = continue_harness.post(
            "/workflows/qa-wf/runs/r-paused/continue",
            data={"background": "true", "stream": "false", "session_id": "s1"},
        )
        assert resp.status_code == 409, f"got {resp.status_code}: {resp.json()}"
        assert "durably-submitted" in resp.json()["detail"]

    def test_inline_continue_without_background_is_not_refused(self, continue_harness):
        """background=false continues keep the inline path untouched - no
        warning, no refusal keyed on the durable door."""
        resp = continue_harness.post(
            "/agents/qa-agent/runs/r-nope/continue",
            data={"background": "false", "stream": "false", "session_id": "s1"},
        )
        assert resp.status_code != 409, f"nothing here should 409: {resp.json()}"


class TestSubmitBackgroundBodyParity:
    """background=true + stream=false submits answer with the SAME body shape
    whether or not the durable queue is wired: 202 and exactly
    {run_id, session_id, status}. The durable seam's body is pinned by
    TestPrepareFailureTruthfulness/TestTicketPollFallback above; this pins
    the NON-durable detached path for all three components, so a client
    written against one deployment mode works unchanged on the other."""

    @pytest.fixture()
    def submit_harness(self, tmp_path):
        from fastapi.testclient import TestClient

        from agno.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.os import AgentOS
        from agno.team import Team
        from agno.workflow import Workflow

        db = SqliteDb(db_file=str(tmp_path / "t.db"))
        agent = Agent(id="qa-agent", name="QA Agent", db=db)
        team = Team(id="qa-team", name="QA Team", members=[], db=db)
        workflow = Workflow(id="qa-wf", name="QA Workflow", db=db, steps=[])
        app = AgentOS(agents=[agent], teams=[team], workflows=[workflow], telemetry=False).get_app()
        return TestClient(app, raise_server_exceptions=False)

    @pytest.mark.parametrize("path", ["/agents/qa-agent/runs", "/teams/qa-team/runs", "/workflows/qa-wf/runs"])
    def test_non_durable_body_matches_durable_contract(self, submit_harness, path):
        resp = submit_harness.post(path, data={"message": "hi", "stream": "false", "background": "true"})
        assert resp.status_code == 202, f"{path}: {resp.status_code} {resp.text[:200]}"
        body = resp.json()
        assert set(body.keys()) == {"run_id", "session_id", "status"}, (
            f"{path}: the non-durable 202 body must match the durable seam's shape exactly, got {body}"
        )
        assert body["status"] in ("PENDING", "RUNNING")


class TestServerErrorsDoNotEchoInternals:
    """N17: seam store failures and unhandled server errors surfaced as raw
    500s whose detail embedded str(exc) - store/driver text carries
    connection strings, SQL fragments, and hostnames. The wire gets the
    exception type; the full detail stays in the server log."""

    SECRET = "postgresql://ai:supersecret@db.internal:5532/ai"

    def test_prepare_failure_500_names_the_type_not_the_driver_text(self, harness, monkeypatch):
        async def broken_prepare(component, component_type, run_id, session_id, user_id, input):
            raise RuntimeError(f"connection refused at {TestServerErrorsDoNotEchoInternals.SECRET}")

        monkeypatch.setattr("agno.os.job_queue.aprepare_queued_run", broken_prepare)
        resp = harness.client.post(
            "/agents/qa-agent/runs", data={"message": "hi", "stream": "false", "background": "true"}
        )
        assert resp.status_code == 500
        assert self.SECRET not in resp.text, "the 500 detail must not echo driver internals"
        assert "RuntimeError" in resp.json()["detail"], "the type name is the client-safe breadcrumb"

    def test_unhandled_exception_500_names_the_type_not_the_message(self, harness, monkeypatch):
        from agno.agent import Agent

        async def broken_arun(self, **kwargs):
            raise RuntimeError(f"cannot reach {TestServerErrorsDoNotEchoInternals.SECRET}")

        monkeypatch.setattr(Agent, "arun", broken_arun)
        resp = harness.client.post(
            "/agents/qa-agent/runs", data={"message": "hi", "stream": "false", "background": "false"}
        )
        assert resp.status_code == 500
        assert self.SECRET not in resp.text, "the app-level handler must not echo str(exc) on 5xx"
        assert "RuntimeError" in resp.json()["detail"]
