import hashlib
import shutil
import tempfile
from typing import List
from unittest.mock import MagicMock

import numpy as np
import pytest

pytest.importorskip("quantal", reason="quantaldb not installed (pip install quantaldb)")

from agno.knowledge.document import Document
from agno.vectordb.quantal import QuantalDb
from agno.vectordb.search import SearchType

TEST_COLLECTION = "test_collection"
DIMS = 256


def _embedding(text: str) -> List[float]:
    """Deterministic embedding: identical text always maps to the same
    vector, so search assertions are meaningful."""
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")
    v = np.random.default_rng(seed).standard_normal(DIMS).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def embedder():
    mock = MagicMock()
    mock.dimensions = DIMS
    mock.get_embedding.side_effect = _embedding
    mock.get_embedding_and_usage.side_effect = lambda text: (_embedding(text), None)

    async def async_get_embedding_and_usage(text):
        return _embedding(text), None

    mock.async_get_embedding_and_usage.side_effect = async_get_embedding_and_usage
    mock.enable_batch = False
    return mock


@pytest.fixture
def quantal_db(embedder):
    path = tempfile.mkdtemp()
    db = QuantalDb(collection=TEST_COLLECTION, path=path, embedder=embedder)
    db.create()
    yield db
    db.drop()
    shutil.rmtree(path, ignore_errors=True)


def _docs() -> List[Document]:
    return [
        Document(
            content="Jupiter's Great Red Spot is a centuries-old storm", name="jupiter", meta_data={"kind": "planet"}
        ),
        Document(content="Saturn's rings are mostly water ice", name="saturn", meta_data={"kind": "planet"}),
        Document(
            content="The Andromeda galaxy will merge with the Milky Way", name="andromeda", meta_data={"kind": "galaxy"}
        ),
    ]


def test_insert_and_search(quantal_db):
    quantal_db.insert("hash1", _docs())
    assert quantal_db.get_count() == 3

    results = quantal_db.search("The Andromeda galaxy will merge with the Milky Way", limit=2)
    assert len(results) == 2
    assert results[0].name == "andromeda"
    assert results[0].meta_data["score"] == pytest.approx(1.0, abs=0.05)


def test_search_with_filters(quantal_db):
    quantal_db.insert("hash1", _docs(), filters={"source": "astronomy_notes"})

    results = quantal_db.search("rings of a gas giant", limit=3, filters={"kind": "planet"})
    assert {r.name for r in results} == {"jupiter", "saturn"}

    assert quantal_db.search("rings of a gas giant", limit=3, filters={"kind": "comet"}) == []
    assert all(r.meta_data["source"] == "astronomy_notes" for r in results)


def test_search_empty(quantal_db):
    assert quantal_db.search("anything") == []


def test_exists_and_id_exists(quantal_db):
    assert quantal_db.exists() is True
    quantal_db.insert("hash1", _docs())
    doc_id = next(iter(quantal_db._docstore))
    assert quantal_db.id_exists(doc_id) is True
    assert quantal_db.id_exists("missing") is False


def test_name_exists(quantal_db):
    quantal_db.insert("hash1", _docs())
    assert quantal_db.name_exists("saturn") is True
    assert quantal_db.name_exists("missing") is False


def test_content_hash_exists(quantal_db):
    quantal_db.insert("hash1", _docs())
    assert quantal_db.content_hash_exists("hash1") is True
    assert quantal_db.content_hash_exists("hash2") is False


def test_upsert_replaces_content_hash(quantal_db):
    quantal_db.insert("hash1", _docs())
    assert quantal_db.upsert_available() is True

    quantal_db.upsert("hash1", [Document(content="Europa hides a subsurface ocean", name="europa")])
    assert quantal_db.get_count() == 1
    assert quantal_db.name_exists("europa")
    assert not quantal_db.name_exists("saturn")


def test_delete_by_id(quantal_db):
    quantal_db.insert("hash1", _docs())
    doc_id = next(iter(quantal_db._docstore))
    assert quantal_db.delete_by_id(doc_id) is True
    assert quantal_db.get_count() == 2
    assert quantal_db.delete_by_id(doc_id) is False


def test_delete_by_name(quantal_db):
    quantal_db.insert("hash1", _docs())
    assert quantal_db.delete_by_name("saturn") is True
    assert quantal_db.get_count() == 2
    assert quantal_db.delete_by_name("missing") is False

    results = quantal_db.search("Saturn's rings are mostly water ice", limit=3)
    assert all(r.name != "saturn" for r in results)


def test_delete_by_metadata(quantal_db):
    quantal_db.insert("hash1", _docs())
    assert quantal_db.delete_by_metadata({"kind": "planet"}) is True
    assert quantal_db.get_count() == 1
    assert quantal_db.delete_by_metadata({"kind": "comet"}) is False


def test_delete_by_content_id(quantal_db):
    quantal_db.insert("hash1", [Document(content="some text", content_id="c1")])
    assert quantal_db.delete_by_content_id("c1") is True
    assert quantal_db.get_count() == 0
    assert quantal_db.delete_by_content_id("c1") is False


def test_update_metadata(quantal_db):
    quantal_db.insert("hash1", [Document(content="some text", content_id="c1", meta_data={"a": 1})])
    quantal_db.update_metadata("c1", {"b": 2})
    entry = next(iter(quantal_db._docstore.values()))
    assert entry["meta_data"]["a"] == 1
    assert entry["meta_data"]["b"] == 2


def test_delete_collection(quantal_db):
    quantal_db.insert("hash1", _docs())
    assert quantal_db.delete() is True
    assert quantal_db.get_count() == 0


def test_persistence_roundtrip(embedder):
    path = tempfile.mkdtemp()
    try:
        db = QuantalDb(collection=TEST_COLLECTION, path=path, embedder=embedder)
        db.create()
        db.insert("hash1", _docs())
        db.delete_by_name("saturn")

        reloaded = QuantalDb(collection=TEST_COLLECTION, path=path, embedder=embedder)
        reloaded.create()
        assert reloaded.get_count() == 2
        assert not reloaded.name_exists("saturn")

        results = reloaded.search("Jupiter's Great Red Spot is a centuries-old storm", limit=1)
        assert results[0].name == "jupiter"

        # New inserts after a reload must not collide with prior internal ids.
        reloaded.insert("hash2", [Document(content="Europa hides a subsurface ocean", name="europa")])
        assert reloaded.get_count() == 3
        reloaded.drop()
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_similarity_threshold(embedder):
    path = tempfile.mkdtemp()
    try:
        db = QuantalDb(collection=TEST_COLLECTION, path=path, embedder=embedder, similarity_threshold=0.9)
        db.create()
        db.insert("hash1", _docs())

        results = db.search("The Andromeda galaxy will merge with the Milky Way", limit=3)
        assert [r.name for r in results] == ["andromeda"]
        db.drop()
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_get_supported_search_types(quantal_db):
    assert quantal_db.get_supported_search_types() == [SearchType.vector]


@pytest.mark.asyncio
async def test_async_roundtrip(quantal_db):
    await quantal_db.async_insert("hash1", _docs())
    assert await quantal_db.async_exists() is True
    assert await quantal_db.async_name_exists("saturn") is True

    results = await quantal_db.async_search("The Andromeda galaxy will merge with the Milky Way", limit=1)
    assert results[0].name == "andromeda"

    await quantal_db.async_upsert("hash1", [Document(content="Europa hides a subsurface ocean", name="europa")])
    assert quantal_db.get_count() == 1
    await quantal_db.async_drop()
    assert quantal_db.get_count() == 0
