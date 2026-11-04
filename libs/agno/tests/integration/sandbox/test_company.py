"""Company Tasks through Docker, Redis, PostgreSQL and all four Company SQL adapters."""

import asyncio
import json
import os
import subprocess
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from agno.agent import Agent
from agno.company.execution import _call
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.job_queue import QueueConfig
from agno.job_queue.config import RedisCoordination
from agno.os import AgentOS, CompanyConfig
from agno.sandbox import Repository
from agno.sandbox.checkpoint import CheckpointRef, FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent

URL = os.environ.get("AGNO_TEST_SANDBOX_DB_URL")
IMAGE = os.environ.get("AGNO_TEST_RUNTIME_IMAGE")
REDIS = os.environ.get("AGNO_TEST_REDIS_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not URL or not IMAGE or not REDIS, reason="Enable Docker, Postgres and Redis"),
]
REPOSITORY = "https://github.com/octocat/Hello-World"


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def service(request, tmp_path):
    import redis
    import redis.asyncio

    import agno.os.event_streams as streams
    import agno.run.cancel as cancel
    from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager

    old = (
        streams._event_stream,
        streams._event_stream_explicitly_set,
        cancel._cancellation_manager,
        cancel._cancellation_manager_explicitly_set,
    )
    streams._event_stream, streams._event_stream_explicitly_set = None, False
    cancel._cancellation_manager, cancel._cancellation_manager_explicitly_set = InMemoryRunCancellationManager(), False
    schema = "company_sandbox_" + uuid4().hex[:12]
    queue_db = PostgresDb(db_url=URL, db_schema=schema)
    if "postgres" in request.param:
        cls = AsyncPostgresDb if request.param.startswith("async") else PostgresDb
        db = cls(db_url=URL, db_schema=schema)
    else:
        cls = AsyncSqliteDb if request.param.startswith("async") else SqliteDb
        db = cls(db_file=str(tmp_path / "company.db"))
    sync_client, async_client = redis.Redis.from_url(REDIS), redis.asyncio.Redis.from_url(REDIS)
    provider = DockerSandbox(
        IMAGE,
        namespace=schema,
        network="isolated",
        workspace_mb=64,
        checkpoints=FileCheckpointStore(tmp_path / "checkpoints"),
        env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
    )
    agent = FixtureAgent(
        id="engineer", db=queue_db, sandbox=provider, repository=Repository(REPOSITORY, "master"), delay=0.5
    )
    plain = Agent(id="plain", db=queue_db)
    handles = []
    create = provider.acreate

    async def track(*args, **kwargs):
        handle = await create(*args, **kwargs)
        handles.append(handle)
        return handle

    provider.acreate = track
    config = QueueConfig(
        durable=True,
        db=queue_db,
        redis=RedisCoordination(sync_client=sync_client, async_client=async_client, key_prefix=schema),
        poll_interval=0.05,
        max_attempts=1,
        stop_timeout_seconds=1,
    )
    agent_os = AgentOS(
        id=schema, db=queue_db, agents=[agent, plain], company=CompanyConfig(db=db), queue=config, telemetry=False
    )
    app = agent_os.get_app()
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                yield client, db, queue_db, agent, app, handles
    finally:
        for handle in handles:
            await provider.adestroy(handle)
        if isinstance(db, AsyncBaseDb):
            await db.close()
        else:
            db.close()
        with queue_db.db_engine.begin() as conn:
            conn.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
        queue_db.close()
        keys = await async_client.keys(schema + "*")
        if keys:
            await async_client.delete(*keys)
        await async_client.aclose()
        sync_client.close()
        (
            streams._event_stream,
            streams._event_stream_explicitly_set,
            cancel._cancellation_manager,
            cancel._cancellation_manager_explicitly_set,
        ) = old


