"""Durable queue for factory-backed components.

A factory builds its component per request from a RequestContext. Before
this, every factory submission with ``background=true`` bypassed the durable
queue and executed as a detached task on the accepting replica. Now the
accepting endpoint stamps the request context (user, session, validated
input, trusted claims) on the ticket and the worker invokes the factory
again at claim time with that context, ``request=None``.

Also covers the read routes that resolved a factory without the request and
answered 400 for every poll of a factory run.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from agno.agent import Agent
from agno.agent.factory import AgentFactory
from agno.db.sqlite import SqliteDb
from agno.factory import FactoryValidationError, QueuedRequest
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.job_queue import (
    UnbuildableComponent,
    aresolve_factory_from_scope,
    factory_queue_scope,
    get_active_queue_worker,
    queue_lifespan,
    queue_scope,
    resolve_queue_scope,
)
from agno.team import Team
from agno.team.factory import TeamFactory

BYPASS = "bypasses the durable queue"


class Persona(BaseModel):
    persona: str = "default"


@pytest.fixture()
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "factories.db"))


@pytest.fixture()
def seen():
    """Every RequestContext a factory in these tests was invoked with."""
    return []


@pytest.fixture()
def agent_factory(db, seen):
    def build(ctx):
        seen.append(ctx)
        persona = ctx.input.persona if isinstance(ctx.input, Persona) else "none"
        return Agent(id="fx-agent", name="FX", db=db, instructions=f"persona={persona}")

    return AgentFactory(id="fx-agent", db=db, factory=build, input_schema=Persona)


@pytest.fixture()
def team_factory(db, seen):
    def build(ctx):
        seen.append(ctx)
        return Team(id="fx-team", name="FX Team", db=db, members=[Agent(id="fx-member", name="Member")])

    return TeamFactory(id="fx-team", db=db, factory=build)


class _TrustedStateMiddleware(BaseHTTPMiddleware):
    """Stand-in for the JWT middleware: puts claims and scopes on request.state."""

    async def dispatch(self, request, call_next):
        request.state.claims = {"sub": "alice", "org": "acme"}
        request.state.scopes = ["runs:write", "agents:read"]
        return await call_next(request)


@pytest.fixture()
def harness(db, agent_factory, team_factory, monkeypatch):
    """A real AgentOS whose only components are factories. The worker never
    runs; the prepare seam is a no-op so a 202 means the ticket was enqueued."""

    async def ok_prepare(component, component_type, run_id, session_id, user_id, input):
        return None

    monkeypatch.setattr("agno.os.job_queue.aprepare_queued_run", ok_prepare)
    app = AgentOS(agents=[agent_factory], teams=[team_factory], db=db, telemetry=False).get_app()
    app.add_middleware(_TrustedStateMiddleware)
    store = InMemoryQueueStore()
    app.state.queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True))
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(app=app, store=store, client=client, db=db)


def _only_job(store):
    assert len(store._jobs) == 1, "exactly one ticket must have been enqueued"
    return next(iter(store._jobs.values()))


class TestFactorySubmissionsRideTheQueue:
    def test_background_submission_stamps_the_request_context(self, harness, caplog):
        resp = harness.client.post(
            "/agents/fx-agent/runs",
            data={
                "message": "hi",
                "stream": "false",
                "background": "true",
                "user_id": "alice",
                "session_id": "s-1",
                "factory_input": json.dumps({"persona": "pirate"}),
            },
        )
        assert resp.status_code == 202, resp.text
        job = _only_job(harness.store)
        assert job["component_type"] == "agent"
        assert job["component_id"] == "fx-agent"
        scope = job["payload"]["scope"]
        assert scope["source"] == "factory"
        assert scope["pinned"] is None
        # Exactly what the door handed the factory, minus the raw request
        assert scope["context"] == {
            "user_id": "alice",
            "session_id": "s-1",
            "input": {"persona": "pirate"},
            "claims": {"sub": "alice", "org": "acme"},
            "scopes": ["agents:read", "runs:write"],
        }
        assert BYPASS not in caplog.text

    def test_team_factory_submission_rides_the_queue(self, harness):
        resp = harness.client.post(
            "/teams/fx-team/runs",
            data={"message": "hi", "stream": "false", "background": "true", "session_id": "t-1"},
        )
        assert resp.status_code == 202, resp.text
        job = _only_job(harness.store)
        assert job["component_type"] == "team"
        assert job["payload"]["scope"]["source"] == "factory"
        assert job["payload"]["scope"]["context"]["session_id"] == "t-1"

    def test_invalid_factory_input_is_refused_at_the_door(self, harness):
        resp = harness.client.post(
            "/agents/fx-agent/runs",
            data={"message": "hi", "stream": "false", "background": "true", "factory_input": '{"persona": 5}'},
        )
        assert resp.status_code == 400, resp.text
        assert len(harness.store._jobs) == 0

    def test_scope_shape(self):
        state = SimpleNamespace(claims={"sub": "bob"}, scopes={"b", "a"})
        scope = factory_queue_scope(state, "bob", "s", '{"k": 1}', pinned=None)
        assert scope == {
            "user_id": "bob",
            "version": None,
            "pinned": None,
            "source": "factory",
            "context": {
                "user_id": "bob",
                "session_id": "s",
                "input": {"k": 1},
                "claims": {"sub": "bob"},
                "scopes": ["a", "b"],
            },
        }
        # The WebSocket door hands the parsed object, not a string
        assert factory_queue_scope(SimpleNamespace(), None, None, {"k": 2})["context"]["input"] == {"k": 2}
        # Nothing the door did not parse rides the ticket
        assert factory_queue_scope(SimpleNamespace(), None, None, "not json")["context"]["input"] is None
        assert factory_queue_scope(SimpleNamespace(), None, None, "[1, 2]")["context"]["input"] is None

    def test_resolve_queue_scope_picks_the_factory_shape(self, db, agent_factory):
        state = SimpleNamespace(claims={}, scopes=[])
        scope = resolve_queue_scope(
            "fx-agent", [agent_factory], db, "owner", None, state=state, context_user_id="alice", session_id="s"
        )
        assert scope["source"] == "factory"
        assert scope["context"]["user_id"] == "alice"
        plain = Agent(id="plain", name="Plain")
        assert resolve_queue_scope("plain", [plain], db, "owner", None, state=state)["source"] == "registry"


class TestWorkerInvokesTheFactoryAgain:
    @pytest.fixture()
    def agent_os(self, db, agent_factory, team_factory):
        return SimpleNamespace(
            queue=QueueConfig(durable=True, db=InMemoryQueueStore()),
            db=db,
            registry=None,
            agents=[agent_factory],
            teams=[team_factory],
            workflows=[],
        )

    @pytest.mark.asyncio
    async def test_worker_rebuilds_the_context_and_resolves(self, agent_os, seen):
        app = SimpleNamespace(state=SimpleNamespace())
        state = SimpleNamespace(claims={"sub": "alice", "org": "acme"}, scopes=["runs:write"])
        scope = factory_queue_scope(state, "alice", "s-1", '{"persona": "pirate"}')
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            resolved = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "fx-agent", "payload": {"scope": scope}}
            )
        assert isinstance(resolved, Agent)
        assert resolved.id == "fx-agent"
        assert resolved.instructions == "persona=pirate"
        ctx = seen[-1]
        assert ctx.user_id == "alice"
        assert ctx.session_id == "s-1"
        assert isinstance(ctx.request, QueuedRequest) and not ctx.request
        assert ctx.input == Persona(persona="pirate")
        assert ctx.trusted.claims == {"sub": "alice", "org": "acme"}
        assert ctx.trusted.scopes == frozenset({"runs:write"})

    @pytest.mark.asyncio
    async def test_worker_resolves_a_team_factory(self, agent_os):
        app = SimpleNamespace(state=SimpleNamespace())
        scope = factory_queue_scope(SimpleNamespace(), "alice", "t-1", None)
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            resolved = await worker._aresolve_job_component(
                {"component_type": "team", "component_id": "fx-team", "payload": {"scope": scope}}
            )
        assert isinstance(resolved, Team)
        assert resolved.id == "fx-team"
        # The HTTP path's per-request copy sets this; the worker must match
        assert resolved.store_member_responses is True

    @pytest.mark.asyncio
    async def test_ticket_without_the_context_leaves_the_factory_unresolved(self, agent_os, seen):
        app = SimpleNamespace(state=SimpleNamespace())
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            # Registry-sourced (a plain instance was expected) and pre-scope
            # tickets carry no request context: nothing to invoke the factory with
            registry_sourced = await worker._aresolve_job_component(
                {
                    "component_type": "agent",
                    "component_id": "fx-agent",
                    "payload": {"scope": queue_scope(None, None, source="registry")},
                }
            )
            pre_scope = await worker._aresolve_job_component({"component_type": "agent", "component_id": "fx-agent"})
        assert registry_sourced is None
        assert pre_scope is None
        assert seen == []

    @pytest.mark.asyncio
    async def test_factory_ticket_never_runs_a_plain_registry_twin(self, db):
        # A deploy replaced the factory with a plain agent of the same id: the
        # ticket was accepted for a factory-built component, so it must not
        # execute the twin
        plain = Agent(id="fx-agent", name="Plain", db=db)
        agent_os = SimpleNamespace(
            queue=QueueConfig(durable=True, db=InMemoryQueueStore()),
            db=db,
            registry=None,
            agents=[plain],
            teams=[],
            workflows=[],
        )
        app = SimpleNamespace(state=SimpleNamespace())
        scope = factory_queue_scope(SimpleNamespace(), "alice", "s", None)
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            resolved = await worker._aresolve_job_component(
                {"component_type": "agent", "component_id": "fx-agent", "payload": {"scope": scope}}
            )
        assert resolved is None

    @pytest.mark.asyncio
    async def test_factory_refusal_is_unbuildable_with_a_row_handle(self, db):
        def refuse(ctx):
            raise FactoryValidationError("tenant disabled")

        factory = AgentFactory(id="fx-agent", db=db, factory=refuse)
        context = factory_queue_scope(SimpleNamespace(), "alice", "s", None)["context"]
        refused = await aresolve_factory_from_scope(factory, "agent", context)
        assert isinstance(refused, UnbuildableComponent)
        assert refused.permanent is True
        assert "tenant disabled" in refused.reason
        assert isinstance(refused.row_handle, Agent)
        assert refused.row_handle.id == "fx-agent" and refused.row_handle.db is db
        # No context at all is a corrupt ticket: permanent too
        corrupt = await aresolve_factory_from_scope(factory, "agent", None)
        assert isinstance(corrupt, UnbuildableComponent) and corrupt.permanent is True

    @pytest.mark.asyncio
    async def test_reading_ctx_request_is_a_permanent_failure_naming_the_fix(self, db):
        def reads_headers(ctx):
            return Agent(name=ctx.request.headers.get("x-region", "us"))

        factory = AgentFactory(id="fx-agent", db=db, factory=reads_headers)
        context = factory_queue_scope(SimpleNamespace(), "alice", "s", None)["context"]
        refused = await aresolve_factory_from_scope(factory, "agent", context)
        assert isinstance(refused, UnbuildableComponent) and refused.permanent is True
        assert "ctx.request.headers" in refused.reason and "factory_input" in refused.reason

    @pytest.mark.asyncio
    async def test_unexpected_factory_errors_take_the_retry_budget(self, db):
        def flaky(ctx):
            raise ConnectionError("config service down")

        factory = AgentFactory(id="fx-agent", db=db, factory=flaky)
        context = factory_queue_scope(SimpleNamespace(), "alice", "s", None)["context"]
        failed = await aresolve_factory_from_scope(factory, "agent", context)
        assert isinstance(failed, UnbuildableComponent) and failed.permanent is False

    @pytest.mark.asyncio
    async def test_unknown_component_type_is_refused(self, db, agent_factory):
        context = factory_queue_scope(SimpleNamespace(), "alice", "s", None)["context"]
        assert await aresolve_factory_from_scope(agent_factory, "connector", context) is None


class _ScriptedModel(Model):
    def __init__(self):
        super().__init__(id="scripted", name="scripted", provider="test")

    def invoke(self, *args, **kwargs):
        return ModelResponse(role="assistant", content="scripted answer", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


class Required(BaseModel):
    tenant: str


class TestFactoryReadRoutesNeverInvokeTheFactory:
    """Reads only need the run rows in the factory's db. Invoking the factory
    on every poll rebuilt a component per GET, and a factory whose
    input_schema has required fields answered 400 (a GET carries no
    factory_input)."""

    @pytest.fixture()
    def reads(self, db):
        from agno.workflow import Step, Workflow
        from agno.workflow.factory import WorkflowFactory

        invoked: list = []

        def refuse(ctx):
            invoked.append(ctx)
            raise AssertionError("a read must not invoke the factory")

        agent = Agent(id="rx-agent", db=db, model=_ScriptedModel())
        team = Team(
            id="rx-team", db=db, model=_ScriptedModel(), members=[Agent(id="rx-member", model=_ScriptedModel())]
        )
        workflow = Workflow(id="rx-wf", db=db, steps=[Step(name="s", executor=lambda step_input: "step done")])
        runs = {
            "agents/rx-agent": agent.run("hi", session_id="sa").run_id,
            "teams/rx-team": team.run("hi", session_id="st").run_id,
            "workflows/rx-wf": workflow.run("hi", session_id="sw").run_id,
        }
        app = AgentOS(
            agents=[AgentFactory(id="rx-agent", db=db, factory=refuse, input_schema=Required)],
            teams=[TeamFactory(id="rx-team", db=db, factory=refuse, input_schema=Required)],
            workflows=[WorkflowFactory(id="rx-wf", db=db, factory=refuse, input_schema=Required)],
            db=db,
            telemetry=False,
        ).get_app()
        return SimpleNamespace(client=TestClient(app), runs=runs, invoked=invoked)

    @pytest.mark.parametrize(
        "path",
        [
            "/agents/rx-agent/runs?session_id=sa",
            "/agents/rx-agent/runs/{run}?session_id=sa",
            "/agents/rx-agent/runs/{run}/checkpoints?session_id=sa",
            "/teams/rx-team/runs?session_id=st",
            "/teams/rx-team/runs/{run}?session_id=st",
            "/teams/rx-team/runs/{run}/checkpoints?session_id=st",
            "/workflows/rx-wf/runs/{run}?session_id=sw",
        ],
    )
    def test_read_routes_answer_from_the_run_rows(self, reads, path):
        component = "/".join(path.split("/")[1:3])
        run_id = reads.runs[component]
        resp = reads.client.get(path.format(run=run_id))
        assert resp.status_code == 200, resp.text
        assert run_id in resp.text
        assert reads.invoked == []

    @pytest.mark.parametrize("component", ["agents/rx-agent", "teams/rx-team"])
    def test_checkpoint_snapshot_reads_without_the_factory(self, reads, component):
        session = "sa" if component.startswith("agents") else "st"
        run_id = reads.runs[component]
        resp = reads.client.get(f"/{component}/runs/{run_id}/checkpoints/0", params={"session_id": session})
        assert resp.status_code == 200, resp.text
        assert reads.invoked == []


class TestQueueSurfaceRedactsClaims:
    @pytest.fixture()
    def ops(self):
        from fastapi import FastAPI

        from agno.db.schemas.jobs import QueuedJob
        from agno.os.routers.job_queue import get_queue_router

        app = FastAPI()
        app.include_router(get_queue_router(SimpleNamespace()))
        store = InMemoryQueueStore()
        app.state.queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True))
        scope = factory_queue_scope(
            SimpleNamespace(claims={"sub": "alice", "email": "alice@acme.io"}, scopes=["runs:write"]),
            "alice",
            "s-1",
            json.dumps({"persona": "pirate"}),
        )
        store._jobs["j1"] = QueuedJob(
            id="j1",
            component_type="agent",
            component_id="fx-agent",
            session_id="s-1",
            payload={"input": "hi", "scope": scope},
        ).to_dict()
        return SimpleNamespace(store=store, client=TestClient(app))

    @pytest.mark.parametrize("path", ["/queue/jobs", "/queue/jobs/j1"])
    def test_claims_never_leave_the_ops_surface(self, ops, path):
        body = ops.client.get(path).json()
        job = body["data"][0] if "data" in body else body
        context = job["payload"]["scope"]["context"]
        assert context["claims"] == "[redacted]"
        assert "alice@acme.io" not in json.dumps(body)
        assert context["input"] == {"persona": "pirate"}, "the rest of the context stays visible to operators"
        assert ops.store._jobs["j1"]["payload"]["scope"]["context"]["claims"]["sub"] == "alice", (
            "the stored ticket keeps the claims the worker needs"
        )


def _wait_for(predicate, timeout: float = 10.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _run_status(db, component_id: str, run_id: str, session_id: str):
    run = Agent(id=component_id, db=db).get_run_output(run_id, session_id=session_id, user_id="alice")
    status = getattr(run, "status", None)
    return str(getattr(status, "value", status) or "").upper(), getattr(run, "content", None)


class TestUnbuildableFactoryRunsFailFast:
    """A factory that cannot build on the worker used to leave the accepted
    run PENDING forever: the worker left the claim, and the sweep could not
    persist the error without the component, so it re-swept (and re-invoked
    the factory) every lock_grace. The run row is reachable through the
    factory's db, so the run now ends ERROR with the reason."""

    def _submit(self, db, build, **queue_kwargs):
        store = InMemoryQueueStore()
        agent_os = AgentOS(
            agents=[AgentFactory(id="fx-agent", db=db, factory=build)],
            db=db,
            queue=QueueConfig(durable=True, db=store, poll_interval=0.05, **queue_kwargs),
            telemetry=False,
        )
        return store, agent_os

    def test_factory_reading_ctx_request_fails_the_run_with_the_fix(self, db):
        calls: list = []

        def reads_headers(ctx):
            calls.append(ctx.request)
            return Agent(name=f"support-{ctx.request.headers.get('x-region', 'us')}", model=_ScriptedModel())

        store, agent_os = self._submit(db, reads_headers)
        with TestClient(agent_os.get_app()) as client:
            resp = client.post(
                "/agents/fx-agent/runs",
                headers={"x-region": "eu"},
                data={"message": "hi", "background": "true", "stream": "false", "session_id": "s1", "user_id": "alice"},
            )
            assert resp.status_code == 202, resp.text
            run_id = resp.json()["run_id"]
            assert _wait_for(lambda: store._jobs[run_id]["status"] == "failed")
            poll = client.get(f"/agents/fx-agent/runs/{run_id}", params={"session_id": "s1"})
        job = store._jobs[run_id]
        assert job["attempt"] == 1, "a permanent failure takes no retry"
        assert "ctx.request.headers" in job["error"]
        status, content = _run_status(db, "fx-agent", run_id, "s1")
        assert status == "ERROR"
        assert "factory_input" in (content or "")
        assert poll.status_code == 200 and poll.json()["status"] == "ERROR"
        # Stamp, execution and the error persist each resolve once; the sweep never takes over
        assert sum(1 for request in calls if not request) == 3

    def test_unexpected_factory_error_retries_then_fails(self, db):
        def flaky(ctx):
            if ctx.request:
                return Agent(model=_ScriptedModel())
            raise ConnectionError("config service down")

        store, agent_os = self._submit(db, flaky, max_attempts=2, retry_delay_seconds=0)
        with TestClient(agent_os.get_app()) as client:
            resp = client.post(
                "/agents/fx-agent/runs",
                data={"message": "hi", "background": "true", "stream": "false", "session_id": "s2", "user_id": "alice"},
            )
            run_id = resp.json()["run_id"]
            assert _wait_for(lambda: store._jobs[run_id]["status"] == "failed")
        assert store._jobs[run_id]["attempt"] == 2, "the retry budget was spent before failing"
        assert _run_status(db, "fx-agent", run_id, "s2")[0] == "ERROR"

    @pytest.mark.asyncio
    async def test_sweep_terminalizes_an_exhausted_unbuildable_ticket(self, db):
        import time

        from agno.db.schemas.jobs import QueuedJob
        from agno.os.job_queue import aprepare_queued_run
        from agno.os.utils import factory_row_handle

        invoked: list = []

        def refuse(ctx):
            invoked.append(ctx)
            raise FactoryValidationError("schema changed")

        factory = AgentFactory(id="fx-agent", db=db, factory=refuse)
        store = InMemoryQueueStore()
        scope = factory_queue_scope(SimpleNamespace(), "alice", "s3", None)
        job = QueuedJob(
            id="r-swept",
            component_type="agent",
            component_id="fx-agent",
            session_id="s3",
            user_id="alice",
            payload={"input": "hi", "scope": scope},
            status="running",
            attempt=1,
            max_attempts=1,
        ).to_dict()
        job.update(locked_by="dead-worker", locked_at=int(time.time()) - 600)
        store._jobs["r-swept"] = job
        await aprepare_queued_run(factory_row_handle(factory), "agent", "r-swept", "s3", "alice", "hi")
        assert _run_status(db, "fx-agent", "r-swept", "s3")[0] == "PENDING"

        agent_os = _worker_os_for(db, factory, store)
        app = SimpleNamespace(state=SimpleNamespace())
        async with queue_lifespan(app, agent_os):
            worker = get_active_queue_worker()
            assert worker is not None
            await worker._sweep_exhausted()
        assert store._jobs["r-swept"]["status"] == "failed"
        assert _run_status(db, "fx-agent", "r-swept", "s3")[0] == "ERROR"


