"""Submission of sandboxed agents to the durable queue through the AgentOS run route.

A registered agent must be the instance the worker runs on. A stored agent component is
rebuilt for every request, so its ticket carries a db queue scope and the route checks that
the worker's rebuild is the same agent on the same registry sandbox and database.
"""

import weakref
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.postgres import PostgresDb
from agno.os.job_queue import resolve_queue_scope
from agno.os.routers.agents import sandbox
from agno.os.utils import get_agent_by_id_async
from agno.registry import Registry
from agno.sandbox import Sandbox, _harness
from agno.sandbox.checkpoint import FileCheckpointStore

DB_URL = "postgresql+psycopg://ai:ai@localhost:1/ai"


class FakeSandbox(Sandbox):
    def __init__(self, id: Optional[str] = None, checkpoints: Any = None):
        self.id = id
        self.checkpoints = checkpoints
        self.env = None
        self.network = "isolated"

    def checkpoint_transfer(self, store):
        return SimpleNamespace(store=store)

    async def acreate(self, session_id, *, agent_id=None, generation=1, env=None):
        raise NotImplementedError

    async def aget(self, provider_ref):
        raise NotImplementedError

    async def aexec(self, handle, command, **kwargs):
        raise NotImplementedError

    async def astop(self, handle):
        raise NotImplementedError

    async def adestroy(self, handle):
        raise NotImplementedError


class StoredComponent:
    """One stored agent's config versions, served from a db the way the component loaders read them."""

    def __init__(self, db: PostgresDb, config: Dict[str, Any], version: int = 1):
        self.versions, self.version = {version: config}, version
        db.get_component = lambda component_id, **kwargs: {
            "component_id": component_id,
            "current_version": self.version,
        }
        db.get_config = lambda component_id, label=None, version=None, **kwargs: {
            "config": self.versions[version or self.version],
            "version": version or self.version,
        }

    def publish(self, config: Dict[str, Any]) -> int:
        self.version += 1
        self.versions[self.version] = config
        return self.version


class FakeWorker:
    """The durable queue as the route sees it, resolving tickets the way the queue worker does."""

    def __init__(self, db: Optional[PostgresDb], registry: Optional[Registry], agents: List[Any]):
        self.config = SimpleNamespace(durable=True, redis=None, max_attempts=3, deployment_id="d1")
        self.store = SimpleNamespace(serializes_sessions=True)
        self.db, self.registry, self.agents = db, registry, agents
        self.resolved: List[Any] = []

    async def _aresolve_job_component(self, job: Dict[str, Any]) -> Any:
        scope = (job.get("payload") or {}).get("scope") or {}
        if scope.get("source") == "db":
            agent = await get_agent_by_id_async(
                job["component_id"],
                None,
                db=self.db,
                registry=self.registry,
                version=scope.get("version"),
                create_fresh=True,
                user_id=scope.get("user_id"),
            )
        else:
            agent = next((entry for entry in self.agents if entry.get_id() == job["component_id"]), None)
        self.resolved.append(agent)
        return agent


@pytest.fixture
def accepted(monkeypatch):
    """Accept every ticket without a queue store, and keep the sandbox tables and sessions off the wire."""
    jobs: List[Dict[str, Any]] = []

    async def enqueue(worker, job, component=None):
        jobs.append(job)
        return {"reason": "enqueued", "job": job}

    async def prepared(*args, **kwargs):
        return None

    async def unowned(agent, session_id):
        return None

    async def tables_ok(agent, create=True):
        return None

    monkeypatch.setattr(sandbox, "aenqueue_ticket", enqueue)
    monkeypatch.setattr(sandbox, "aprepare_accepted_or_abort", prepared)
    monkeypatch.setattr(sandbox, "_session_owner", unowned)
    monkeypatch.setattr(_harness, "acheck_tables", tables_ok)
    monkeypatch.setattr(_harness, "_coordinators", weakref.WeakKeyDictionary())
    return jobs


@pytest.fixture
def db() -> PostgresDb:
    return PostgresDb(db_url=DB_URL, id="main")


@pytest.fixture
def registry_sandbox(tmp_path) -> FakeSandbox:
    return FakeSandbox(id="docker-local", checkpoints=FileCheckpointStore(tmp_path))


@pytest.fixture
def registry(db, registry_sandbox) -> Registry:
    return Registry(dbs=[db], sandboxes=[registry_sandbox])


async def stored_agent(db, registry, **overrides):
    """Load the stored agent the way the run route does: the AgentOS loader, strict, through the registry."""
    agent = await get_agent_by_id_async("coder", None, db=db, registry=registry, create_fresh=True, **overrides)
    assert agent is not None
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("durable, serializes_sessions", [(False, True), (True, False), (True, None)])
async def test_sandbox_submission_requires_durable_session_admission(durable, serializes_sessions):
    worker = SimpleNamespace(
        config=SimpleNamespace(durable=durable, redis=None),
        store=SimpleNamespace(serializes_sessions=serializes_sessions),
    )
    with pytest.raises(
        ValueError, match="^Sandbox API execution requires a durable queue with shared session admission$"
    ):
        await sandbox.enqueue_sandbox_run(Mock(), worker, input="hello", session_id="session", user_id=None, kwargs={})


