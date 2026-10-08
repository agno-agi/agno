"""Transcript contracts against a disposable PostgreSQL schema."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from agno.agents.claude.session_store import AgnoSessionStore
from agno.db.postgres import AsyncPostgresDb, PostgresDb


@pytest.mark.skipif(not os.getenv("AGNO_TEST_TRANSCRIPT_POSTGRES_URL"), reason="Set AGNO_TEST_TRANSCRIPT_POSTGRES_URL")
@pytest.mark.parametrize("async_db", [False, True])
@pytest.mark.asyncio
async def test_postgres_transcript_contract(async_db):
    from claude_agent_sdk.testing import run_session_store_conformance

    url = os.environ["AGNO_TEST_TRANSCRIPT_POSTGRES_URL"]
    schema = "transcript_test_" + uuid4().hex
    sync_engine = create_engine(url)
    cls = AsyncPostgresDb if async_db else PostgresDb
    db = cls(db_url=url, db_schema=schema)

    class Stores:
        def __init__(self):
            self.prefix = uuid4().hex

        def store(self, project):
            return AgnoSessionStore(db, self.prefix + project)

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

    try:
        # Use independent adapter instances so lazy table caches stay valid.
        counter = 0
        stores = []

        def make():
            nonlocal counter, db
            counter += 1
            db = cls(db_url=url, db_schema=schema)
            db.transcripts_table_name = "transcripts_" + str(counter)
            stores.append(db)
            return Stores()

        await run_session_store_conformance(make)
        store = AgnoSessionStore(db, "tenant")
        key = {"project_key": "cwd", "session_id": "s"}
        entry = {"uuid": str(uuid4()), "type": "user", "text": "fact"}
        await store.append(key, [entry])
        await store.append(key, [entry])
        assert await store.load({**key, "project_key": "new-cwd"}) == [entry]
        await store.delete(key)
        assert await store.load(key) is None
    finally:
        for adapter in stores:
            if async_db:
                await adapter.db_engine.dispose()
            else:
                adapter.db_engine.dispose()
        with sync_engine.begin() as conn:
            conn.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
        sync_engine.dispose()
