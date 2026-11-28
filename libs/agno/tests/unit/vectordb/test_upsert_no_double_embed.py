from typing import Any

import pytest

from agno.knowledge.document import Document
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.qdrant import Qdrant
from tests.unit.vectordb.conftest import DeterministicEmbedder


class CountingEmbedder(DeterministicEmbedder):
    """Embedder that counts sync, async, and batch embedding invocations."""

    def __init__(self, dimensions: int = 8, enable_batch: bool = False):
        super().__init__(dimensions=dimensions)
        self.enable_batch = enable_batch
        self.sync_calls = 0
        self.async_calls = 0
        self.batch_calls = 0

    def get_embedding_and_usage(self, text: str) -> tuple[list[float], dict[str, Any]]:
        self.sync_calls += 1
        return super().get_embedding_and_usage(text)

    async def async_get_embedding_and_usage(self, text: str) -> tuple[list[float], dict[str, Any]]:
        self.async_calls += 1
        return await super().async_get_embedding_and_usage(text)

    async def async_get_embeddings_batch_and_usage(
        self, texts: list[str]
    ) -> tuple[list[list[float]], list[dict[str, Any]]]:
        self.batch_calls += 1
        return [self.get_embedding(t) for t in texts], [{"total_tokens": 1} for _ in texts]


def _make_docs(n: int = 5) -> list[Document]:
    return [Document(content=f"chunk {i}", name=f"doc_{i}") for i in range(n)]


def test_chromadb_upsert_embeds_once():
    embedder = CountingEmbedder()
    db = ChromaDb(collection="test_no_double_embed", embedder=embedder, persistent_client=False)
    db.create()
    try:
        docs = _make_docs(5)
        db.upsert("hash_1", docs)
        assert embedder.sync_calls == 5
    finally:
        db.drop()


@pytest.mark.asyncio
@pytest.mark.parametrize("enable_batch", [False, True])
async def test_chromadb_async_upsert_embeds_once(enable_batch: bool):
    embedder = CountingEmbedder(enable_batch=enable_batch)
    db = ChromaDb(collection="test_async_no_double_embed", embedder=embedder, persistent_client=False)
    db.create()
    try:
        docs = _make_docs(5)
        await db.async_upsert("hash_1", docs)
        if enable_batch:
            assert embedder.batch_calls == 1
            assert embedder.async_calls == 0
        else:
            assert embedder.async_calls == 5
            assert embedder.batch_calls == 0
    finally:
        db.drop()


def test_qdrant_upsert_embeds_once():
    embedder = CountingEmbedder()
    db = Qdrant(collection="test_qdrant_no_double_embed", location=":memory:", embedder=embedder)
    db.create()
    try:
        docs = _make_docs(5)
        db.upsert("hash_1", docs)
        assert embedder.sync_calls == 5
    finally:
        db.drop()


@pytest.mark.asyncio
@pytest.mark.parametrize("enable_batch", [False, True])
async def test_qdrant_async_upsert_embeds_once(enable_batch: bool):
    embedder = CountingEmbedder(enable_batch=enable_batch)
    db = Qdrant(collection="test_qdrant_async_no_double_embed", location=":memory:", embedder=embedder)
    await db.async_create()
    try:
        docs = _make_docs(5)
        await db.async_upsert("hash_1", docs)
        if enable_batch:
            assert embedder.batch_calls == 1
            assert embedder.async_calls == 0
        else:
            assert embedder.async_calls == 5
            assert embedder.batch_calls == 0
    finally:
        await db.async_drop()
