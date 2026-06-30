import sys
import types
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from agno.knowledge.document import Document
from agno.vectordb.search import SearchType


@pytest.fixture()
def stub_redisvl(monkeypatch):
    """Patch installed redis/redisvl to avoid real network and return MagicMock indexes.
    Returns a tuple (SearchIndex_mock, AsyncSearchIndex_mock).
    """
    # Patch redis client constructors to return MagicMocks
    try:
        import redis
        import redis.asyncio as redis_async
    except Exception:
        redis = types.ModuleType("redis")
        redis_async = types.ModuleType("redis.asyncio")
        sys.modules["redis"] = redis
        sys.modules["redis.asyncio"] = redis_async

    def _redis_from_url(url: str, **kwargs):
        return MagicMock(name="RedisClient")

    def _async_redis_from_url(url: str, **kwargs):
        return MagicMock(name="AsyncRedisClient")

    # If attributes don't exist, create shells
    if not hasattr(redis, "Redis"):

        class _Redis:  # type: ignore
            @classmethod
            def from_url(cls, url: str, **kwargs):
                return _redis_from_url(url, **kwargs)

        redis.Redis = _Redis  # type: ignore
    else:
        monkeypatch.setattr(redis.Redis, "from_url", staticmethod(_redis_from_url))

    if not hasattr(redis_async, "Redis"):

        class _AsyncRedis:  # type: ignore
            @classmethod
            def from_url(cls, url: str, **kwargs):
                return _async_redis_from_url(url, **kwargs)

        redis_async.Redis = _AsyncRedis  # type: ignore
    else:
        monkeypatch.setattr(redis_async.Redis, "from_url", staticmethod(_async_redis_from_url))

    # Patch redisvl SearchIndex/AsyncSearchIndex to return MagicMocks
    import importlib

    try:
        rvl_index = importlib.import_module("redisvl.index")
    except ModuleNotFoundError:
        rvl_index = types.ModuleType("redisvl.index")
        sys.modules["redisvl.index"] = rvl_index

    search_index_mock = MagicMock(name="SearchIndex")
    async_search_index_mock = MagicMock(name="AsyncSearchIndex")

    def _SearchIndex(*args, **kwargs):
        return search_index_mock

    def _AsyncSearchIndex(*args, **kwargs):
        return async_search_index_mock

    monkeypatch.setattr(rvl_index, "SearchIndex", _SearchIndex, raising=False)
    monkeypatch.setattr(rvl_index, "AsyncSearchIndex", _AsyncSearchIndex, raising=False)

    # Optionally patch utils to simple pass-throughs (safe even if module missing)
    try:
        rvl_utils = importlib.import_module("redisvl.redis.utils")
        monkeypatch.setattr(rvl_utils, "convert_bytes", lambda x: x, raising=False)
        monkeypatch.setattr(rvl_utils, "array_to_buffer", lambda a, dt: a, raising=False)
        monkeypatch.setattr(rvl_utils, "buffer_to_array", lambda b, dt: b, raising=False)
    except ModuleNotFoundError:
        pass

    # Also ensure schema.from_dict is available (no-op)
    try:
        rvl_schema = importlib.import_module("redisvl.schema")

        class _IndexSchema:
            @classmethod
            def from_dict(cls, d: Dict[str, Any]):
                return d

        monkeypatch.setattr(rvl_schema, "IndexSchema", _IndexSchema, raising=False)
    except ModuleNotFoundError:
        pass

    yield search_index_mock, async_search_index_mock


@pytest.fixture()
def import_redisdb(stub_redisvl):
    """Import RedisVectorDb after stubbing dependencies and return (RedisVectorDb, search_idx_mock)."""
    # Delayed import to ensure patches are in place
    from agno.vectordb.redis import RedisVectorDb  # type: ignore

    search_idx_mock, async_idx_mock = stub_redisvl
    return RedisVectorDb, search_idx_mock, async_idx_mock


@pytest.fixture()
def sample_documents() -> List[Document]:
    return [
        Document(content="Doc A", meta_data={"category": "A"}, name="doc_a"),
        Document(content="Doc B", meta_data={"category": "B"}, name="doc_b"),
        Document(content="Doc C", meta_data={"category": "A"}, name="doc_c"),
    ]


@pytest.fixture()
def redis_db(import_redisdb, mock_embedder):
    RedisVectorDb, _search_idx_mock, _ = import_redisdb

    db = RedisVectorDb(
        index_name="test_index",
        redis_url="redis://localhost:6379/0",
        embedder=mock_embedder,
    )

    # Replace the internal index with our own MagicMock instance so we fully control it
    idx = MagicMock(name="SearchIndexInstance")
    idx.exists.return_value = False
    idx.create.return_value = None
    idx.delete.return_value = None
    idx.load.return_value = None
    idx.clear.return_value = None
    idx.drop_keys.return_value = 1
    idx.drop_documents.return_value = 1

    db.index = idx
    return db, idx


@pytest.fixture()
def import_knowledge():
    from agno.knowledge.knowledge import Knowledge

    return Knowledge


