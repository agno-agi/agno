"""Workflow WebSocket submissions apply the same admission rules as HTTP.

The HTTP and WebSocket doors share the durable core (validation, enqueue,
register, prepare, tail), but the WebSocket door drifted on the guards that
run before it: which submissions may ride the queue, and which sessions a
caller may write into.
"""

import json
from types import SimpleNamespace
from typing import Any, List

import pytest

from agno.db.schemas.scheduler import COMPONENT_VERSION_METADATA_KEY


class FakeWebSocket:
    def __init__(self, app_state: Any):
        self.sent: List[dict] = []
        self.app = SimpleNamespace(state=app_state)

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


@pytest.fixture
def ws_env(monkeypatch):
    from agno.db.in_memory import InMemoryDb
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager
    from agno.os.routers.workflows import router as ws_router
    from agno.workflow.workflow import Workflow

    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr(ws_router, "get_event_stream", lambda: stream)
    workflow = Workflow(id="wf1", name="WF", db=InMemoryDb())
    monkeypatch.setattr(ws_router, "get_workflow_by_id", lambda **kwargs: workflow)

    async def no_prepare(*args, **kwargs):
        return None

    monkeypatch.setattr(ws_router, "aprepare_accepted_or_abort", no_prepare)
    # The non-durable path hands the run to the workflow itself; record it
    arun_calls: List[dict] = []

    async def recording_arun(**kwargs):
        arun_calls.append(kwargs)
        return None

    monkeypatch.setattr(workflow, "arun", recording_arun)
    store = InMemoryQueueStore()
    ws = FakeWebSocket(SimpleNamespace(queue_worker=SimpleNamespace(store=store, config=QueueConfig(durable=True))))
    os_stub = SimpleNamespace(workflows=[workflow], db=None, registry=None)
    yield SimpleNamespace(
        router=ws_router, stream=stream, ws=ws, os=os_stub, store=store, workflow=workflow, arun_calls=arun_calls
    )


def _queued_acks(env) -> List[dict]:
    return [f for f in env.ws.sent if f.get("event") == "queued"]


@pytest.mark.asyncio
async def test_version_pinned_submission_rides_the_queue_with_its_pin(ws_env):
    """The ticket carries the pin (resolution scope + run metadata stamp), so
    a pinned WebSocket submission queues like its HTTP twin, and a later
    continue reloads the pinned version rather than whatever is current."""
    from agno.run.base import RunStatus

    env = ws_env
    await env.router.handle_workflow_via_websocket(
        env.ws, {"workflow_id": "wf1", "session_id": "s1", "message": "hi", "version": 2}, env.os
    )
    try:
        acks = _queued_acks(env)
        assert len(acks) == 1, "a version-pinned submission must ride the queue"
        assert env.arun_calls == [], "and not also run in-process"
        job = await env.store.get_job(acks[0]["run_id"])
        assert job is not None
        assert job["payload"]["scope"]["pinned"] == 2
        stamped = job["payload"]["kwargs"].get("metadata") or {}
        assert stamped.get(COMPONENT_VERSION_METADATA_KEY) == 2, "the queued run carries the pin"
    finally:
        for ack in _queued_acks(env):
            await env.stream.complete_run(ack["run_id"], RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)


@pytest.mark.asyncio
async def test_factory_submission_rides_the_queue_with_its_pin(ws_env):
    """A factory-backed workflow queues like a registered instance: the door
    invokes the factory to validate the submission, and the ticket carries the
    request context and the version pin so the worker builds the same
    workflow instead of running it in-process on the accepting replica."""
    from agno.db.in_memory import InMemoryDb
    from agno.run.base import RunStatus
    from agno.workflow.factory import WorkflowFactory
    from agno.workflow.workflow import Workflow

    env = ws_env
    built = Workflow(id="wf-factory", name="Built", db=InMemoryDb())
    arun_calls: List[dict] = []

    async def recording_arun(**kwargs):
        arun_calls.append(kwargs)
        return None

    built.arun = recording_arun  # type: ignore[method-assign]
    factory_contexts: List[Any] = []

    def build(ctx):
        factory_contexts.append(ctx)
        return built

    env.os.workflows.append(WorkflowFactory(id="wf-factory", db=built.db, factory=build))
    await env.router.handle_workflow_via_websocket(
        env.ws,
        {"workflow_id": "wf-factory", "session_id": "s1", "message": "hi", "version": 1},
        env.os,
        ws_user_context={"user_id": "alice", "payload": {"sub": "alice"}, "scopes": {"workflows:run"}},
    )
    try:
        acks = _queued_acks(env)
        assert len(acks) == 1, f"a factory submission must ride the queue, got {env.ws.sent}"
        assert arun_calls == [], "and not also run in-process"
        assert len(factory_contexts) == 1, "the door invokes the factory once to validate the submission"
        assert factory_contexts[0].user_id == "alice"
        job = await env.store.get_job(acks[0]["run_id"])
        assert job is not None
        scope = job["payload"]["scope"]
        assert scope["source"] == "factory"
        assert scope["pinned"] == 1
        assert scope["context"]["user_id"] == "alice"
        assert scope["context"]["session_id"] == "s1"
        assert scope["context"]["claims"] == {"sub": "alice"}
        assert scope["context"]["scopes"] == ["workflows:run"]
        stamped = job["payload"]["kwargs"].get("metadata") or {}
        assert stamped.get(COMPONENT_VERSION_METADATA_KEY) == 1, "the queued run carries the pin"
    finally:
        for ack in _queued_acks(env):
            await env.stream.complete_run(ack["run_id"], RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)


