"""Tests for the background telemetry dispatcher (Api.post_in_background)."""

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agno.api.agent import acreate_agent_run, create_agent_run
from agno.api.api import TELEMETRY_TIMEOUT, Api, api
from agno.api.evals import async_create_eval_run_telemetry, create_eval_run_telemetry
from agno.api.os import log_os_telemetry
from agno.api.routes import ApiRoutes
from agno.api.schemas.agent import AgentRunCreate
from agno.api.schemas.evals import EvalRunCreate
from agno.api.schemas.os import OSLaunch
from agno.api.schemas.team import TeamRunCreate
from agno.api.schemas.workflows import WorkflowRunCreate
from agno.api.team import acreate_team_run, create_team_run
from agno.api.workflow import acreate_workflow_run, create_workflow_run
from agno.db.schemas.evals import EvalType


def wait_for_drain(instance: Api, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while instance._queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not instance._queue.unfinished_tasks, "telemetry queue did not drain in time"


def make_api_with_mock_transport(handler) -> tuple[Api, list[httpx.Client]]:
    """An Api whose clients hit a mock transport, tracking each construction."""
    instance = Api()
    constructed: list[httpx.Client] = []

    def make_client() -> httpx.Client:
        client = httpx.Client(base_url="https://telemetry.test", transport=httpx.MockTransport(handler))
        constructed.append(client)
        return client

    instance._telemetry_client = make_client  # type: ignore[method-assign]
    return instance, constructed


def test_events_are_sent_over_a_single_reused_client():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    instance, constructed = make_api_with_mock_transport(handler)

    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "s1"})
    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "s2"})
    wait_for_drain(instance)

    assert len(requests) == 2
    assert len(constructed) == 1, "every event must reuse the one shared client"
    assert requests[0].url.path == ApiRoutes.RUN_CREATE
    assert b"s1" in requests[0].content and b"s2" in requests[1].content


def test_concurrent_first_use_starts_one_worker_and_delivers_every_event():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    instance, constructed = make_api_with_mock_transport(handler)

    with ThreadPoolExecutor(max_workers=16) as callers:
        futures = [
            callers.submit(instance.post_in_background, ApiRoutes.RUN_CREATE, {"session_id": f"s{i}"})
            for i in range(64)
        ]
        for future in futures:
            future.result()
    wait_for_drain(instance)

    assert len(requests) == 64
    assert len(constructed) == 1
    assert instance._worker is not None and instance._worker.is_alive()


def test_worker_survives_transport_errors_and_bad_statuses():
    calls = {"n": 0}
    delivered: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("https://secret-telemetry.example/internal")
        if calls["n"] == 2:
            return httpx.Response(500)
        delivered.append(request)
        return httpx.Response(200)

    instance, _ = make_api_with_mock_transport(handler)

    with patch("agno.api.api.log_debug") as log:
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "boom"})
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "rejected"})
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "ok"})
        wait_for_drain(instance)

    assert calls["n"] == 3
    assert len(delivered) == 1 and b"ok" in delivered[0].content
    messages = [str(call.args[0]) for call in log.call_args_list]
    assert any("ConnectError" in message for message in messages)
    assert all("secret-telemetry.example" not in message for message in messages)


def test_post_in_background_never_blocks_or_raises_when_queue_is_full():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        return httpx.Response(200)

    instance, _ = make_api_with_mock_transport(handler)
    # Fill the queue without a worker so puts beyond the bound must drop, not block
    instance._ensure_worker = lambda: None  # type: ignore[method-assign]
    for i in range(instance._queue.maxsize + 10):
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"i": i})
    assert instance._queue.qsize() == instance._queue.maxsize


