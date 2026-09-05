"""Durable queue for db-backed components.

Components created through the components API (and version-pinned loads)
live in the AgentOS db, not the code registry. With QueueConfig(durable=True)
their background submissions must ride the durable queue exactly like
registry components: the accepting endpoint stamps the resolution scope
(owner user_id + pinned version) on the ticket, and the worker replays the
db load under that scope at claim time.
"""

import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os import AgentOS
from agno.os.job_queue import (
    QueueWorker,
    component_is_queueable,
    ensure_duplicate_matches_component,
    get_active_queue_worker,
    queue_lifespan,
    queue_scope,
    resolve_queue_scope,
    warn_unfenced_session_stores,
)

BYPASS = "bypasses the durable queue"


def _create_db_agent(db: SqliteDb, component_id: str, stage: str = "published", user_id=None) -> None:
    db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType.AGENT,
        name=component_id,
        config={"name": component_id, "instructions": "hi"},
        stage=stage,
        user_id=user_id,
    )


@pytest.fixture()
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "components.db"))


@pytest.fixture()
def harness(db, monkeypatch):
    """A real AgentOS with NO code-registered agents: everything resolves
    from the db. The worker never runs; the prepare seam is a no-op."""
    _create_db_agent(db, "db-agent")

    async def ok_prepare(component, component_type, run_id, session_id, user_id, input):
        return None

    monkeypatch.setattr("agno.os.job_queue.aprepare_queued_run", ok_prepare)
    app = AgentOS(agents=[], db=db, telemetry=False).get_app()
    store = InMemoryQueueStore()
    app.state.queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True))
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(app=app, store=store, client=client, db=db)


def _capture_root_logs(records):
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record)  # type: ignore[method-assign]
    logging.getLogger().addHandler(handler)
    return handler


class TestDbComponentSubmissionsRideTheQueue:
    def test_background_submission_enqueues_with_scope(self, harness):
        records: list = []
        handler = _capture_root_logs(records)
        try:
            resp = harness.client.post(
                "/agents/db-agent/runs", data={"message": "hi", "stream": "false", "background": "true"}
            )
        finally:
            logging.getLogger().removeHandler(handler)
        assert resp.status_code == 202, resp.text
        assert len(harness.store._jobs) == 1, "a db-backed agent must ride the durable queue"
        job = next(iter(harness.store._jobs.values()))
        assert job["component_type"] == "agent"
        assert job["component_id"] == "db-agent"
        # Unpinned: the door resolved current_version (1) and validated the
        # input against it, so the ticket names THAT version - a version
        # published while the ticket waits must not change what executes
        assert job["payload"]["scope"] == {"user_id": None, "version": 1}
        assert not any(BYPASS in str(r.getMessage()) for r in records), "no bypass warning for a queued run"

    def test_version_pinned_submission_carries_the_version(self, harness):
        resp = harness.client.post(
            "/agents/db-agent/runs",
            data={"message": "hi", "stream": "false", "background": "true", "version": "1"},
        )
        assert resp.status_code == 202, resp.text
        job = next(iter(harness.store._jobs.values()))
        assert job["payload"]["scope"]["version"] == 1, "the worker must replay the SAME pinned version"

    def test_unknown_component_still_404s(self, harness):
        resp = harness.client.post(
            "/agents/no-such-agent/runs", data={"message": "hi", "stream": "false", "background": "true"}
        )
        assert resp.status_code == 404
        assert len(harness.store._jobs) == 0


class TestQueueabilityGuard:
    def test_registry_instance_is_queueable(self):
        from agno.agent import Agent

        agent = Agent(id="a1", name="A1")
        assert component_is_queueable(agent, "a1", [agent], db=None) is True

    def test_factory_entry_is_never_queueable(self, db):
        from agno.agent import Agent
        from agno.agent.factory import AgentFactory

        produced = Agent(id="fx", name="FX", db=db)
        factory = AgentFactory(id="fx", db=db, factory=lambda ctx: produced)
        assert component_is_queueable(produced, "fx", [factory], db=db) is False

    def test_off_registry_component_needs_a_db_to_replay_from(self):
        from agno.agent import Agent

        agent = Agent(id="db-agent", name="DB Agent")
        assert component_is_queueable(agent, "db-agent", [], db=None) is False
        assert component_is_queueable(agent, "db-agent", [], db=object()) is True

    def test_unresolved_component_is_not_queueable(self):
        assert component_is_queueable(None, "x", [], db=object()) is False

    def test_scope_shape(self):
        assert queue_scope("alice", 3) == {"user_id": "alice", "version": 3}
        assert queue_scope(None, None) == {"user_id": None, "version": None}