@pytest.mark.asyncio
async def test_registered_agent_submits_without_a_scope_and_only_as_its_instance(accepted, db, registry_sandbox):
    agent = ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox)
    job = await sandbox.enqueue_sandbox_run(
        agent, FakeWorker(None, None, [agent]), input="hello", session_id="s1", user_id=None, kwargs={}
    )
    assert "scope" not in job["payload"] and job["payload"]["serialize_session"] is True
    other = ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox)
    with pytest.raises(ValueError, match="must use the registered agent instance"):
        await sandbox.enqueue_sandbox_run(
            agent, FakeWorker(None, None, [other]), input="hello", session_id="s1", user_id=None, kwargs={}
        )


@pytest.mark.asyncio
async def test_stored_agent_submits_with_a_db_scope_the_worker_rebuilds_from(accepted, db, registry, registry_sandbox):
    StoredComponent(db, ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox, max_turns=3).to_dict())
    agent = await stored_agent(db, registry, user_id="owner")
    assert agent.sandbox is registry_sandbox
    worker = FakeWorker(db, registry, [])
    scope = resolve_queue_scope("coder", [], db, "owner", None)

    job = await sandbox.enqueue_sandbox_run(
        agent, worker, input="hello", session_id="s1", user_id="owner", kwargs={}, scope=scope
    )

    assert job["component_id"] == "coder"
    assert job["payload"]["scope"] == {"user_id": "owner", "version": 1, "pinned": None, "source": "db"}
    assert job["payload"]["serialize_session"] is True
    [rebuilt] = worker.resolved
    assert rebuilt is not agent and isinstance(rebuilt, ClaudeAgent) and rebuilt.max_turns == 3
    assert rebuilt.sandbox is registry_sandbox
    assert _harness.coordinator(rebuilt) is _harness.coordinator(agent)


@pytest.mark.asyncio
async def test_stored_agent_with_table_overrides_reaches_one_coordinator(accepted, db, registry, registry_sandbox):
    config = CodexAgent(id="coder", db=db, sandbox=registry_sandbox).to_dict()
    config["db"]["session_table"] = "coder_sessions"
    StoredComponent(db, config)
    agent = await stored_agent(db, registry)
    assert agent.db is not db and agent.db.session_table_name == "coder_sessions"
    worker = FakeWorker(db, registry, [])

    await sandbox.enqueue_sandbox_run(
        agent,
        worker,
        input="hello",
        session_id="s1",
        user_id=None,
        kwargs={},
        scope=resolve_queue_scope("coder", [], db, None, None),
    )

    [rebuilt] = worker.resolved
    assert rebuilt.db is not agent.db
    shared = _harness.coordinator(agent)
    assert _harness.coordinator(rebuilt) is shared
    assert rebuilt.db.sandbox_coordinators == [shared] and agent.db.sandbox_coordinators == [shared]


@pytest.mark.asyncio
async def test_stored_agent_the_worker_cannot_rebuild_is_refused(accepted, db, registry, registry_sandbox):
    StoredComponent(db, ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox).to_dict())
    agent = await stored_agent(db, registry)
    with pytest.raises(ValueError, match="cannot rebuild stored agent 'coder'"):
        await sandbox.enqueue_sandbox_run(
            agent,
            FakeWorker(None, None, []),
            input="hello",
            session_id="s1",
            user_id=None,
            kwargs={},
            scope=resolve_queue_scope("coder", [], db, None, None),
        )


@pytest.mark.asyncio
async def test_stored_agent_rebuilt_on_another_sandbox_or_database_is_refused(
    accepted, db, registry, registry_sandbox, tmp_path
):
    StoredComponent(db, ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox).to_dict())
    agent = await stored_agent(db, registry)
    scope = resolve_queue_scope("coder", [], db, None, None)
    other_sandbox = Registry(
        dbs=[db], sandboxes=[FakeSandbox(id="docker-local", checkpoints=FileCheckpointStore(tmp_path))]
    )
    with pytest.raises(ValueError, match="different agent or on a different sandbox"):
        await sandbox.enqueue_sandbox_run(
            agent,
            FakeWorker(db, other_sandbox, []),
            input="hello",
            session_id="s1",
            user_id=None,
            kwargs={},
            scope=scope,
        )
    other_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:1/other", id="main")
    StoredComponent(other_db, agent.to_dict())
    with pytest.raises(ValueError, match="on a different database"):
        await sandbox.enqueue_sandbox_run(
            agent,
            FakeWorker(other_db, Registry(dbs=[other_db], sandboxes=[registry_sandbox]), []),
            input="hello",
            session_id="s1",
            user_id=None,
            kwargs={},
            scope=scope,
        )
    assert not accepted


