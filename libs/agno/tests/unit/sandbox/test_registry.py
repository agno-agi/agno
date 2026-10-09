import inspect
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb


async def call(db, method, *args, **kwargs):
    result = getattr(db, method)(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def record(session_id="session", user_id="owner"):
    return dict(
        sandbox_id=str(uuid4()),
        session_id=session_id,
        agent_id="coder",
        user_id=user_id,
        provider="docker",
        provider_ref=None,
        url=None,
        generation=1,
        status="creating",
        metadata={},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("async_db", [False, True])
async def test_registry_cas_identity_and_delete(tmp_path, async_db):
    cls = AsyncSqliteDb if async_db else SqliteDb
    db = cls(db_file=str(tmp_path / "registry.db"))
    initial = record()
    assert await call(db, "upsert_sandbox", initial)
    assert not await call(db, "upsert_sandbox", record())
    row = await call(db, "get_sandbox", session_id="session")
    assert row["revision"] == 1
    assert row["db_now"] >= row["created_at"]
    assert row["metadata"] == {}
    assert await call(db, "upsert_sandbox", {**row, "status": "ready", "user_id": "intruder"}, 1)
    assert not await call(db, "upsert_sandbox", {**row, "status": "error"}, 1)
    row = await call(db, "get_sandbox", sandbox_id=initial["sandbox_id"])
    assert row["status"] == "ready" and row["user_id"] == "owner"
    assert not await call(db, "delete_sandbox", row["sandbox_id"], 2)
    assert await call(db, "list_sandboxes", user_id="intruder") == []
    assert len(await call(db, "list_sandboxes", agent_id="coder", user_id="owner")) == 1
    assert await call(db, "upsert_sandbox", {**row, "status": "destroyed"}, 2)
    assert not await call(db, "delete_sandbox", row["sandbox_id"], 2)
    assert await call(db, "delete_sandbox", row["sandbox_id"], 3)
    assert await call(db, "get_sandbox", session_id="session") is None
    if async_db:
        await db.db_engine.dispose()
    else:
        db.db_engine.dispose()


def test_two_replicas_claim_one_binding(tmp_path):
    path = str(tmp_path / "registry.db")
    a, b = SqliteDb(db_file=path), SqliteDb(db_file=path)
    # Provision before racing writes, as deployment startup does.
    a.list_sandboxes()
    b.list_sandboxes()
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(db.upsert_sandbox, record()) for db in (a, b)]
        assert sorted(f.result() for f in futures) == [False, True]
    original = a.get_sandbox(session_id="session")
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(db.upsert_sandbox, {**original, "status": state}, 1)
            for db, state in ((a, "ready"), (b, "error"))
        ]
        assert sorted(f.result() for f in futures) == [False, True]
    a.db_engine.dispose()
    b.db_engine.dispose()