@pytest.fixture()
def create_knowledge(import_knowledge, redis_db):
    db, idx = redis_db
    Knowledge = import_knowledge
    knowledge = Knowledge(
        name="My Redis Vector Knowledge Base",
        description="This knowledge base uses Redis + RedisVL as the vector store",
        vector_db=db,
    )
    return knowledge


def test_knowlwedge_insert(create_knowledge):
    knowledge = create_knowledge
    try:
        result = knowledge.insert(
            name="Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            metadata={"doc_type": "recipe_book"},
            skip_if_exists=True,
        )

        assert result is None or result is not False

    except Exception as e:
        pytest.fail(f"insert raised an unexpected exception: {e}")


def test_create_and_exists(redis_db):
    db, idx = redis_db
    # When index does not exist, create() should call create()
    idx.exists.return_value = False
    db.create()
    idx.create.assert_called_once()

    # exists() returns underlying value
    idx.exists.return_value = True
    assert db.exists() is True
    idx.exists.return_value = False
    assert db.exists() is False


def test_drop(redis_db):
    db, idx = redis_db
    assert db.drop() is True
    idx.delete.assert_called_once()


def test_insert_loads_documents(redis_db, sample_documents):
    db, idx = redis_db
    db.insert(content_hash="chash1", documents=sample_documents)
    # Ensure load was called with id_field and 3 docs
    assert idx.load.call_count == 1
    args, kwargs = idx.load.call_args
    loaded = args[0]
    assert isinstance(loaded, list) and len(loaded) == 3
    assert kwargs.get("id_field") == "id"
    # Documents should have content_hash field set
    assert all("content_hash" in d for d in loaded)


def test_upsert_deletes_existing_then_inserts(redis_db, sample_documents):
    db, idx = redis_db

    # Simulate existing keys for the same content_hash
    idx.query.return_value = [{"id": "test_index:key1"}, {"id": "test_index:key2"}]

    db.upsert(content_hash="same_hash", documents=sample_documents)

    # Should have dropped keys for each found result
    assert idx.drop_keys.call_count == 2
    # And loaded new docs
    assert idx.load.call_count >= 1


def test_existence_checks(redis_db):
    db, idx = redis_db

    # name_exists -> returns True if query returns non-empty
    idx.query.return_value = [{"id": "k1"}]
    assert db.name_exists("doc_a") is True
    idx.query.return_value = []
    assert db.name_exists("doc_a") is False

    # id_exists
    idx.query.return_value = [{"id": "k1"}]
    assert db.id_exists("someid") is True
    idx.query.return_value = []
    assert db.id_exists("someid") is False

    # content_hash_exists
    idx.query.return_value = [{"id": "k1"}]
    assert db.content_hash_exists("hash") is True
    idx.query.return_value = []
    assert db.content_hash_exists("hash") is False


def test_search_vector_keyword_hybrid(redis_db):
    db, idx = redis_db

    # Configure vector_search to return list of dicts that map to Documents
    idx.query.return_value = [
        {"id": "1", "name": "doc_a", "content": "Doc A"},
        {"id": "2", "name": "doc_b", "content": "Doc B"},
    ]

    db.search_type = SearchType.vector
    docs = db.search("q", limit=2)
    assert len(docs) == 2 and all(isinstance(d, Document) for d in docs)

    # Keyword search uses convert_bytes, but we stubbed it to passthrough
    idx.query.return_value = [
        {"id": "3", "name": "doc_c", "content": "Doc C"},
    ]
    db.search_type = SearchType.keyword
    docs = db.search("curry", limit=1)
    assert len(docs) == 1 and docs[0].name == "doc_c"

    # Hybrid search
    idx.query.return_value = [
        {"id": "4", "name": "doc_a", "content": "Doc A"},
    ]
    db.search_type = SearchType.hybrid
    docs = db.search("thai curry", limit=1)
    assert len(docs) == 1 and docs[0].name == "doc_a"


def test_delete_by_name_and_metadata_and_content_id(redis_db):
    db, idx = redis_db

    # Query returns 2 keys to delete
    idx.query.return_value = [{"id": "test_index:k1"}, {"id": "test_index:k2"}]
    idx.drop_keys.return_value = 1

    assert db.delete_by_name("doc_a") is True
    assert idx.drop_keys.call_count >= 2

    # Reset and test metadata deletion
    idx.drop_keys.reset_mock()
    assert db.delete_by_metadata({"category": "A"}) is True
    assert idx.drop_keys.call_count >= 1

    # Reset and test content_id deletion
    idx.drop_keys.reset_mock()
    assert db.delete_by_content_id("content-123") is True
    assert idx.drop_keys.call_count >= 1


def test_update_metadata_writes_to_hash(redis_db):
    db, idx = redis_db

    # Query returns keys to update
    idx.query.return_value = [{"id": "test_index:k1"}, {"id": "test_index:k2"}]

    # Underlying redis client was created by stub as MagicMock
    redis_client = db.redis_client

    db.update_metadata("content-xyz", {"status": "updated"})

    # Ensure hset called for each key
    assert redis_client.hset.call_count == 2
    for call in redis_client.hset.call_args_list:
        assert "mapping" in call.kwargs and call.kwargs["mapping"]["status"] == "updated"
