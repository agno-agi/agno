"""Tests for the background telemetry dispatcher (Api.post_in_background)."""

import gc
import json
import os
import subprocess
import sys
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agno.api.agent import acreate_agent_run, create_agent_run
from agno.api.api import (
    TELEMETRY_SHUTDOWN_TIMEOUT,
    TELEMETRY_TIMEOUT,
    Api,
    _create_telemetry_client,
    _TelemetryDispatcher,
    api,
)
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


def wait_for_drain(dispatcher: _TelemetryDispatcher, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while dispatcher._queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not dispatcher._queue.unfinished_tasks, "telemetry queue did not drain in time"


@pytest.fixture
def dispatcher_factory():
    """Build isolated dispatchers and always stop their workers after a test."""
    dispatchers: list[_TelemetryDispatcher] = []

    def make(handler, *, register_at_fork: bool = False) -> tuple[_TelemetryDispatcher, list[httpx.Client]]:
        constructed: list[httpx.Client] = []

        def make_client() -> httpx.Client:
            client = httpx.Client(base_url="https://telemetry.test", transport=httpx.MockTransport(handler))
            constructed.append(client)
            return client

        dispatcher = _TelemetryDispatcher(make_client, register_at_fork=register_at_fork)
        dispatchers.append(dispatcher)
        return dispatcher, constructed

    yield make

    for dispatcher in reversed(dispatchers):
        dispatcher.close(flush_timeout=0.5)


def test_events_are_sent_over_a_single_reused_client(dispatcher_factory):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    dispatcher, constructed = dispatcher_factory(handler)
    instance = Api(dispatcher)

    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "s1"})
    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "s2"})
    wait_for_drain(dispatcher)

    assert len(requests) == 2
    assert len(constructed) == 1, "every event must reuse the one shared client"
    assert requests[0].url.path == ApiRoutes.RUN_CREATE
    assert b"s1" in requests[0].content and b"s2" in requests[1].content


def test_concurrent_first_use_starts_one_worker_and_delivers_every_event(dispatcher_factory):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    dispatcher, constructed = dispatcher_factory(handler)
    instance = Api(dispatcher)

    with ThreadPoolExecutor(max_workers=16) as callers:
        futures = [
            callers.submit(instance.post_in_background, ApiRoutes.RUN_CREATE, {"session_id": f"s{i}"})
            for i in range(64)
        ]
        for future in futures:
            future.result()
    wait_for_drain(dispatcher)

    assert len(requests) == 64
    assert len(constructed) == 1
    assert dispatcher._worker is not None and dispatcher._worker.is_alive()


def test_worker_survives_transport_errors_and_bad_statuses(dispatcher_factory):
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

    dispatcher, _ = dispatcher_factory(handler)
    instance = Api(dispatcher)

    with patch("agno.api.api.log_debug") as log:
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "boom"})
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "rejected"})
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "ok"})
        wait_for_drain(dispatcher)

    assert calls["n"] == 3
    assert len(delivered) == 1 and b"ok" in delivered[0].content
    messages = [str(call.args[0]) for call in log.call_args_list]
    assert any("ConnectError" in message for message in messages)
    assert all("secret-telemetry.example" not in message for message in messages)


def test_post_in_background_never_blocks_or_raises_when_queue_is_full():
    started = threading.Event()
    release = threading.Event()
    delivered: list[int] = []

    class BlockingClient:
        def post(self, route, json):
            delivered.append(json["i"])
            if json["i"] == 1:
                started.set()
                release.wait(2)

            class Response:
                status_code = 200

            return Response()

        def close(self):
            pass

    dispatcher = _TelemetryDispatcher(lambda: BlockingClient(), register_at_fork=False)
    dispatcher._queue = Queue(maxsize=1)
    instance = Api(dispatcher)
    try:
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"i": 1})
        assert started.wait(1)
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"i": 2})

        start = time.monotonic()
        instance.post_in_background(ApiRoutes.RUN_CREATE, {"i": 3})
        assert time.monotonic() - start < 0.1
        assert dispatcher._queue.qsize() == 1
    finally:
        release.set()
        wait_for_drain(dispatcher)
        dispatcher.close(flush_timeout=0.5)

    assert delivered == [1, 2]


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


