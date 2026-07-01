import sys
import types
from typing import List
from unittest.mock import MagicMock

import pytest

from agno.knowledge.document import Document
from agno.vectordb.search import SearchType


@pytest.fixture()
def stub_glide(monkeypatch):
    """Patch glide_sync references inside the valkeydb module to avoid real network calls.

    Returns a tuple (glide_client_mock, glide_ft_mock).
    """
    # Ensure the module is importable (it may already be if valkey-glide-sync is installed)
    if "glide_sync" not in sys.modules:
        glide_mod = types.ModuleType("glide_sync")
        # Minimal stubs for types referenced at import time
        for attr in (
            "DataType",
            "DistanceMetricType",
            "FtCreateOptions",
            "FtSearchLimit",
            "FtSearchOptions",
            "GlideClient",
            "GlideClientConfiguration",
            "NodeAddress",
            "ReturnField",
            "ServerCredentials",
            "TagField",
            "TextField",
            "VectorAlgorithm",
            "VectorField",
            "VectorFieldAttributesFlat",
            "VectorFieldAttributesHnsw",
            "VectorType",
        ):
            setattr(glide_mod, attr, MagicMock(name=attr))
        glide_mod.ft = MagicMock(name="glide_ft_module")  # type: ignore[attr-defined]
        sys.modules["glide_sync"] = glide_mod

    # Now import the actual module so we can patch its glide_ft reference
    from agno.vectordb.valkey import valkeydb as valkeydb_mod

    ft_mock = MagicMock(name="glide_ft")
    monkeypatch.setattr(valkeydb_mod, "glide_ft", ft_mock)

    yield ft_mock


@pytest.fixture()
def import_valkeydb(stub_glide):
    """Import ValkeyDB after stubbing dependencies and return (ValkeyDB, ft_mock)."""
    from agno.vectordb.valkey.valkeydb import ValkeyDB

    ft_mock = stub_glide
    return ValkeyDB, ft_mock


@pytest.fixture()
def sample_documents() -> List[Document]:
    return [
        Document(content="Doc A", meta_data={"category": "A"}, name="doc_a"),
        Document(content="Doc B", meta_data={"category": "B"}, name="doc_b"),
        Document(content="Doc C", meta_data={"category": "A"}, name="doc_c"),
    ]


@pytest.fixture()
def valkey_db(import_valkeydb, mock_embedder):
    ValkeyDB, ft_mock = import_valkeydb

    # Pre-create a mock GlideClient so ValkeyDB never tries to connect
    client = MagicMock(name="GlideClientInstance")

    db = ValkeyDB(
        index_name="test_index",
        host="localhost",
        port=6379,
        glide_client=client,
        embedder=mock_embedder,
    )

    return db, client, ft_mock


@pytest.fixture()
def import_knowledge():
    from agno.knowledge.knowledge import Knowledge

    return Knowledge


@pytest.fixture()
def create_knowledge(import_knowledge, valkey_db):
    db, _client, _ft = valkey_db
    Knowledge = import_knowledge
    knowledge = Knowledge(
        name="My Valkey Vector Knowledge Base",
        description="This knowledge base uses Valkey as the vector store",
        vector_db=db,
    )
    return knowledge


# -- Tests --


def test_knowledge_insert(create_knowledge):
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


def test_create_and_exists(valkey_db):
    db, client, ft_mock = valkey_db

    # When index does not exist, create() should call glide_ft.create
    ft_mock.list.return_value = []
    ft_mock.create.return_value = None
    db.create()
    ft_mock.create.assert_called_once()

    # exists() returns True when index_name is in the list
    ft_mock.list.return_value = ["test_index"]
    assert db.exists() is True

    ft_mock.list.return_value = ["other_index"]
    assert db.exists() is False


def test_drop(valkey_db):
    db, client, ft_mock = valkey_db

    ft_mock.dropindex.return_value = None
    # Simulate scan returning no keys (cursor=0, empty list)
    client.scan.return_value = ("0", [])

    assert db.drop() is True
    ft_mock.dropindex.assert_called_once_with(client, "test_index")