class TestWorkerReplaysDbResolution:
    @pytest.fixture()
    def agent_os(self, db):
        _create_db_agent(db, "db-agent")
        # A draft owned by alice: readable to its owner (pinned by version),
        # invisible to everyone else. A published component is shared by
        # design, so it cannot demonstrate the owner scope.
        _create_db_agent(db, "owned-agent", stage="draft", user_id="alice")
        return SimpleNamespace(
            queue=QueueConfig(durable=True, db=InMemoryQueueStore()),
            db=db,
            registry=None,
            agents=[],
            teams=[],
            workflows=[],
        )

    @pytest.mark.asyncio
    async def test_worker_resolves_db_component_from_ticket_scope(self, agent_os):
        app = SimpleNamespace(state=SimpleNamespace())
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            resolved = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "db-agent", "payload": {"scope": queue_scope(None, None)}}
            )
            assert resolved is not None and resolved.id == "db-agent"
            assert resolved.db is agent_os.db, "the rehydrated component must carry the OS db for run persistence"

    @pytest.mark.asyncio
    async def test_worker_honours_owner_scope(self, agent_os):
        app = SimpleNamespace(state=SimpleNamespace())
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            as_owner = await worker._aresolve_job_component(
                {
                    "component_type": "agent",
                    "component_id": "owned-agent",
                    "payload": {"scope": queue_scope("alice", 1)},
                }
            )
            assert as_owner is not None and as_owner.id == "owned-agent"
            as_stranger = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "owned-agent", "payload": {"scope": queue_scope("bob", 1)}}
            )
            assert as_stranger is None, "the worker must not widen the owner scope the door enforced"

    @pytest.mark.asyncio
    async def test_worker_resolves_pinned_version(self, agent_os):
        agent_os.db.upsert_config("db-agent", config={"name": "db-agent", "instructions": "draft v2"})
        app = SimpleNamespace(state=SimpleNamespace())
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            v1 = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "db-agent", "payload": {"scope": queue_scope(None, 1)}}
            )
            v2 = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "db-agent", "payload": {"scope": queue_scope(None, 2)}}
            )
            unpinned = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "db-agent", "payload": {"scope": queue_scope(None, None)}}
            )
            assert v1 is not None and v1.instructions == "hi"
            assert v2 is not None and v2.instructions == "draft v2"
            assert unpinned is not None and unpinned.instructions == "hi", "unpinned takes the published version"

    @pytest.mark.asyncio
    async def test_worker_still_prefers_the_registry(self, agent_os):
        from agno.agent import Agent

        registered = Agent(id="db-agent", name="Registered twin", db=agent_os.db)
        agent_os.agents = [registered]
        app = SimpleNamespace(state=SimpleNamespace())
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            resolved = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "db-agent", "payload": {"scope": queue_scope(None, None)}}
            )
            assert resolved is not None and resolved.name == "Registered twin"

    @pytest.mark.asyncio
    async def test_unknown_component_resolves_to_none(self, agent_os):
        app = SimpleNamespace(state=SimpleNamespace())
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            resolved = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "ghost", "payload": {"scope": queue_scope(None, None)}}
            )
            assert resolved is None


class TestResolverCompatibility:
    @pytest.mark.asyncio
    async def test_two_argument_sync_resolver_keeps_working_for_unscoped_tickets(self):
        sentinel = object()
        worker = QueueWorker(
            store=InMemoryQueueStore(),
            resolve_component=lambda t, i: sentinel,
            config=QueueConfig(durable=True),
        )
        assert await worker._aresolve_job_component({"component_type": "agent", "component_id": "x"}) is sentinel

    @pytest.mark.asyncio
    async def test_scoped_ticket_passes_scope_to_the_resolver(self):
        seen = {}

        async def resolver(component_type, component_id, scope=None):
            seen["scope"] = scope
            return "resolved"

        worker = QueueWorker(store=InMemoryQueueStore(), resolve_component=resolver, config=QueueConfig(durable=True))
        job = {"component_type": "agent", "component_id": "x", "payload": {"scope": queue_scope("alice", 2)}}
        assert await worker._aresolve_job_component(job) == "resolved"
        assert seen["scope"] == {"user_id": "alice", "version": 2}