def test_async_variant_is_paired_and_delegates(dispatcher_factory):
    import asyncio

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    dispatcher, constructed = dispatcher_factory(handler)
    instance = Api(dispatcher)
    asyncio.run(instance.apost_in_background(ApiRoutes.RUN_CREATE, {"session_id": "async-1"}))
    wait_for_drain(dispatcher)

    assert len(requests) == 1 and b"async-1" in requests[0].content
    assert len(constructed) == 1


def test_background_client_uses_short_telemetry_timeout():
    with patch("agno.api.api.HttpxClient") as client:
        _create_telemetry_client()

    assert client.call_args.kwargs["timeout"] == TELEMETRY_TIMEOUT


def test_changed_pid_is_reset_before_acquiring_inherited_lock(dispatcher_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    dispatcher, _ = dispatcher_factory(handler)
    inherited_lock = dispatcher._lock
    inherited_lock.acquire()
    dispatcher._pid = -1
    completed = threading.Event()

    def post() -> None:
        dispatcher.post(ApiRoutes.RUN_CREATE, {"run_id": "child"})
        completed.set()

    thread = threading.Thread(target=post, daemon=True)
    thread.start()
    try:
        assert completed.wait(1), "pid fallback must not acquire a lock inherited from the parent"
        assert dispatcher._lock is not inherited_lock
        assert dispatcher._pid == os.getpid()
        wait_for_drain(dispatcher)
    finally:
        inherited_lock.release()


def test_changed_pid_is_reset_before_acquiring_inherited_close_lock(dispatcher_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    dispatcher, _ = dispatcher_factory(handler)
    inherited_close_lock = dispatcher._close_lock
    inherited_close_lock.acquire()
    dispatcher._pid = -1
    completed = threading.Event()

    def close() -> None:
        dispatcher.close(flush_timeout=0.1)
        completed.set()

    thread = threading.Thread(target=close, daemon=True)
    thread.start()
    try:
        assert completed.wait(1), "pid fallback must run before acquiring a close lock inherited from the parent"
        assert dispatcher._close_lock is not inherited_close_lock
        assert dispatcher._pid == os.getpid()
    finally:
        inherited_close_lock.release()


def test_api_wrappers_share_dispatcher_without_retaining_instances(dispatcher_factory):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    dispatcher, constructed = dispatcher_factory(handler)
    baseline_threads = set(threading.enumerate())
    references: list[weakref.ReferenceType[Api]] = []

    def dispatch_from_temporary_wrappers() -> None:
        for i in range(25):
            wrapper = Api(dispatcher)
            references.append(weakref.ref(wrapper))
            wrapper.post_in_background(ApiRoutes.RUN_CREATE, {"i": i})

    dispatch_from_temporary_wrappers()
    wait_for_drain(dispatcher)
    gc.collect()

    assert all(reference() is None for reference in references)
    assert len(requests) == 25
    assert len(constructed) == 1
    worker = dispatcher._worker
    assert worker is not None and worker.is_alive()
    assert [thread for thread in threading.enumerate() if thread not in baseline_threads and thread.is_alive()] == [
        worker
    ]

    dispatcher.close(flush_timeout=1)

    assert not worker.is_alive()
    assert dispatcher._worker is None
    assert dispatcher._client is None
    assert constructed[0].is_closed


def test_default_api_wrappers_share_the_process_dispatcher():
    assert Api()._dispatcher is api._dispatcher
    assert Api()._dispatcher is Api()._dispatcher


def test_close_is_idempotent_and_rejects_later_posts(dispatcher_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    dispatcher, constructed = dispatcher_factory(handler)

    dispatcher.close(flush_timeout=0.1)
    dispatcher.close(flush_timeout=0.1)
    dispatcher.post(ApiRoutes.RUN_CREATE, {"run_id": "too-late"})

    assert dispatcher._worker is None
    assert dispatcher._queue.unfinished_tasks == 0
    assert constructed == []


def test_worker_start_failure_is_retried_without_losing_queued_event(dispatcher_factory):
    delivered: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        delivered.append(json.loads(request.content)["i"])
        return httpx.Response(200)

    dispatcher, _ = dispatcher_factory(handler)
    original_start = threading.Thread.start
    starts = 0

    def fail_once(worker: threading.Thread) -> None:
        nonlocal starts
        if worker.name == "agno-telemetry":
            starts += 1
            if starts == 1:
                raise RuntimeError("synthetic start failure")
        original_start(worker)

    with patch.object(threading.Thread, "start", fail_once):
        dispatcher.post(ApiRoutes.RUN_CREATE, {"i": 1})
        assert dispatcher._worker is None
        dispatcher.post(ApiRoutes.RUN_CREATE, {"i": 2})
        wait_for_drain(dispatcher)

    assert delivered == [1, 2]
    assert starts == 2


def test_full_queue_retries_a_worker_stranded_by_start_failures(dispatcher_factory):
    delivered: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        delivered.append(json.loads(request.content)["i"])
        return httpx.Response(200)

    dispatcher, _ = dispatcher_factory(handler)
    dispatcher._queue = Queue(maxsize=2)
    original_start = threading.Thread.start
    starts = 0

    def fail_twice(worker: threading.Thread) -> None:
        nonlocal starts
        if worker.name == "agno-telemetry":
            starts += 1
            if starts <= 2:
                raise RuntimeError("synthetic start failure")
        original_start(worker)

    with patch.object(threading.Thread, "start", fail_twice):
        dispatcher.post(ApiRoutes.RUN_CREATE, {"i": 1})
        dispatcher.post(ApiRoutes.RUN_CREATE, {"i": 2})
        assert dispatcher._queue.full()
        dispatcher.post(ApiRoutes.RUN_CREATE, {"i": 3})
        wait_for_drain(dispatcher)

    assert delivered == [1, 2]
    assert starts == 3


def test_dead_worker_is_replaced_and_pending_events_are_delivered(dispatcher_factory):
    delivered: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        delivered.append(json.loads(request.content)["i"])
        return httpx.Response(200)

    dispatcher, _ = dispatcher_factory(handler)
    original_drain = dispatcher._drain
    first_worker_exited = threading.Event()

    def exit_once(queue: Queue[object]) -> None:
        dispatcher._drain = original_drain
        first_worker_exited.set()

    dispatcher._drain = exit_once
    dispatcher.post(ApiRoutes.RUN_CREATE, {"i": 1})
    assert first_worker_exited.wait(1)
    assert dispatcher._worker is not None
    dispatcher._worker.join(1)
    assert not dispatcher._worker.is_alive()

    dispatcher.post(ApiRoutes.RUN_CREATE, {"i": 2})
    wait_for_drain(dispatcher)

    assert delivered == [1, 2]


def test_close_discards_a_full_queue_within_its_deadline():
    started = threading.Event()
    release = threading.Event()
    delivered: list[int] = []
    closed = threading.Event()

    class BlockingClient:
        def post(self, route, json):
            delivered.append(json["i"])
            started.set()
            release.wait(2)

            class Response:
                status_code = 200

            return Response()

        def close(self):
            closed.set()

    dispatcher = _TelemetryDispatcher(lambda: BlockingClient(), register_at_fork=False)
    dispatcher._queue = Queue(maxsize=1)
    try:
        dispatcher.post(ApiRoutes.RUN_CREATE, {"i": 1})
        assert started.wait(1)
        dispatcher.post(ApiRoutes.RUN_CREATE, {"i": 2})

        start = time.monotonic()
        dispatcher.close(flush_timeout=0.05)
        assert time.monotonic() - start < 0.5
        assert delivered == [1]

        release.set()
        worker = dispatcher._worker
        assert worker is not None
        worker.join(1)
        assert not worker.is_alive()
        assert dispatcher._queue.unfinished_tasks == 0
        assert closed.is_set()
    finally:
        release.set()
        dispatcher.close(flush_timeout=0.5)


def test_post_racing_close_is_either_flushed_or_rejected(dispatcher_factory):
    delivered: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        delivered.append(json.loads(request.content)["run_id"])
        return httpx.Response(200)

    dispatcher, _ = dispatcher_factory(handler)
    original_put = dispatcher._queue.put_nowait
    insertion_started = threading.Event()
    allow_insertion = threading.Event()

    def paused_put(item: object) -> None:
        insertion_started.set()
        assert allow_insertion.wait(1)
        original_put(item)

    with patch.object(dispatcher._queue, "put_nowait", paused_put):
        poster = threading.Thread(
            target=dispatcher.post,
            args=(ApiRoutes.RUN_CREATE, {"run_id": "accepted"}),
        )
        poster.start()
        assert insertion_started.wait(1)

        closer = threading.Thread(target=dispatcher.close, kwargs={"flush_timeout": 1})
        closer.start()
        allow_insertion.set()
        poster.join(1)
        closer.join(2)

    assert not poster.is_alive()
    assert not closer.is_alive()
    assert delivered == ["accepted"]

    dispatcher.post(ApiRoutes.RUN_CREATE, {"run_id": "rejected"})
    assert delivered == ["accepted"]


def test_concurrent_close_call_respects_its_own_timeout():
    started = threading.Event()
    release = threading.Event()

    class BlockingClient:
        def post(self, route, json):
            started.set()
            release.wait(2)

            class Response:
                status_code = 200

            return Response()

        def close(self):
            pass

    dispatcher = _TelemetryDispatcher(lambda: BlockingClient(), register_at_fork=False)
    try:
        dispatcher.post(ApiRoutes.RUN_CREATE, {"run_id": "blocked"})
        assert started.wait(1)
        long_close = threading.Thread(target=dispatcher.close, kwargs={"flush_timeout": 1})
        long_close.start()
        deadline = time.monotonic() + 1
        while not dispatcher._close_lock.locked() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert dispatcher._close_lock.locked()

        start = time.monotonic()
        dispatcher.close(flush_timeout=0.05)
        assert time.monotonic() - start < 0.5

        release.set()
        long_close.join(2)
        assert not long_close.is_alive()
    finally:
        release.set()
        dispatcher.close(flush_timeout=0.5)


def test_worker_callback_can_close_without_waiting_on_itself():
    request_started = threading.Event()
    allow_callback_close = threading.Event()
    close_elapsed: list[float] = []
    dispatcher: _TelemetryDispatcher

    class ClosingClient:
        def post(self, route, json):
            request_started.set()
            assert allow_callback_close.wait(1)
            start = time.monotonic()
            dispatcher.close(flush_timeout=1)
            close_elapsed.append(time.monotonic() - start)

            class Response:
                status_code = 200

            return Response()

        def close(self):
            pass

    dispatcher = _TelemetryDispatcher(lambda: ClosingClient(), register_at_fork=False)
    dispatcher.post(ApiRoutes.RUN_CREATE, {"run_id": "self-close"})
    assert request_started.wait(1)

    external_close = threading.Thread(target=dispatcher.close, kwargs={"flush_timeout": 1})
    external_close.start()
    deadline = time.monotonic() + 1
    while not dispatcher._close_lock.locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert dispatcher._close_lock.locked()
    allow_callback_close.set()

    deadline = time.monotonic() + 2
    while dispatcher._worker is not None and time.monotonic() < deadline:
        time.sleep(0.01)

    external_close.join(1)
    assert not external_close.is_alive()
    assert close_elapsed and close_elapsed[0] < 0.5
    assert dispatcher._queue.unfinished_tasks == 0


def test_concurrent_pid_fallback_resets_once_and_starts_one_worker():
    script = """
import threading
import time

from agno.api.api import _TelemetryDispatcher

delivered = []
constructed = []

class Client:
    def __init__(self):
        constructed.append(self)

    def post(self, route, json):
        delivered.append(json['i'])
        class Response:
            status_code = 200
        return Response()

    def close(self):
        pass

dispatcher = _TelemetryDispatcher(Client, register_at_fork=False)
dispatcher._pid = -1
original_reset = dispatcher._reset_after_fork
reset_count = [0]
reset_count_lock = threading.Lock()

def slow_reset(*, replace_fallback_lock=True):
    with reset_count_lock:
        reset_count[0] += 1
    time.sleep(0.05)
    original_reset(replace_fallback_lock=replace_fallback_lock)

dispatcher._reset_after_fork = slow_reset
barrier = threading.Barrier(16)

def post(index):
    barrier.wait()
    dispatcher.post('/telemetry/test', {'i': index})

threads = [threading.Thread(target=post, args=(index,)) for index in range(16)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(2)
assert all(not thread.is_alive() for thread in threads)

deadline = time.monotonic() + 2
while dispatcher._queue.unfinished_tasks and time.monotonic() < deadline:
    time.sleep(0.01)

assert reset_count[0] == 1, reset_count
assert len(delivered) == 16, delivered
assert len(constructed) == 1, constructed
assert sum(t.name == 'agno-telemetry' and t.is_alive() for t in threading.enumerate()) == 1
dispatcher.close(0.5)
"""
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[3])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (package_root, env.get("PYTHONPATH"))))

    subprocess.run([sys.executable, "-c", script], check=True, timeout=8, env=env)