def test_insert_hsets_documents(valkey_db, sample_documents):
    db, client, ft_mock = valkey_db

    db.insert(content_hash="chash1", documents=sample_documents)

    # hset should be called once per document
    assert client.hset.call_count == 3
    for call in client.hset.call_args_list:
        key = call.args[0]
        assert key.startswith("test_index:")


def test_upsert_deletes_existing_then_inserts(valkey_db, sample_documents):
    db, client, ft_mock = valkey_db

    # Simulate existing keys for the same content_hash via _find_keys_by_tag
    ft_mock.search.return_value = [2, {"test_index:key1": {}, "test_index:key2": {}}]
    client.delete.return_value = 1

    db.upsert(content_hash="same_hash", documents=sample_documents)

    # Should have deleted existing keys in a single batch call
    assert client.delete.call_count >= 1
    # And inserted new docs via hset
    assert client.hset.call_count >= 3


def test_existence_checks(valkey_db):
    db, client, ft_mock = valkey_db

    # name_exists -> True when count > 0
    ft_mock.search.return_value = [1, {"test_index:k1": {}}]
    assert db.name_exists("doc_a") is True

    ft_mock.search.return_value = [0, {}]
    assert db.name_exists("doc_a") is False

    # id_exists
    ft_mock.search.return_value = [1, {"test_index:k1": {}}]
    assert db.id_exists("someid") is True

    ft_mock.search.return_value = [0, {}]
    assert db.id_exists("someid") is False

    # content_hash_exists
    ft_mock.search.return_value = [1, {"test_index:k1": {}}]
    assert db.content_hash_exists("hash") is True

    ft_mock.search.return_value = [0, {}]
    assert db.content_hash_exists("hash") is False


def test_search_vector(valkey_db):
    db, client, ft_mock = valkey_db

    # Vector search: FT.SEARCH returns [count, {key: {field: value}}]
    ft_mock.search.return_value = [
        2,
        {
            "test_index:1": {"id": "1", "name": "doc_a", "content": "Doc A"},
            "test_index:2": {"id": "2", "name": "doc_b", "content": "Doc B"},
        },
    ]

    docs = db.search("q", limit=2)
    assert len(docs) == 2 and all(isinstance(d, Document) for d in docs)


def test_search_keyword(valkey_db):
    db, client, ft_mock = valkey_db

    ft_mock.search.return_value = [
        1,
        {
            "test_index:3": {"id": "3", "name": "doc_c", "content": "Doc C"},
        },
    ]
    db.search_type = SearchType.keyword
    docs = db.search("curry", limit=1)
    assert len(docs) == 1 and docs[0].name == "doc_c"


def test_delete_by_name_and_metadata_and_content_id(valkey_db):
    db, client, ft_mock = valkey_db

    # _find_keys_by_tag returns keys via FT.SEARCH
    ft_mock.search.return_value = [2, {"test_index:k1": {}, "test_index:k2": {}}]
    client.delete.return_value = 1

    assert db.delete_by_name("doc_a") is True
    # Batch delete: single call with all keys
    assert client.delete.call_count >= 1

    # Reset and test metadata deletion
    client.delete.reset_mock()
    ft_mock.search.return_value = [1, {"test_index:k3": {}}]
    assert db.delete_by_metadata({"category": "A"}) is True
    assert client.delete.call_count >= 1

    # Reset and test content_id deletion
    client.delete.reset_mock()
    ft_mock.search.return_value = [1, {"test_index:k4": {}}]
    assert db.delete_by_content_id("content-123") is True
    assert client.delete.call_count >= 1


def test_update_metadata_writes_to_hash(valkey_db):
    db, client, ft_mock = valkey_db

    # _find_keys_by_tag returns keys
    ft_mock.search.return_value = [2, {"test_index:k1": {}, "test_index:k2": {}}]

    db.update_metadata("content-xyz", {"status": "updated"})

    # hset called for each key
    assert client.hset.call_count == 2
    for call in client.hset.call_args_list:
        metadata_arg = call.args[1]
        assert metadata_arg["status"] == "updated"
