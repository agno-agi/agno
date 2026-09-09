"""Database cancellation delivery, including two independently spawned servers."""

import asyncio
import json
import multiprocessing
import os
import socket
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from agno.db.postgres import PostgresDb
from agno.exceptions import RunCancelledException
from agno.run.cancellation_management.postgres_cancellation_manager import PostgresRunCancellationManager

pytestmark = pytest.mark.skipif(not os.getenv("AGNO_PAGE_TEST_DB_URL"), reason="requires isolated local PostgreSQL")


@pytest.fixture
def database():
    url = make_url(os.environ["AGNO_PAGE_TEST_DB_URL"])
    assert url.host in ("localhost", "127.0.0.1", "::1")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "cancellation_" + uuid4().hex[:12]
    with admin.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(url.set(database=name))
    try:
        yield PostgresDb(db_engine=engine)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def manager(db, namespace="test", **kwargs):
    result = PostgresRunCancellationManager(db, namespace=namespace, poll_interval=0.05, **kwargs)
    result.setup()
    return result


@pytest.mark.parametrize("asynchronous", [False, True])
def test_intent_registration_and_restart(database, asynchronous):
    first, second = manager(database), manager(database)

    async def check():
        assert not await first.acancel_run("early")
        await second.aregister_run("early")
        with pytest.raises(RunCancelledException):
            await second.araise_if_cancelled("early")
        assert await second.aget_active_runs() == {"early": True}
        await second.acleanup_run("early")
        assert await first.aget_active_runs() == {}

    if asynchronous:
        asyncio.run(check())
    else:
        assert not first.cancel_run("early")
        second.register_run("early")
        with pytest.raises(RunCancelledException):
            second.raise_if_cancelled("early")
        assert second.get_active_runs() == {"early": True}
        second.cleanup_run("early")
        assert first.get_active_runs() == {}
    # A fresh manager reads durable intent without inheriting another process's cache.
    first.cancel_run("restart")
    assert manager(database).is_cancelled("restart")
    assert not manager(database, namespace="other").is_cancelled("restart")


def test_expiry_and_member_tracking(database):
    first, second = manager(database), manager(database)
    first.register_run("old")
    first.cancel_run("old")
    first.register_member_run("team", "old")
    assert second.get_member_run_ids("team") == {"old"}
    with database.db_engine.begin() as conn:
        conn.execute(text("UPDATE public.agno_run_cancellations SET expires_at=now()-interval '1 second'"))
        conn.execute(text("UPDATE public.agno_run_cancellation_members SET expires_at=now()-interval '1 second'"))
    assert second.get_active_runs() == {}
    assert second.get_member_run_ids("team") == set()
    second.register_run("old")
    assert not second.is_cancelled("old")
    asyncio.run(second.aregister_member_run("team", "new"))
    assert asyncio.run(first.aget_member_run_ids("team")) == {"new"}
    asyncio.run(first.acleanup_member_runs("team"))
    assert second.get_member_run_ids("team") == set()


def test_cached_checkpoints_and_remote_intent(database):
    first, second = manager(database), manager(database)
    first.register_run("active")
    queries = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT run_id, cancelled"):
            queries.append(statement)

    event.listen(database.db_engine, "before_cursor_execute", record)
    try:
        assert not first.is_cancelled("active")
        for _ in range(1000):
            assert not first.is_cancelled("active")
        assert len(queries) == 1
        assert second.cancel_run("active")
        time.sleep(0.06)
        assert asyncio.run(first.ais_cancelled("active"))
        assert len(queries) == 2
    finally:
        event.remove(database.db_engine, "before_cursor_execute", record)