@pytest.mark.parametrize(
    ("helper", "payload", "route"),
    [
        (create_agent_run, AgentRunCreate(session_id="agent-session", run_id="agent-run"), ApiRoutes.RUN_CREATE),
        (create_team_run, TeamRunCreate(session_id="team-session", run_id="team-run"), ApiRoutes.RUN_CREATE),
        (
            create_workflow_run,
            WorkflowRunCreate(session_id="workflow-session", run_id="workflow-run"),
            ApiRoutes.RUN_CREATE,
        ),
        (
            create_eval_run_telemetry,
            EvalRunCreate(run_id="eval-run", eval_type=EvalType.ACCURACY),
            ApiRoutes.EVAL_RUN_CREATE,
        ),
        (log_os_telemetry, OSLaunch(os_id="test-os"), ApiRoutes.AGENT_OS_LAUNCH),
    ],
)
def test_sync_telemetry_helpers_dispatch_in_background(monkeypatch, helper, payload, route):
    enqueued: list[tuple[str, dict]] = []
    monkeypatch.setattr(api, "post_in_background", lambda route, payload: enqueued.append((route, payload)))

    helper(payload)

    assert len(enqueued) == 1
    actual_route, actual_payload = enqueued[0]
    assert actual_route == route
    assert actual_payload == payload.model_dump(exclude_none=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("helper", "payload", "route"),
    [
        (acreate_agent_run, AgentRunCreate(session_id="agent-session", run_id="agent-run"), ApiRoutes.RUN_CREATE),
        (acreate_team_run, TeamRunCreate(session_id="team-session", run_id="team-run"), ApiRoutes.RUN_CREATE),
        (
            acreate_workflow_run,
            WorkflowRunCreate(session_id="workflow-session", run_id="workflow-run"),
            ApiRoutes.RUN_CREATE,
        ),
        (
            async_create_eval_run_telemetry,
            EvalRunCreate(run_id="eval-run", eval_type=EvalType.ACCURACY),
            ApiRoutes.EVAL_RUN_CREATE,
        ),
    ],
)
async def test_async_telemetry_helpers_dispatch_in_background(monkeypatch, helper, payload, route):
    enqueue = AsyncMock()
    monkeypatch.setattr(api, "apost_in_background", enqueue)

    await helper(payload)

    enqueue.assert_awaited_once_with(route, payload.model_dump(exclude_none=True))


def test_async_variant_is_paired_and_delegates():
    import asyncio

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    instance, constructed = make_api_with_mock_transport(handler)
    asyncio.run(instance.apost_in_background(ApiRoutes.RUN_CREATE, {"session_id": "async-1"}))
    wait_for_drain(instance)

    assert len(requests) == 1 and b"async-1" in requests[0].content
    assert len(constructed) == 1


def test_background_client_uses_short_telemetry_timeout():
    instance = Api()

    with patch("agno.api.api.HttpxClient") as client:
        instance._telemetry_client()

    assert client.call_args.kwargs["timeout"] == TELEMETRY_TIMEOUT


def test_changed_pid_is_reset_before_acquiring_inherited_lock():
    instance = Api()
    inherited_lock = instance._lock
    inherited_lock.acquire()
    instance._pid = -1
    completed = threading.Event()

    def ensure_worker() -> None:
        instance._ensure_worker()
        completed.set()

    thread = threading.Thread(target=ensure_worker, daemon=True)
    thread.start()
    try:
        assert completed.wait(1), "pid fallback must not acquire a lock inherited from the parent"
        assert instance._lock is not inherited_lock
        assert instance._pid == os.getpid()
    finally:
        inherited_lock.release()


def test_daemon_worker_does_not_delay_process_exit():
    script = """
import threading
import time

from agno.api.api import Api

started = threading.Event()

class BlockingClient:
    def post(self, route, json):
        started.set()
        time.sleep(30)

instance = Api()
instance._telemetry_client = lambda: BlockingClient()
instance.post_in_background('/telemetry/test', {'run_id': 'run'})
assert started.wait(2)
"""
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[3])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (package_root, env.get("PYTHONPATH"))))

    subprocess.run([sys.executable, "-c", script], check=True, timeout=5, env=env)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork is not available on this platform")
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_forked_child_resets_dispatcher_state():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    instance, constructed = make_api_with_mock_transport(handler)
    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "parent"})
    wait_for_drain(instance)
    assert instance._worker is not None and instance._worker.is_alive()

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # child: prove reset state can deliver through a new worker/client
        try:
            fresh = (
                instance._worker is None
                and instance._client is None
                and instance._queue.qsize() == 0
                and instance._pid == os.getpid()
            )
            instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "child"})
            wait_for_drain(instance)
            delivered = len(requests) == 2 and b"child" in requests[-1].content and len(constructed) == 2
            os.write(write_fd, b"1" if fresh and delivered else b"0")
        finally:
            os._exit(0)
    os.close(write_fd)
    try:
        assert os.read(read_fd, 1) == b"1", "child must reset dispatcher state and deliver through a fresh worker"
    finally:
        os.close(read_fd)
        os.waitpid(pid, 0)
