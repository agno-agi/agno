"""Integration tests for search_learnings on PostgresDb and AsyncPostgresDb.

The JSONB content column has no ILIKE operator; these tests prove the
CAST-to-TEXT path live. Requires the pgvector container from
./cookbook/scripts/run_pgvector.sh (localhost:5532).
"""

import uuid

import pytest

SYNC_DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
ASYNC_DB_URL = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"


def _postgres_reachable() -> bool:
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(SYNC_DB_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable on localhost:5532")


@pytest.fixture
def db():
    from agno.db.postgres import PostgresDb

    return PostgresDb(db_url=SYNC_DB_URL)


@pytest.fixture
def learning_ids():
    return [f"test-search-{uuid.uuid4().hex[:8]}" for _ in range(3)]


def test_search_learnings_casts_jsonb_and_crosses_slug_boundary(db, learning_ids):
    needle, spaced, decoy = learning_ids
    try:
        db.upsert_learning(
            id=needle,
            learning_type="entity_memory",
            entity_id="sarah_chen",
            namespace="test_search",
            content={"entity_id": "sarah_chen", "facts": [{"content": "designs radar"}]},
        )
        db.upsert_learning(
            id=spaced,
            learning_type="entity_memory",
            entity_id="acme_corp",
            namespace="test_search",
            content={"entity_id": "acme_corp", "name": "Acme Corp"},
        )
        db.upsert_learning(
            id=decoy,
            learning_type="entity_memory",
            entity_id="unrelated",
            namespace="test_search",
            content={"entity_id": "unrelated", "facts": [{"content": "nothing here"}]},
        )

        # JSONB path works at all (no cast -> this raises live)
        rows = db.search_learnings(query="designs radar", namespace="test_search")
        assert [r["learning_id"] for r in rows] == [needle]

        # Slug boundary: spaced query finds the slug...
        rows = db.search_learnings(query="sarah chen", namespace="test_search")
        assert [r["learning_id"] for r in rows] == [needle]
        # ...and the underscore query finds the spaced display name
        rows = db.search_learnings(query="acme_corp", namespace="test_search")
        assert spaced in [r["learning_id"] for r in rows]

        # Filters compose
        rows = db.search_learnings(query="sarah chen", namespace="test_search", entity_type="person")
        assert rows == []
    finally:
        for learning_id in learning_ids:
            db.delete_learning(id=learning_id)


async def test_async_search_learnings_casts_jsonb(learning_ids):
    from agno.db.postgres import AsyncPostgresDb

    adb = AsyncPostgresDb(db_url=ASYNC_DB_URL)
    needle = learning_ids[0]
    try:
        await adb.upsert_learning(
            id=needle,
            learning_type="entity_memory",
            entity_id="sarah_chen",
            namespace="test_search_async",
            content={"entity_id": "sarah_chen", "facts": [{"content": "prefers async communication"}]},
        )
        rows = await adb.search_learnings(query="sarah chen", namespace="test_search_async")
        assert [r["learning_id"] for r in rows] == [needle]

        rows = await adb.search_learnings(query="ASYNC COMMUNICATION", namespace="test_search_async")
        assert [r["learning_id"] for r in rows] == [needle]
    finally:
        await adb.delete_learning(id=needle)