@pytest.mark.asyncio
async def test_stored_agent_republished_during_acceptance_is_refused(accepted, db, registry, registry_sandbox):
    component = StoredComponent(db, ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox, max_turns=3).to_dict())
    agent = await stored_agent(db, registry)
    component.publish({**component.versions[1], "max_turns": 5})
    with pytest.raises(ValueError, match="changed while this request was being accepted"):
        await sandbox.enqueue_sandbox_run(
            agent,
            FakeWorker(db, registry, []),
            input="hello",
            session_id="s1",
            user_id=None,
            kwargs={},
            scope=resolve_queue_scope("coder", [], db, None, None),
        )
    assert not accepted


@pytest.mark.asyncio
async def test_version_pinning_is_accepted_for_stored_agents_only(accepted, db, registry, registry_sandbox):
    StoredComponent(db, ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox).to_dict(), version=2)
    agent = await stored_agent(db, registry, version=2)
    request = SimpleNamespace(headers={})
    common = dict(input="hello", session_id="s1", user_id=None, kwargs={}, stream=False, background=True, db=db)

    response = await sandbox.sandbox_run_response(
        agent, FakeWorker(db, registry, []), request, agents=[], scoped_user_id=None, version=2, **common
    )

    assert response.status_code == 202
    [job] = accepted
    assert job["payload"]["scope"] == {"user_id": None, "version": 2, "pinned": 2, "source": "db"}
    registered = ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox)
    with pytest.raises(HTTPException, match="version pinning is not supported"):
        await sandbox.sandbox_run_response(
            registered,
            FakeWorker(None, None, [registered]),
            request,
            agents=[registered],
            scoped_user_id=None,
            version=2,
            **common,
        )
    assert len(accepted) == 1


@pytest.mark.asyncio
async def test_idempotent_retry_after_a_publish_reads_the_result_through_the_tickets_version(
    accepted, db, registry, registry_sandbox, monkeypatch
):
    from agno.agents.base import BaseExternalAgent
    from agno.run.agent import RunOutput

    first = ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox).to_dict()
    first["db"]["session_table"] = "v1_sessions"
    component = StoredComponent(db, first)
    component.publish({**first, "db": {**first["db"], "session_table": "v2_sessions"}})
    agent = await stored_agent(db, registry)
    assert agent.db.session_table_name == "v2_sessions"
    scope = resolve_queue_scope("coder", [], db, None, None)
    original = {
        "id": "run-1",
        "component_type": "agent",
        "component_id": "coder",
        "session_id": "s1",
        "user_id": None,
        "status": "completed",
        "payload": {
            "input": "hello",
            "kwargs": {},
            "stream": True,
            "serialize_session": True,
            "scope": {**scope, "version": 1},
        },
    }

    async def duplicate(worker, job, component=None):
        return {"reason": "duplicate", "job": original}

    read_through = []

    async def stored_output(self, run_id, session_id, user_id=None):
        read_through.append(self.db.session_table_name)
        return RunOutput(run_id=run_id, session_id=session_id, content="done")

    async def completed(run_id):
        return original

    monkeypatch.setattr(sandbox, "aenqueue_ticket", duplicate)
    monkeypatch.setattr(BaseExternalAgent, "aget_run_output", stored_output)
    worker = FakeWorker(db, registry, [])
    worker.store.get_job = completed

    response = await sandbox.sandbox_run_response(
        agent,
        worker,
        SimpleNamespace(headers={}),
        input="hello",
        session_id="s1",
        user_id=None,
        kwargs={},
        stream=False,
        background=False,
        agents=[],
        db=db,
        scoped_user_id=None,
    )

    assert response.status_code == 200 and b"done" in response.body
    # The original ran version 1, whose sessions live in another table than version 2's.
    assert read_through == ["v1_sessions"]


@pytest.mark.asyncio
async def test_idempotent_retry_of_a_stored_agent_compares_the_pin_not_the_published_version(
    accepted, db, registry, registry_sandbox, monkeypatch
):
    StoredComponent(db, ClaudeAgent(id="coder", db=db, sandbox=registry_sandbox).to_dict(), version=2)
    agent = await stored_agent(db, registry)
    scope = resolve_queue_scope("coder", [], db, None, None)
    assert scope["version"] == 2
    submit = dict(input="hello", session_id="s1", user_id=None, kwargs={}, idempotency_key="key")
    original = {
        "id": "run-1",
        "component_type": "agent",
        "component_id": "coder",
        "session_id": "s1",
        "user_id": None,
        "payload": {
            "input": "hello",
            "kwargs": {},
            "stream": True,
            "serialize_session": True,
            "scope": {**scope, "version": 1},
        },
    }

    async def duplicate(worker, job, component=None):
        return {"reason": "duplicate", "job": original}

    monkeypatch.setattr(sandbox, "aenqueue_ticket", duplicate)
    # The original ran version 1 and version 2 was published since: the unpinned retry is the same submission.
    assert await sandbox.enqueue_sandbox_run(agent, FakeWorker(db, registry, []), scope=scope, **submit) is original
    with pytest.raises(HTTPException, match="different input or options"):
        await sandbox.enqueue_sandbox_run(agent, FakeWorker(db, registry, []), scope={**scope, "pinned": 2}, **submit)
