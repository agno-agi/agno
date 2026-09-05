"""Composed public HTTP routes with two apps sharing real PostgreSQL quotas."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS
from agno.os.public import PublicSurface, RateLimit
from agno.workflow import Step, StepInput, StepOutput, Workflow

pytestmark = pytest.mark.skipif(not os.getenv("AGNO_PAGE_TEST_DB_URL"), reason="requires isolated local PostgreSQL")


@pytest.fixture(scope="module")
def engine():
    url = make_url(os.environ["AGNO_PAGE_TEST_DB_URL"])
    assert url.host in ("localhost", "127.0.0.1", "::1")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "agno_public_" + uuid4().hex[:12]
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    target = create_engine(url.set(database=name), connect_args={"connect_timeout": 3})
    try:
        yield target
    finally:
        target.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


class SyncInput(BaseModel):
    reason: str


def sync_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content={"success": True, "input": str(step_input.input)})


def application(engine, namespace, *, limit=100):
    db = PostgresDb(db_engine=engine)
    visible, hidden = Agent(id="docs-agent", name="Docs", instructions="private prompt"), Agent(id="hidden")
    workflow = Workflow(
        id="sync-docs", name="Sync", input_schema=SyncInput, db=db, steps=[Step(name="sync", executor=sync_step)]
    )
    public = PublicSurface(
        agents=[visible], workflows=[workflow], namespace=namespace, limits={"run": RateLimit(limit, limit)}
    )
    agent_os = AgentOS(
        id="test-public",
        db=db,
        agents=[visible, hidden],
        workflows=[workflow],
        public=public,
        internal_service_token="shared-internal-token",
        telemetry=False,
        auto_provision_dbs=False,
        cors_allowed_origins=["https://docs.example.com"],
    )
    return agent_os.get_app(), public


def test_two_apps_share_atomic_admission_and_reject_overrides(engine):
    namespace = "test-" + uuid4().hex[:8]
    first, p1 = application(engine, namespace, limit=5)
    second, p2 = application(engine, namespace, limit=5)
    with TestClient(first) as a, TestClient(second) as b:
        assert a.get("/agents").json() == [{"id": "docs-agent", "name": "Docs", "description": ""}]
        assert a.get("/agents/hidden").status_code == 404
        assert a.get("/config").status_code == 404
        assert a.get("/readyz").status_code == 200
        # Malformed admitted requests still consume the shared allowance.
        clients = [a, b]

        def attempt(index):
            return (
                clients[index % 2]
                .post("/agents/docs-agent/runs", data={"message": "hello", "user_id": "spoof"})
                .status_code
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(attempt, range(10)))
        assert statuses.count(400) == 5 and statuses.count(429) == 5
        assert p1.limiter.consume("cancel", client_id="testclient").allowed
        assert p2.limiter.consume("cancel", client_id="testclient").allowed
        response = a.post(
            "/agents/docs-agent/runs", data={"message": "hello"}, headers={"Origin": "https://docs.example.com"}
        )
        assert response.status_code == 429
        assert response.headers["access-control-allow-origin"] == "https://docs.example.com"
        assert int(response.headers["retry-after"]) > 0


def test_workflow_authentication_while_chat_is_anonymous(engine):
    app, _ = application(engine, "test-" + uuid4().hex[:8])
    with TestClient(app) as client:
        payload = {"message": '{"reason":"test"}', "stream": "false"}
        assert client.post("/workflows/sync-docs/runs", data=payload).status_code == 401
        for bearer in ("unknown", "agno_pat_unknown"):
            assert (
                client.post(
                    "/workflows/sync-docs/runs", data=payload, headers={"Authorization": "Bearer " + bearer}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/workflows/sync-docs/runs",
                data=payload,
                headers=[("Authorization", "Bearer shared-internal-token"), ("Authorization", "Bearer invalid")],
            ).status_code
            == 401
        )
        # Internal execution accepts scheduler fields; arbitrary bearer presence does not.
        response = client.post(
            "/workflows/sync-docs/runs",
            data={**payload, "user_id": "schedule-owner"},
            headers={"Authorization": "Bearer shared-internal-token"},
        )
        assert response.status_code == 200, response.text
        run = response.json()
        status = client.get(
            f"/workflows/sync-docs/runs/{run['run_id']}",
            params={"session_id": run["session_id"]},
            headers={"Authorization": "Bearer shared-internal-token"},
        )
        assert status.status_code == 200, status.text
        assert (
            client.post(
                "/agents/docs-agent/runs",
                data={"message": "hi", "user_id": "spoof"},
                headers={"Authorization": "Bearer unknown"},
            ).status_code
            == 400
        )


def test_scoped_service_credentials_and_native_mcp(engine):
    import time

    from agno.db.schemas.service_accounts import ServiceAccount
    from agno.os import MCPConfig
    from agno.os.public import get_public_client_id
    from agno.os.service_accounts import generate_token

    db = PostgresDb(db_engine=engine)
    workflow = Workflow(
        id="scoped-sync",
        name="Scoped sync",
        input_schema=SyncInput,
        db=db,
        steps=[Step(name="sync", executor=sync_step)],
    )

    def identity_echo() -> str:
        return get_public_client_id()

    public = PublicSurface(
        workflows=[workflow],
        mcp=True,
        namespace="scoped-" + uuid4().hex[:8],
        client_id=lambda request: "resolved-client",
    )
    server = AgentOS(
        id="scoped",
        db=db,
        workflows=[workflow],
        public=public,
        internal_service_token="internal-scoped-test",
        telemetry=False,
        auto_provision_dbs=False,
        mcp=MCPConfig(tools=[identity_echo], default_tools=False, lifecycle_tools=False, stateless=True),
    )
    with TestClient(server.get_app(), base_url="http://localhost") as client:

        def mint(scopes, **kwargs):
            token, digest, prefix = generate_token()
            db.create_service_account(
                ServiceAccount(
                    id=str(uuid4()),
                    name="test-" + uuid4().hex[:8],
                    token_hash=digest,
                    token_prefix=prefix,
                    scopes=scopes,
                    created_at=int(time.time()),
                    **kwargs,
                ).to_dict()
            )
            return {"Authorization": "Bearer " + token}

        both = mint(["workflows:scoped-sync:run", "workflows:scoped-sync:read"])
        payload = {"message": '{"reason":"scope regression"}', "stream": "false"}
        route = "/workflows/scoped-sync/runs"
        response = client.post(route, data=payload, headers=both)
        assert response.status_code == 200, response.text
        run = response.json()
        poll = route + "/" + run["run_id"]
        assert client.get(poll, params={"session_id": run["session_id"]}, headers=both).status_code == 200
        assert client.get(poll, params={"session_id": str(uuid4())}, headers=both).status_code == 404
        for scopes in (["agents:scoped-sync:run"], ["workflows:another:run"], ["workflows:scoped-sync:read"]):
            assert client.post(route, data=payload, headers=mint(scopes)).status_code == 403
        for expiration in ({"expires_at": int(time.time()) - 1}, {"revoked_at": int(time.time()) - 1}):
            assert client.post(route, data=payload, headers=mint(["workflows:run"], **expiration)).status_code == 401
        assert client.post(route, data={**payload, "user_id": "spoofed"}, headers=both).status_code == 400
        assert (
            client.post(
                route,
                data={**payload, "user_id": "scheduler-owner"},
                headers={"Authorization": "Bearer internal-scoped-test"},
            ).status_code
            == 200
        )
        headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
        result = client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        assert result.status_code == 200 and "identity_echo" in result.text
        assert "run_workflow" not in result.text
        for ident in (2, 3):
            result = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": ident,
                    "method": "tools/call",
                    "params": {"name": "identity_echo", "arguments": {}},
                },
            )
            assert result.status_code == 200 and "resolved-client" in result.text
    public.limiter.engine.dispose()


def test_actual_scheduler_executes_and_polls_a_prefixed_public_server(engine):
    import asyncio
    import socket
    import threading
    import time

    import uvicorn
    from fastapi import FastAPI

    from agno.db.schemas.scheduler import Schedule
    from agno.scheduler.executor import ScheduleExecutor

    db = PostgresDb(db_engine=engine)
    workflow = Workflow(
        id="scheduled-sync",
        name="Scheduled sync",
        input_schema=SyncInput,
        db=db,
        steps=[Step(name="sync", executor=sync_step)],
    )
    namespace = "scheduler-" + uuid4().hex[:8]
    public = PublicSurface(workflows=[workflow], namespace=namespace)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    base = "http://127.0.0.1:" + str(sock.getsockname()[1]) + "/prefix"
    receiver = AgentOS(
        id="receiver",
        url=base,
        db=db,
        workflows=[workflow],
        public=public,
        internal_service_token="shared-scheduler-token",
        telemetry=False,
        auto_provision_dbs=False,
    )
    sender = AgentOS(
        id="sender",
        url=base,
        db=db,
        workflows=[workflow],
        internal_service_token="shared-scheduler-token",
        telemetry=False,
        auto_provision_dbs=False,
    )
    app = receiver.get_app()
    mounted = FastAPI(lifespan=app.router.lifespan_context)
    mounted.mount("/prefix", app)
    server = uvicorn.Server(uvicorn.Config(mounted, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        schedule = Schedule(
            id=str(uuid4()),
            name="test-scheduled-sync",
            cron_expr="0 * * * *",
            endpoint="/workflows/scheduled-sync/runs",
            user_id="schedule-owner",
            timeout_seconds=10,
            payload={"message": {"reason": "scheduled"}, "user_id": "spoofed", "metadata": {"origin": "test"}},
        )
        db.create_schedule(schedule.to_dict())

        async def execute():
            executor = ScheduleExecutor(
                sender._scheduler_base_url, sender._internal_service_token, poll_interval=0.1, timeout=10
            )
            try:
                return await executor.execute(schedule, db, release_schedule=False)
            finally:
                await executor.close()

        result = asyncio.run(execute())
        assert result["status"] == "success", result
        run = workflow.get_run_output(run_id=result["run_id"], session_id=result["session_id"])
        assert run.user_id == "schedule-owner"
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM public.agno_public_limits WHERE key LIKE :prefix"),
                    {"prefix": namespace + ":%"},
                ).scalar_one()
                == 0
            )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        public.limiter.engine.dispose()