def _worker_os_for(db, factory, store):
    return SimpleNamespace(
        queue=QueueConfig(durable=True, db=store, poll_interval=60),
        db=db,
        registry=None,
        agents=[factory],
        teams=[],
        workflows=[],
    )


class TestQueuedFactoryRunsEndToEnd:
    """Accept on the HTTP door, claim and execute on the real queue worker,
    poll the result: the whole path a factory run takes on the durable queue."""

    @pytest.fixture()
    def live(self, db):
        built: list = []

        def build_agent(ctx):
            built.append(ctx)
            return Agent(model=_ScriptedModel(), instructions=f"persona={ctx.input.persona}")

        def build_team(ctx):
            built.append(ctx)
            return Team(model=_ScriptedModel(), members=[Agent(id="e2e-member", model=_ScriptedModel())])

        store = InMemoryQueueStore()
        app = AgentOS(
            agents=[AgentFactory(id="e2e-agent", db=db, factory=build_agent, input_schema=Persona)],
            teams=[TeamFactory(id="e2e-team", db=db, factory=build_team)],
            db=db,
            queue=QueueConfig(durable=True, db=store, poll_interval=0.05),
            telemetry=False,
        ).get_app()
        app.add_middleware(_TrustedStateMiddleware)
        return SimpleNamespace(app=app, store=store, built=built)

    @pytest.mark.parametrize(
        "route, extra",
        [("agents/e2e-agent", {"factory_input": json.dumps({"persona": "pirate"})}), ("teams/e2e-team", {})],
    )
    def test_factory_run_completes_on_the_worker(self, live, route, extra):
        with TestClient(live.app) as client:
            resp = client.post(
                f"/{route}/runs",
                data={"message": "hi", "background": "true", "stream": "false", "user_id": "alice", **extra},
            )
            assert resp.status_code == 202, resp.text
            run_id, session_id = resp.json()["run_id"], resp.json()["session_id"]
            assert _wait_for(lambda: live.store._jobs[run_id]["status"] == "completed")
            poll = client.get(f"/{route}/runs/{run_id}", params={"session_id": session_id})
        assert poll.status_code == 200, poll.text
        assert poll.json()["status"] == "COMPLETED"
        assert poll.json()["content"] == "scripted answer"
        on_worker = [ctx for ctx in live.built if isinstance(ctx.request, QueuedRequest)]
        assert on_worker, "the worker rebuilt the component from the ticket"
        assert on_worker[0].user_id == "alice"
        assert on_worker[0].session_id == session_id
        assert dict(on_worker[0].trusted.claims) == {"sub": "alice", "org": "acme"}
        assert on_worker[0].trusted.scopes == frozenset({"runs:write", "agents:read"})
        if extra:
            assert on_worker[0].input == Persona(persona="pirate")