def _isolated(ws_router):
    return ws_router.WebSocketAuthContext(jwt_enabled=True, is_admin=False, user_isolation_enabled=True)


@pytest.mark.asyncio
async def test_submission_into_another_users_session_is_refused(ws_env, monkeypatch):
    """HTTP refuses a run into a session owned by someone else before any
    background work: the runs table has no ownership predicate, so an
    unguarded write lands in the owner's history as their own turn. The
    WebSocket door pins the caller's identity to the token but let the
    client choose any session id; it must apply the same guard."""
    from agno.run.base import RunStatus

    env = ws_env
    monkeypatch.setattr(env.workflow.db, "get_session", lambda **kwargs: {"session_id": "s1", "user_id": "owner"})
    await env.router.handle_workflow_via_websocket(
        env.ws,
        {"workflow_id": "wf1", "session_id": "s1", "message": "hi"},
        env.os,
        ws_user_context={"user_id": "intruder"},
        ws_auth=_isolated(env.router),
    )
    try:
        assert not _queued_acks(env), "a run into another user's session must not be queued"
        assert await env.store.count_queued_jobs() == 0
        assert not env.arun_calls, "nor executed in-process"
        errors = [f for f in env.ws.sent if f.get("event") == "error"]
        assert errors, "the caller must be told the submission was refused"
    finally:
        for ack in _queued_acks(env):
            await env.stream.complete_run(ack["run_id"], RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)


@pytest.mark.asyncio
async def test_owner_submission_into_own_session_is_queued(ws_env, monkeypatch):
    from agno.run.base import RunStatus

    env = ws_env
    monkeypatch.setattr(env.workflow.db, "get_session", lambda **kwargs: {"session_id": "s1", "user_id": "owner"})
    await env.router.handle_workflow_via_websocket(
        env.ws,
        {"workflow_id": "wf1", "session_id": "s1", "message": "hi"},
        env.os,
        ws_user_context={"user_id": "owner"},
        ws_auth=_isolated(env.router),
    )
    try:
        acks = _queued_acks(env)
        assert len(acks) == 1, f"the owner's submission must be accepted, got {env.ws.sent}"
    finally:
        for ack in _queued_acks(env):
            await env.stream.complete_run(ack["run_id"], RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)


@pytest.mark.asyncio
async def test_submission_without_session_id_gets_a_fresh_session(ws_env):
    """HTTP mints a new session for a submission that names none. The
    WebSocket door fell back to the workflow's own session_id first, so every
    client omitting the field on a workflow configured with one pooled into
    a single session, and under per-session queueing they would all line up
    behind each other."""
    from agno.run.base import RunStatus

    env = ws_env
    env.workflow.session_id = "fixed-on-the-workflow"
    await env.router.handle_workflow_via_websocket(env.ws, {"workflow_id": "wf1", "message": "one"}, env.os)
    await env.router.handle_workflow_via_websocket(env.ws, {"workflow_id": "wf1", "message": "two"}, env.os)
    try:
        acks = _queued_acks(env)
        assert len(acks) == 2
        sessions = {ack["session_id"] for ack in acks}
        assert "fixed-on-the-workflow" not in sessions, "the workflow's own session_id is not a default for clients"
        assert len(sessions) == 2, "each submission without a session_id gets its own session, as over HTTP"
    finally:
        for ack in _queued_acks(env):
            await env.stream.complete_run(ack["run_id"], RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)
