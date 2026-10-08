"""Real PostgreSQL registry and execution-handoff contract.

Set AGNO_SANDBOX_TEST_DB_URL to a disposable PostgreSQL database. Each test uses
its own schema and drops only that schema on completion.
"""

import asyncio
import inspect
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.schemas.jobs import QueuedJob

DB_URL = os.getenv("AGNO_SANDBOX_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="Set AGNO_SANDBOX_TEST_DB_URL for PostgreSQL sandbox tests")


async def call(db, method, *args, **kwargs):
    fn = getattr(db, method)
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


@pytest_asyncio.fixture(params=[PostgresDb, AsyncPostgresDb], ids=["sync", "async"])
async def db(request):
    schema = "sandbox_test_" + uuid4().hex
    instance = request.param(db_url=DB_URL, db_schema=schema)
    try:
        yield instance
    finally:
        engine = create_engine(DB_URL)
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
        if isinstance(instance, AsyncPostgresDb):
            await instance.db_engine.dispose()
        else:
            instance.db_engine.dispose()


@pytest.mark.asyncio
async def test_registry_races_and_claim_handoff(db):
    row = dict(
        sandbox_id=str(uuid4()),
        session_id="s",
        agent_id="coder",
        user_id="owner",
        provider="docker",
        status="creating",
        generation=1,
        metadata={},
    )
    await call(db, "list_sandboxes")
    results = await asyncio.gather(*[call(db, "upsert_sandbox", {**row, "sandbox_id": str(uuid4())}) for _ in range(8)])
    assert results.count(True) == 1
    current = await call(db, "get_sandbox", session_id="s")
    assert current["db_now"] >= current["created_at"]
    results = await asyncio.gather(*[call(db, "upsert_sandbox", {**current, "status": "ready"}, 1) for _ in range(8)])
    assert results.count(True) == 1
    assert await call(db, "list_sandboxes", user_id="other") == []
    assert not await call(db, "delete_sandbox", current["sandbox_id"], 2)
    current = await call(db, "get_sandbox", session_id="s")
    assert await call(db, "upsert_sandbox", {**current, "status": "destroyed", "user_id": "other"}, 2)
    assert (await call(db, "get_sandbox", session_id="s"))["user_id"] == "owner"
    assert await call(db, "delete_sandbox", current["sandbox_id"], 3)

    queued = QueuedJob(id="run", component_type="agent", component_id="coder", session_id="s").to_dict()
    assert (await call(db, "enqueue_job", queued))["accepted"]
    job = await call(db, "claim_job", "api-a")
    assert await call(db, "handoff_job", "run", "api-a", job["attempt"], "sandbox-1")
    assert not await call(db, "handoff_job", "run", "api-a", job["attempt"], "sandbox-2")
    assert await call(db, "heartbeat_jobs", "api-a", ["run"]) == 0
    assert not await call(db, "complete_job", "run", "api-a", job["attempt"], "failed")
    assert await call(db, "retry_or_fail_job", "run", "api-a", job["attempt"], "shutdown") is None
    assert await call(db, "heartbeat_jobs", "sandbox-1", ["run"]) == 1
    assert (await call(db, "get_job", "run"))["attempt"] == job["attempt"]
    assert await call(db, "complete_job", "run", "sandbox-1", job["attempt"], "completed")