def _serve(url, port):
    import uvicorn

    from agno.agent import Agent
    from agno.models.base import Model
    from agno.models.message import MessageMetrics
    from agno.models.response import ModelResponse
    from agno.os import AgentOS
    from agno.os.public import PublicSurface
    from agno.run.cancel import set_cancellation_manager

    class SlowModel(Model):
        def __init__(self):
            super().__init__(id="slow", name="slow", provider="test")

        def invoke(self, *args, **kwargs):
            return ModelResponse(role="assistant", content="Done", response_usage=MessageMetrics())

        async def ainvoke(self, *args, **kwargs):
            return self.invoke(*args, **kwargs)

        def invoke_stream(self, *args, **kwargs):
            for _ in range(200):
                time.sleep(0.05)
                yield ModelResponse(role="assistant", content="Still working ", response_usage=MessageMetrics())

        async def ainvoke_stream(self, *args, **kwargs):
            for _ in range(200):
                await asyncio.sleep(0.05)
                yield ModelResponse(role="assistant", content="Still working ", response_usage=MessageMetrics())

        def _parse_provider_response(self, response, **kwargs):
            return response

        def _parse_provider_response_delta(self, response, **kwargs):
            return response

    db = PostgresDb(db_url=url)
    shared = manager(db)
    set_cancellation_manager(shared)
    agent = Agent(id="slow", db=db, model=SlowModel(), telemetry=False)
    server = AgentOS(
        id="cancel-workers",
        db=db,
        agents=[agent],
        public=PublicSurface(agents=[agent]),
        telemetry=False,
        auto_provision_dbs=False,
    )
    uvicorn.run(server.get_app(), host="127.0.0.1", port=port, log_level="error")


@contextmanager
def worker(url):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = multiprocessing.get_context("spawn").Process(target=_serve, args=(url, port))
    process.start()
    address = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            assert process.is_alive(), "server exited during startup"
            try:
                if httpx.get(address + "/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        else:
            raise AssertionError("server startup timed out")
        yield address
    finally:
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)


def test_stop_from_another_os_process(database):
    url = database.db_engine.url.render_as_string(hide_password=False)
    with worker(url) as first, worker(url) as second, httpx.Client(timeout=15) as client:
        events = []
        with client.stream("POST", first + "/agents/slow/runs", data={"message": "start", "stream": "true"}) as stream:
            assert stream.status_code == 200
            for line in stream.iter_lines():
                if not line.startswith("data: "):
                    continue
                value = json.loads(line[6:])
                events.append(value["event"])
                if value["event"] == "RunStarted":
                    run_id, session_id = value["run_id"], value["session_id"]
                if value["event"] == "RunContent" and events.count("RunContent") == 3:
                    route = second + f"/agents/slow/runs/{run_id}/cancel"
                    wrong = client.post(route, params={"session_id": str(uuid4())})
                    assert wrong.status_code == 404
                    correct = client.post(route, params={"session_id": session_id})
                    assert correct.status_code == 200, correct.text
                    cancelled_at = time.monotonic()
        assert events.count("RunCancelled") == 1, events
        assert events.index("RunCancelled") < events.index("RunCompleted")
        # Agno emits a completion marker after cancellation to close frontend streams.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            session = database.get_session(session_id=session_id, session_type="agent")
            if session and session.runs:
                break
            time.sleep(0.01)
        assert session and session.runs[-1].status == "CANCELLED"
        assert time.monotonic() - cancelled_at < 3
        assert manager(database).get_active_runs() == {}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_cleanup_and_check_failures_preserve_run_outcome(database, monkeypatch, asynchronous):
    shared = manager(database)
    shared.register_run("healthy")

    def unavailable(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(shared.engine, "begin", unavailable)
    if asynchronous:
        assert not asyncio.run(shared.ais_cancelled("healthy"))
        asyncio.run(shared.acleanup_run("healthy"))
        asyncio.run(shared.acleanup_member_runs("team"))
        with pytest.raises(RuntimeError):
            asyncio.run(shared.acancel_run("healthy"))
    else:
        assert not shared.is_cancelled("healthy")
        shared.cleanup_run("healthy")
        shared.cleanup_member_runs("team")
        with pytest.raises(RuntimeError):
            shared.cancel_run("healthy")
    assert shared._local == {}


def test_team_cascade_uses_shared_members(database, monkeypatch):
    import agno.run.cancel as cancellation
    from agno.team import Team

    first, second = manager(database), manager(database)
    first.register_run("team")
    first.register_run("member")
    first.register_member_run("team", "member")
    monkeypatch.setattr(cancellation, "_cancellation_manager", second)
    assert asyncio.run(Team.acancel_run("team"))
    assert first.is_cancelled("team")
    assert first.is_cancelled("member")


def test_registration_and_cancellation_are_atomic(database):
    from concurrent.futures import ThreadPoolExecutor

    first, second = manager(database), manager(database)
    barrier = __import__("threading").Barrier(2)

    def register():
        barrier.wait()
        first.register_run("race")

    def cancel():
        barrier.wait()
        second.cancel_run("race")

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(register), pool.submit(cancel)]
        for future in futures:
            future.result(timeout=5)
    assert manager(database).is_cancelled("race")
