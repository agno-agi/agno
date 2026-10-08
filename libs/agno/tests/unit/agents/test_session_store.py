"""Transcript persistence and bound-project behavior with real database adapters."""

from uuid import uuid4

import pytest

from agno.agents.claude.session_store import AgnoSessionStore
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb


@pytest.fixture(params=[False, True], ids=["sqlite", "async-sqlite"])
def db_factory(request, tmp_path):
    def make():
        cls = AsyncSqliteDb if request.param else SqliteDb
        return cls(db_file=str(tmp_path / (str(uuid4()) + ".db")))

    return make


@pytest.mark.asyncio
async def test_sdk_conformance(db_factory):
    from claude_agent_sdk.testing import run_session_store_conformance

    class ProjectStores:
        # The SDK suite routes arbitrary project keys. Production stores bind
        # one project, so dispatch to one bound store per project for this suite.
        def __init__(self):
            self.db = db_factory()
            self.stores = {}

        def store(self, project):
            return self.stores.setdefault(project, AgnoSessionStore(self.db, project))

        async def append(self, key, entries):
            await self.store(key["project_key"]).append(key, entries)

        async def load(self, key):
            return await self.store(key["project_key"]).load(key)

        async def list_sessions(self, project):
            return await self.store(project).list_sessions(project)

        async def list_subkeys(self, key):
            return await self.store(key["project_key"]).list_subkeys(key)

        async def delete(self, key):
            await self.store(key["project_key"]).delete(key)

    await run_session_store_conformance(ProjectStores)


@pytest.mark.asyncio
async def test_bound_key_retry_and_cascade(db_factory):
    db = db_factory()
    store = AgnoSessionStore(db, "tenant")
    old = {"project_key": "old-cwd", "session_id": "session"}
    new = {**old, "project_key": "new-cwd"}
    entries = [{"uuid": "id", "type": "user", "opaque": {"a": [1, None, False]}}]
    await store.append(old, entries)
    await store.append(new, entries)
    assert await store.load(new) == entries
    assert await store.list_sessions("ignored") == await store.list_sessions("old-cwd")
    assert (await store.list_sessions("ignored"))[0]["session_id"] == "session"
    await store.append({**old, "subpath": "subagents/agent-a"}, [{"type": "metadata"}])
    assert await store.list_subkeys(new) == ["subagents/agent-a"]
    other = AgnoSessionStore(db, "other-tenant")
    await other.append(old, [{"type": "other"}])
    await store.delete(new)
    assert await store.load(old) is None
    assert await store.list_subkeys(old) == []
    assert await other.load(old) == [{"type": "other"}]


@pytest.mark.asyncio
async def test_order_across_fast_batches_and_reopen(db_factory, monkeypatch):
    from agno.db import transcripts

    monkeypatch.setattr(transcripts, "time_ns", lambda: 1800000000000000000)
    db = db_factory()
    store = AgnoSessionStore(db, "project")
    key = {"project_key": "cwd", "session_id": "session"}
    entries = [{"uuid": str(i), "type": "entry", "n": i} for i in range(1002)]
    await store.append(key, entries)
    # A restarted process has no in-memory position counter.
    monkeypatch.setattr(transcripts, "_last_position", 0)
    await store.append(key, [{"type": "last"}])
    reopened = AgnoSessionStore(db, "project")
    assert await reopened.load(key) == entries + [{"type": "last"}]


@pytest.mark.asyncio
async def test_sync_db_is_offloaded(db_factory):
    import threading

    db = db_factory()
    if isinstance(db, AsyncSqliteDb):
        return
    called = []
    caller = threading.get_ident()
    db.append_transcript_entries = lambda **kwargs: called.append(threading.get_ident())
    await AgnoSessionStore(db, "p").append({"session_id": "s"}, [{"type": "x"}])
    assert called and called[0] != caller


@pytest.mark.asyncio
async def test_empty_database_optional_operations(db_factory):
    store = AgnoSessionStore(db_factory(), "project")
    key = {"session_id": "missing", "project_key": "cwd"}
    assert await store.load(key) is None
    assert await store.list_sessions("cwd") == []
    assert await store.list_subkeys(key) == []
    await store.delete(key)
    await store.append(key, [])
    assert await store.load(key) is None
