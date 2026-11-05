"""SurrealDb vector store against a real in-process engine, so SDK behavior changes cannot hide behind mocks."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agno.knowledge.document import Document
from agno.vectordb.surrealdb import SurrealDb

surrealdb = pytest.importorskip("surrealdb")

DIMENSIONS = 4
EMBEDDING = [0.1, 0.2, 0.3, 0.4]


@pytest.fixture
def embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.dimensions = DIMENSIONS
    embedder.get_embedding.return_value = EMBEDDING
    embedder.get_embedding_and_usage.return_value = (EMBEDDING, {})
    embedder.async_get_embedding = AsyncMock(return_value=EMBEDDING)
    embedder.async_get_embedding_and_usage = AsyncMock(return_value=(EMBEDDING, {}))
    embedder.enable_batch = False
    return embedder


@pytest.fixture
def store(embedder: MagicMock) -> SurrealDb:
    client = surrealdb.Surreal("mem://")
    client.use("test", uuid4().hex)
    vector_db = SurrealDb(client=client, collection="docs", embedder=embedder)
    vector_db.create()
    return vector_db


def _doc(name: str = "doc") -> Document:
    return Document(id=f"{name}_id", name=name, content=f"content of {name}", embedding=EMBEDDING)


def test_create_defines_the_table(store: SurrealDb):
    assert store.exists() is True


def test_exists_is_false_before_create(embedder: MagicMock):
    client = surrealdb.Surreal("mem://")
    client.use("test", uuid4().hex)

    assert SurrealDb(client=client, collection="docs", embedder=embedder).exists() is False


def test_name_exists_distinguishes_present_from_absent(store: SurrealDb):
    store.insert(content_hash="hash", documents=[_doc()])

    assert store.name_exists("doc") is True
    assert store.name_exists("missing") is False


def test_inserted_document_is_found_by_search(store: SurrealDb):
    store.insert(content_hash="hash", documents=[_doc()])

    results = store.search("query", limit=1)

    assert [doc.content for doc in results] == ["content of doc"]


def test_delete_by_name_removes_the_document(store: SurrealDb):
    store.insert(content_hash="hash", documents=[_doc()])

    store.delete_by_name("doc")

    assert store.name_exists("doc") is False


def test_drop_removes_the_table(store: SurrealDb):
    store.drop()

    assert store.exists() is False


@pytest.mark.asyncio
async def test_async_round_trip(embedder: MagicMock):
    client = surrealdb.AsyncSurreal("mem://")
    if hasattr(client, "connect"):
        await client.connect()
    await client.use("test", uuid4().hex)
    store = SurrealDb(async_client=client, collection="docs", embedder=embedder)

    await store.async_create()
    assert await store.async_exists() is True
    assert await store.async_name_exists("doc") is False

    await store.async_insert(content_hash="hash", documents=[_doc()])
    assert await store.async_name_exists("doc") is True
    assert [doc.content for doc in await store.async_search("query", limit=1)] == ["content of doc"]

    await store.async_drop()
    assert await store.async_exists() is False