def test_atexit_flush_delivers_one_shot_event_and_closes_client():
    script = """
import os
import time

from agno.api.api import api

class Client:
    def post(self, route, json):
        time.sleep(0.25)
        os.write(1, b'D')
        class Response:
            status_code = 200
        return Response()

    def close(self):
        os.write(1, b'C')

api._dispatcher._client_factory = Client
api.post_in_background('/telemetry/test', {'run_id': 'run'})
"""
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[3])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (package_root, env.get("PYTHONPATH"))))

    result = subprocess.run([sys.executable, "-c", script], check=True, timeout=5, env=env, capture_output=True)

    assert b"DC" in result.stdout


def test_blocked_worker_respects_bounded_atexit_flush():
    script = """
import threading
import time

from agno.api.api import api

started = threading.Event()

class BlockingClient:
    def post(self, route, json):
        started.set()
        time.sleep(30)

    def close(self):
        pass

api._dispatcher._client_factory = BlockingClient
api.post_in_background('/telemetry/test', {'run_id': 'run'})
assert started.wait(2)
"""
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[3])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (package_root, env.get("PYTHONPATH"))))

    start = time.monotonic()
    subprocess.run([sys.executable, "-c", script], check=True, timeout=6, env=env)
    elapsed = time.monotonic() - start

    assert 1.5 <= elapsed < TELEMETRY_SHUTDOWN_TIMEOUT + 2


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork is not available on this platform")
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_forked_child_resets_dispatcher_state(dispatcher_factory):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    dispatcher, constructed = dispatcher_factory(handler, register_at_fork=True)
    instance = Api(dispatcher)
    instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "parent"})
    wait_for_drain(dispatcher)
    assert dispatcher._worker is not None and dispatcher._worker.is_alive()

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # child: prove reset state can deliver through a new worker/client
        try:
            fresh = (
                dispatcher._worker is None
                and dispatcher._client is None
                and dispatcher._queue.qsize() == 0
                and dispatcher._pid == os.getpid()
            )
            instance.post_in_background(ApiRoutes.RUN_CREATE, {"session_id": "child"})
            wait_for_drain(dispatcher)
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
