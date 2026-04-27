"""Integration tests for ValkeyDB vector database with performance benchmarks.

Requires a running Valkey instance on localhost:6379 with the valkey-search module.
Run with: pytest libs/agno/tests/integration/vector_dbs/test_valkeydb.py -v -s
"""

from typing import Dict, List, Optional, Tuple

import pytest

from agno.knowledge.document.base import Document
from agno.knowledge.embedder.base import Embedder
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType
from agno.vectordb.valkey.valkeydb import ValkeyDB


class MockEmbedder(Embedder):
    """Deterministic embedder that avoids external API calls."""

    dimensions: int = 128

    def get_embedding(self, text: str) -> List[float]:
        # Simple deterministic embedding based on text hash
        h = hash(text) & 0xFFFFFFFF
        base = [(h >> i & 0xFF) / 255.0 for i in range(0, 32, 8)]
        return (base * (self.dimensions // len(base) + 1))[: self.dimensions]

    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        return [self.get_embedding(t) for t in texts]

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text), None

    async def async_get_embedding(self, text: str) -> List[float]:
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text), None


@pytest.fixture()
def embedder() -> MockEmbedder:
    return MockEmbedder()


@pytest.fixture()
def valkey_db(embedder: MockEmbedder) -> ValkeyDB:
    """Create a ValkeyDB instance and ensure a clean index."""
    db = ValkeyDB(
        index_name="test_valkey_integ",
        host="localhost",
        port=6379,
        embedder=embedder,
        search_type=SearchType.vector,
        distance=Distance.cosine,
        vector_algorithm="FLAT",
    )
    # Drop any leftover index from a previous run
    db.drop()
    db.create()
    return db


@pytest.fixture(autouse=True)
def cleanup(valkey_db: ValkeyDB):
    """Drop the index after each test."""
    yield
    valkey_db.drop()


def _make_docs(count: int, prefix: str = "doc") -> List[Document]:
    return [
        Document(
            name=f"{prefix}_{i}",
            content=f"Content for document {prefix} number {i}",
            meta_data={"category": f"cat_{i % 3}", "source": prefix},
        )
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Functional tests
# ---------------------------------------------------------------------------


def test_create_and_exists(valkey_db: ValkeyDB):
    assert valkey_db.exists() is True


def test_insert_and_search(valkey_db: ValkeyDB):
    docs = _make_docs(5)
    valkey_db.insert("hash_1", docs)

    results = valkey_db.search("Content for document doc number 0", limit=3)
    assert len(results) > 0
    assert all(isinstance(d, Document) for d in results)


def test_name_exists(valkey_db: ValkeyDB):
    docs = _make_docs(2)
    valkey_db.insert("hash_1", docs)

    assert valkey_db.name_exists("doc_0") is True
    assert valkey_db.name_exists("nonexistent") is False


def test_content_hash_exists(valkey_db: ValkeyDB):
    docs = _make_docs(2)
    valkey_db.insert("unique_hash", docs)

    assert valkey_db.content_hash_exists("unique_hash") is True
    assert valkey_db.content_hash_exists("missing_hash") is False


def test_upsert_replaces_documents(valkey_db: ValkeyDB):
    original = _make_docs(3, prefix="orig")
    valkey_db.insert("upsert_hash", original)
    assert valkey_db.content_hash_exists("upsert_hash") is True

    replacement = _make_docs(2, prefix="repl")
    valkey_db.upsert("upsert_hash", replacement)

    # Old docs should be gone, new ones present
    assert valkey_db.name_exists("repl_0") is True
    assert valkey_db.name_exists("repl_1") is True
    # Original names should no longer exist
    assert valkey_db.name_exists("orig_0") is False


def test_delete_by_name(valkey_db: ValkeyDB):
    docs = _make_docs(3)
    valkey_db.insert("hash_del", docs)

    assert valkey_db.delete_by_name("doc_1") is True
    assert valkey_db.name_exists("doc_1") is False
    assert valkey_db.name_exists("doc_0") is True


def test_delete_by_metadata(valkey_db: ValkeyDB):
    docs = _make_docs(6)
    valkey_db.insert("hash_meta", docs)

    # Delete all docs with category=cat_0 (indices 0, 3)
    assert valkey_db.delete_by_metadata({"category": "cat_0"}) is True
    assert valkey_db.name_exists("doc_0") is False
    assert valkey_db.name_exists("doc_3") is False
    # Others survive
    assert valkey_db.name_exists("doc_1") is True


def test_keyword_search(valkey_db: ValkeyDB):
    valkey_db.search_type = SearchType.keyword
    docs = _make_docs(5)
    valkey_db.insert("hash_kw", docs)

    results = valkey_db.keyword_search("document", limit=5)
    assert len(results) > 0


def test_drop_and_recreate(valkey_db: ValkeyDB):
    docs = _make_docs(2)
    valkey_db.insert("hash_drop", docs)

    assert valkey_db.drop() is True
    assert valkey_db.exists() is False

    valkey_db.create()
    assert valkey_db.exists() is True
    # Data should be gone
    assert valkey_db.name_exists("doc_0") is False