async def draft(client):
    product = (await client.post("/company/products", json={"name": "Repository"})).json()
    project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Change"})).json()
    approval = {"target": "active", "reason": "Approved"}
    await client.post("/company/projects/" + project["id"] + "/transitions", json=approval)
    response = await client.post(
        "/company/tasks",
        json={
            "product_id": product["id"],
            "project_id": project["id"],
            "title": "Inspect README",
            "brief": "Read README from the repository",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def accept(client, task, executor="engineer"):
    return await client.post(
        "/company/tasks/" + task["id"] + "/transitions",
        json={"target": "ready", "reason": "Reviewed", "executor_type": "agent", "executor_id": executor},
    )


async def source(client, task, reference=REPOSITORY):
    response = await client.post(
        "/company/sources",
        json={"product_id": task["product_id"], "type": "git", "reference": reference, "config": {"branch": "master"}},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def settled(client, task):
    async def wait():
        while True:
            response = await client.get("/company/tasks/" + task["id"])
            value = response.json()
            if value.get("result"):
                return value
            await asyncio.sleep(0.05)

    return await asyncio.wait_for(wait(), 90)


@pytest.mark.live
async def test_checkout_session_reuse_and_concurrent_start(service, tmp_path):
    client, db, run_db, agent, app, handles = service
    task = await draft(client)
    src = await source(client, task)
    accepted = await accept(client, task)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["sandboxed"] is True
    listing = (await client.get("/agents")).json()
    assert {row["id"]: row["sandboxed"] for row in listing} == {"engineer": True, "plain": False}
    other = await draft(client)
    await source(client, other)
    assert (await accept(client, other)).status_code == 200
    path = "/company/tasks/" + task["id"] + "/runs"
    starts = await asyncio.gather(client.post(path), client.post("/company/tasks/" + other["id"] + "/runs"))
    assert sorted(response.status_code for response in starts) == [202, 409], [r.text for r in starts]
    if starts[0].status_code == 409:
        task, other = other, task
        src = (await client.get("/company/sources", params={"product_id": task["product_id"]})).json()["data"][0]
        path = "/company/tasks/" + task["id"] + "/runs"
    blocked = await client.post("/company/tasks/" + other["id"] + "/runs")
    assert blocked.status_code == 409 and "live job" in blocked.text, blocked.text
    first = await settled(client, task)
    assert first["status"] == "in_review", first
    checkout = first["metadata"]["checkout"]
    assert checkout["source_id"] == src["id"] and checkout["url"] == REPOSITORY
    assert checkout["branch"] == "master" and len(checkout["commit"]) == 40
    # Discard compute: attempt two must restore the committed session checkpoint.
    await agent.sandbox.adestroy(handles[-1])
    second = await client.post(path, json={"attempt": 2})
    assert second.status_code == 202, second.text
    final = await settled(client, task)
    assert final["status"] == "in_review", final
    assert final["metadata"]["checkout"] == checkout
    assert final["session_id"] == first["session_id"]
    run = run_db.get_run(final["job_id"], deserialize=False)
    assert run["run_data"]["metadata"]["sandbox"]["repository"] == {
        key: checkout[key] for key in ("url", "branch", "commit")
    }
    assert run["run_data"]["metadata"]["repository"] == {"commit": checkout["commit"]}
    restored = tmp_path / "restored"
    await agent.sandbox.checkpoints.arestore(
        CheckpointRef(**run["run_data"]["metadata"]["sandbox"]["checkpoint"]), restored
    )
    repository = restored / "workspace/repository"
    assert (repository / "README").is_file()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    assert head == checkout["commit"]
    assert json.loads((restored / "native/repository.json").read_text())["commit"] == head
    assert "sandboxed" not in await _call(db, "get_task", task["id"])


async def test_acceptance_and_plain_marker(service, tmp_path):
    client, db, _, agent, _, _ = service
    task = await draft(client)
    missing = await accept(client, task)
    assert missing.status_code == 409 and "Source" in missing.text
    await source(client, task, str(tmp_path))
    assert (await accept(client, task)).status_code == 409
    await source(client, task)
    repository = agent.repository
    agent.repository = None
    missing = await accept(client, task)
    assert missing.status_code == 409 and "repository=" in missing.text
    agent.repository = repository
    response = await accept(client, task, "plain")
    assert response.status_code == 200 and response.json()["sandboxed"] is False
    assert (await client.get("/company/tasks/" + task["id"])).json()["sandboxed"] is False
    assert "sandboxed" not in await _call(db, "get_task", task["id"])


async def test_cancelled_submitter_keeps_admission_until_enqueue_finishes(service, monkeypatch):
    client, _, _, agent, app, _ = service
    first, second = await draft(client), await draft(client)
    await source(client, first)
    await source(client, second)
    assert (await accept(client, first)).status_code == 200
    assert (await accept(client, second)).status_code == 200
    entered, release = asyncio.Event(), asyncio.Event()
    store = app.state.queue_worker.store
    enqueue = store.enqueue_job

    async def delayed(job, **kwargs):
        entered.set()
        await release.wait()
        return await enqueue(job, **kwargs)

    monkeypatch.setattr(store, "enqueue_job", delayed)
    pending = asyncio.create_task(client.post("/company/tasks/" + first["id"] + "/runs"))
    await asyncio.wait_for(entered.wait(), 10)
    pending.cancel()
    await asyncio.sleep(0)
    try:
        refused = await client.post("/company/tasks/" + second["id"] + "/runs")
        assert refused.status_code == 409, refused.text
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    result = await settled(client, first)
    assert result["status"] == "in_review", result