class TestWebSocketSubmissionCarriesTheVersionStamp:
    """The HTTP seams stamp the pinned version into kwargs BEFORE the durable
    branch. The WS seam stamped only on its non-queued path, so a queued
    version-pinned run persisted no stamp and a later continue re-resolved
    whatever was current instead of the pinned version."""

    def test_queued_ws_kwargs_carry_the_stamp(self, db):
        import json

        from agno.os.utils import stamp_component_version
        from agno.workflow import Step, Workflow

        def noop(step_input):
            return "ok"

        workflow = Workflow(id="wf-1", name="WF", db=db, steps=[Step(name="noop", executor=noop)])
        app = AgentOS(workflows=[workflow], db=db, telemetry=False).get_app()
        store = InMemoryQueueStore()
        app.state.queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True))

        with TestClient(app).websocket_connect("/workflows/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "action": "start-workflow",
                        "workflow_id": "wf-1",
                        "message": "hi",
                        "version": 1,
                        "session_id": "s1",
                    }
                )
            )
            for _ in range(10):
                frame = json.loads(ws.receive_text())
                if frame.get("event") == "queued":
                    break
                assert frame.get("event") != "error", frame
            else:
                raise AssertionError("the WS submission never reached the durable queue")

        assert len(store._jobs) == 1
        job = next(iter(store._jobs.values()))
        expected_kwargs: dict = {}
        stamp_component_version(expected_kwargs, 1)
        assert job["payload"]["kwargs"] == expected_kwargs, "the queued run must carry the version stamp"
        assert job["payload"]["scope"]["version"] == 1


class TestTicketNamesAConcreteVersion:
    def test_unpinned_db_component_pins_current_version(self, db):
        _create_db_agent(db, "db-agent")
        scope = resolve_queue_scope("db-agent", [], db, None, None)
        assert scope == {"user_id": None, "version": 1}

    def test_explicit_pin_wins(self, db):
        _create_db_agent(db, "db-agent")
        db.upsert_config("db-agent", config={"name": "db-agent", "instructions": "v2"})
        assert resolve_queue_scope("db-agent", [], db, "alice", 2) == {"user_id": "alice", "version": 2}

    def test_registry_component_stays_unversioned(self, db):
        from agno.agent import Agent

        registered = Agent(id="reg-agent", name="Registered", db=db)
        assert resolve_queue_scope("reg-agent", [registered], db, None, None) == {"user_id": None, "version": None}

    def test_no_db_stays_unversioned(self):
        assert resolve_queue_scope("db-agent", [], None, None, None) == {"user_id": None, "version": None}

    def test_idempotency_duplicate_must_match_version(self):
        from fastapi import HTTPException

        existing = {
            "component_type": "agent",
            "component_id": "db-agent",
            "payload": {"scope": {"user_id": None, "version": 1}},
        }
        ensure_duplicate_matches_component(existing, "agent", "db-agent", version=1)
        with pytest.raises(HTTPException) as exc:
            ensure_duplicate_matches_component(existing, "agent", "db-agent", version=2)
        assert exc.value.status_code == 409

    def test_idempotency_duplicate_without_scope_matches_unversioned(self):
        # Tickets from a pre-scope producer carry no scope: they match an
        # unversioned replay and nothing else
        existing = {"component_type": "agent", "component_id": "a1", "payload": {"input": "hi"}}
        ensure_duplicate_matches_component(existing, "agent", "a1", version=None)


class TestFactoryIdNeverFallsThroughToTheDb:
    @pytest.mark.asyncio
    async def test_factory_match_returns_none_even_with_a_db_twin(self, db):
        from agno.agent import Agent
        from agno.agent.factory import AgentFactory

        # A db component that shares the factory's id: the worker must NOT
        # execute it in the factory's place
        _create_db_agent(db, "fx-agent")
        produced = Agent(id="fx-agent", name="Produced", db=db)
        factory = AgentFactory(id="fx-agent", db=db, factory=lambda ctx: produced)
        agent_os = SimpleNamespace(
            queue=QueueConfig(durable=True, db=InMemoryQueueStore()),
            db=db,
            registry=None,
            agents=[factory],
            teams=[],
            workflows=[],
        )
        app = SimpleNamespace(state=SimpleNamespace())
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            resolved = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "fx-agent", "payload": {"scope": queue_scope(None, 1)}}
            )
            assert resolved is None


class TestUnfencedWarningCoversTheAgentOsDb:
    def test_os_db_without_the_primitive_warns(self, db, caplog):
        # No code-registered component at all: the only session store in play
        # is the AgentOS db that db-backed components inherit
        agent_os = SimpleNamespace(agents=[], teams=[], workflows=[], db=db)
        with caplog.at_level("WARNING"):
            warn_unfenced_session_stores(agent_os)
        assert any("SqliteDb" in r.getMessage() and "UNFENCED" in r.getMessage() for r in caplog.records)

    def test_fenced_os_db_stays_silent(self, caplog):
        fenced_db = SimpleNamespace(update_run_in_session=lambda *a, **k: None)
        agent_os = SimpleNamespace(agents=[], teams=[], workflows=[], db=fenced_db)
        with caplog.at_level("WARNING"):
            warn_unfenced_session_stores(agent_os)
        assert not any("UNFENCED" in r.getMessage() for r in caplog.records)
