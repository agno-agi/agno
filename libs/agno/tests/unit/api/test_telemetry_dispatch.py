"""Tests for the background telemetry dispatcher (Api.post_in_background)."""

import os
import time

import httpx
import pytest

from agno.api.agent import create_agent_run
from agno.api.api import Api, api
from agno.api.routes import ApiRoutes
from agno.api.schemas.agent import AgentRunCreate


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

    instance.Client = make_client  # type: ignore[method-assign]
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


def test_worker_survives_transport_errors_and_bad_statuses():
    calls = {"n": 0}
    delivered: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("telemetry endpoint down")
        if calls["n"] == 2:
            return httpx.Response(500)
        delivered.append(request)
        return httpx.Response(200)

    instance, _ = make_api_with_mock_transport(handler)

    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "boom"})
    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "rejected"})
    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "ok"})
    wait_for_drain(instance)

    assert calls["n"] == 3
    assert len(delivered) == 1 and b"ok" in delivered[0].content


def test_post_in_background_never_blocks_or_raises_when_queue_is_full():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        return httpx.Response(200)

    instance, _ = make_api_with_mock_transport(handler)
    # Fill the queue without a worker so puts beyond the bound must drop, not block
    instance._ensure_worker = lambda: None  # type: ignore[method-assign]
    for i in range(instance._queue.maxsize + 10):
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"i": i})
    assert instance._queue.qsize() == instance._queue.maxsize


def test_create_agent_run_dispatches_in_background(monkeypatch):
    enqueued = []
    monkeypatch.setattr(api, "post_in_background", lambda route, payload: enqueued.append((route, payload)))

    create_agent_run(AgentRunCreate(session_id="session-1", run_id="run-1"))

    assert len(enqueued) == 1
    route, payload = enqueued[0]
    assert route == ApiRoutes.RUN_CREATE
    assert payload["session_id"] == "session-1" and payload["run_id"] == "run-1"


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


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork is not available on this platform")
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_forked_child_resets_dispatcher_state():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    instance, _ = make_api_with_mock_transport(handler)
    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "parent"})
    wait_for_drain(instance)
    assert instance._worker is not None and instance._worker.is_alive()

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # child: report whether the fork hook gave us fresh state
        try:
            fresh = (
                instance._worker is None
                and instance._client is None
                and instance._queue.qsize() == 0
                and instance._pid == os.getpid()
            )
            os.write(write_fd, b"1" if fresh else b"0")
        finally:
            os._exit(0)
    os.close(write_fd)
    try:
        assert os.read(read_fd, 1) == b"1", "child must see reset dispatcher state"
    finally:
        os.close(read_fd)
        os.waitpid(pid, 0)
