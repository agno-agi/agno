import asyncio
import copy
import os
import time
from hashlib import md5
from typing import Generator

import pytest
from couchbase.auth import PasswordAuthenticator
from couchbase.management.search import SearchIndex
from couchbase.options import ClusterOptions, KnownConfigProfiles

from agno.document import Document
from agno.embedder.openai import OpenAIEmbedder
from agno.vectordb.couchbase.couchbase import CouchbaseSearch

# Skip all tests if environment variables not set
pytestmark = pytest.mark.skipif(
    not all(
        [
            os.getenv("COUCHBASE_CONNECTION_STRING"),
            os.getenv("COUCHBASE_USER"),
            os.getenv("COUCHBASE_PASSWORD"),
            os.getenv("OPENAI_API_KEY"),
        ]
    ),
    reason="Required environment variables not set",
)


@pytest.fixture(scope="module")
def embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder(id="text-embedding-3-large", dimensions=3072)


@pytest.fixture(scope="module")
def cluster_options() -> ClusterOptions:
    """Create a cluster options object with the correct profile."""
    options = ClusterOptions(
        authenticator=PasswordAuthenticator(os.getenv("COUCHBASE_USER", ""), os.getenv("COUCHBASE_PASSWORD", ""))
    )
    options.apply_profile(KnownConfigProfiles.WanDevelopment)
    return options


@pytest.fixture(scope="module")
def search_index() -> SearchIndex:
    return SearchIndex(
        name="vector_search",
        source_type="gocbcore",
        idx_type="fulltext-index",
        source_name="test_bucket",
        plan_params={"index_partitions": 1, "num_replicas": 0},
        params={
            "doc_config": {
                "docid_prefix_delim": "",
                "docid_regexp": "",
                "mode": "scope.collection.type_field",
                "type_field": "type",
            },
            "mapping": {
                "default_analyzer": "standard",
                "default_datetime_parser": "dateTimeOptional",
                "index_dynamic": True,
                "store_dynamic": True,
                "default_mapping": {"dynamic": True, "enabled": False},
                "types": {
                    "test_scope.test_collection": {
                        "dynamic": False,
                        "enabled": True,
                        "properties": {
                            "content": {
                                "enabled": True,
                                "fields": [
                                    {
                                        "docvalues": True,
                                        "include_in_all": False,
                                        "include_term_vectors": False,
                                        "index": True,
                                        "name": "content",
                                        "store": True,
                                        "type": "text",
                                    }
                                ],
                            },
                            "embedding": {
                                "enabled": True,
                                "dynamic": False,
                                "fields": [
                                    {
                                        "vector_index_optimized_for": "recall",
                                        "docvalues": True,
                                        "dims": 3072,
                                        "include_in_all": False,
                                        "include_term_vectors": False,
                                        "index": True,
                                        "name": "embedding",
                                        "similarity": "dot_product",
                                        "store": True,
                                        "type": "vector",
                                    }
                                ],
                            },
                            "meta": {
                                "dynamic": True,
                                "enabled": True,
                                "properties": {
                                    "name": {
                                        "enabled": True,
                                        "fields": [
                                            {
                                                "docvalues": True,
                                                "include_in_all": False,
                                                "include_term_vectors": False,
                                                "index": True,
                                                "name": "name",
                                                "store": True,
                                                "analyzer": "keyword",
                                                "type": "text",
                                            }
                                        ],
                                    }
                                },
                            },
                        },
                    }
                },
            },
        },
    )


@pytest.fixture
def couchbase_db(
    cluster_options: ClusterOptions, search_index: SearchIndex, embedder: OpenAIEmbedder
) -> Generator[CouchbaseSearch, None, None]:
    """Create a test database and clean up after tests."""
    print(f"COUCHBASE_CONNECTION_STRING: {os.getenv('COUCHBASE_CONNECTION_STRING')}")
    db = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string=os.getenv("COUCHBASE_CONNECTION_STRING"),
        cluster_options=cluster_options,
        search_index=search_index,
        embedder=embedder,
        overwrite=True,
        wait_until_index_ready=30,
    )

    try:
        db.create()

        # Create a secondary index on the name field
        index_query = f"CREATE INDEX idx_name ON `{db.collection_name}` (name)"
        db._scope.query(index_query).execute()
        print("Created secondary index on name field: idx_name")

        yield db
    finally:
        db.delete()


@pytest.fixture
def test_documents() -> list[Document]:
    return [
        Document(
            name="doc1", content="The quick brown fox jumps over the lazy dog", meta_data={"type": "test", "id": 1}
        ),
        Document(name="doc2", content="Pack my box with five dozen liquor jugs", meta_data={"type": "test", "id": 2}),
        Document(name="doc3", content="The five boxing wizards jump quickly", meta_data={"type": "test", "id": 3}),
    ]


def test_insert_and_search(couchbase_db: CouchbaseSearch, test_documents: list[Document]):
    """Test basic insert and search functionality."""
    # Insert documents
    print(f"Inserting documents: {test_documents}")
    couchbase_db.insert(test_documents.copy())
    time.sleep(10)
    # Verify count
    assert couchbase_db.get_count() == len(test_documents)

    # Search for documents
    results = couchbase_db.search("fox jumps", limit=2)
    assert len(results) > 0
    assert isinstance(results[0], Document)
    assert "fox" in results[0].content.lower()


def test_document_exists(couchbase_db: CouchbaseSearch, test_documents: list[Document]):
    """Test document existence checks."""
    # Insert one document
    couchbase_db.insert([test_documents.copy()[0]])

    # Check existence
    assert couchbase_db.doc_exists(test_documents[0])
    assert not couchbase_db.doc_exists(test_documents[1])
    assert couchbase_db.name_exists(test_documents[0].name)
    assert not couchbase_db.name_exists(test_documents[1].name)


def test_upsert(couchbase_db: CouchbaseSearch, test_documents: list[Document]):
    """Test upsert functionality."""
    # Initial insert
    couchbase_db.insert([test_documents.copy()[0]])
    time.sleep(5)
    initial_count = couchbase_db.get_count()

    # Upsert same document with modified content
    modified_doc = Document(
        id=test_documents[0].id,
        name=test_documents[0].name,
        content=test_documents[0].content,
        meta_data=test_documents[0].meta_data,
    )
    couchbase_db.upsert([modified_doc])
    time.sleep(5)
    # Count should remain same
    assert couchbase_db.get_count() == initial_count

    # Search should find modified content
    results = couchbase_db.search("The quick brown", limit=1)
    assert len(results) == 1
    assert results[0].content.startswith("The quick brown")


def test_cluster_level_index(cluster_options: ClusterOptions, search_index: SearchIndex, embedder: OpenAIEmbedder):
    """Test operations with cluster-level index."""
    db = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string=os.getenv("COUCHBASE_CONNECTION_STRING", ""),
        cluster_options=cluster_options,
        search_index=search_index,
        embedder=embedder,
        overwrite=True,
        is_global_level_index=True,
        wait_until_index_ready=30,
    )

    try:
        # Create and verify
        db.create()
        assert db.exists()

        # Test basic operations
        doc = Document(name="cluster_test", content="Testing cluster level index", meta_data={"level": "cluster"})
        db.insert([doc])

        # Verify search works
        results = db.search("cluster level", limit=1)
        assert len(results) == 1
        assert results[0].name == "cluster_test"

    finally:
        db.delete()


@pytest.mark.asyncio
async def test_async_insert_and_search(couchbase_db: CouchbaseSearch, test_documents: list[Document]):
    """Test basic async insert and search functionality."""
    # Insert documents
    print(f"Async inserting documents: {test_documents}")
    await couchbase_db.async_insert(test_documents.copy())
    # Allow some time for indexing
    await asyncio.sleep(10)  # Use asyncio.sleep for async tests

    # Verify count - get_count is sync, so we'll assume it reflects async operations for now
    # or we might need an async_get_count if FTS index updates are the bottleneck
    assert couchbase_db.get_count() == len(test_documents)

    # Search for documents
    results = await couchbase_db.async_search("fox jumps", limit=2)
    assert len(results) > 0
    assert isinstance(results[0], Document)
    assert "fox" in results[0].content.lower()


@pytest.mark.asyncio
async def test_async_document_exists(couchbase_db: CouchbaseSearch, test_documents: list[Document]):
    """Test async document existence checks."""
    # Insert one document
    await couchbase_db.async_insert([test_documents.copy()[0]])
    await asyncio.sleep(5)  # Allow time for eventual consistency

    # Check existence
    assert await couchbase_db.async_doc_exists(test_documents[0])
    assert not await couchbase_db.async_doc_exists(test_documents[1])
    assert await couchbase_db.async_name_exists(test_documents[0].name)
    assert not await couchbase_db.async_name_exists(test_documents[1].name)

    # Test async_id_exists
    # We need to calculate the ID as it's done in prepare_doc
    from hashlib import md5

    doc_id_0 = md5(test_documents[0].content.encode("utf-8")).hexdigest()
    doc_id_1 = md5(test_documents[1].content.encode("utf-8")).hexdigest()
    assert await couchbase_db.async_id_exists(doc_id_0)
    assert not await couchbase_db.async_id_exists(doc_id_1)


@pytest.mark.asyncio
async def test_async_upsert(couchbase_db: CouchbaseSearch, test_documents: list[Document]):
    """Test async upsert functionality."""
    # Initial async insert
    await couchbase_db.async_insert([test_documents.copy()[0]])
    await asyncio.sleep(5)  # Allow time for indexing
    initial_count = couchbase_db.get_count()  # get_count is sync

    # Upsert same document with modified content (content is actually the same here for simplicity)
    # The main test is whether async_upsert runs without errors and maintains count.
    modified_doc = Document(
        id=test_documents[0].id,  # id is not used by upsert logic, content hash is
        name=test_documents[0].name,
        content=test_documents[0].content,  # Keeping content same, so it should be an update of existing doc
        meta_data=test_documents[0].meta_data,
    )
    await couchbase_db.async_upsert([modified_doc])
    await asyncio.sleep(5)  # Allow time for indexing

    # Count should remain same
    assert couchbase_db.get_count() == initial_count

    # Search should find the document
    # Since async_upsert in the implementation calls the sync upsert, which then calls prepare_doc,
    # the embedding logic is handled. If async_upsert was fully async, we'd need to ensure embedding.
    results = await couchbase_db.async_search(test_documents[0].content[:10], limit=1)  # search by partial content
    assert len(results) == 1
    assert results[0].name == test_documents[0].name


@pytest.mark.asyncio
async def test_async_create_exists_drop(couchbase_db: CouchbaseSearch):
    """Test async create, exists, and drop functionality."""
    # Note: couchbase_db fixture already calls db.create() (sync)
    # We are testing the async wrappers here. async_create now uses async methods
    # for both collection/scope management and FTS index creation.

    # Test async_exists after initial sync create from fixture
    assert await couchbase_db.async_exists() is True

    # Test async_drop
    await couchbase_db.async_drop()
    assert await couchbase_db.async_exists() is False

    # Test async_create
    # after drop, we rely on the re-creation logic.
    # We also need to ensure the DB object is in a state where create can be called again.
    # The original fixture sets overwrite=True, which helps.
    # The `async_create` method now handles asynchronous creation of both the
    # collection/scope and the FTS index.

    # Let's assume async_create is primarily for ensuring the collection exists and FTS index.
    # We've already dropped it. Now, let's call async_create and check existence.
    # The `couchbase_db` object itself is not recreated, so its internal async client objects
    # initialized by previous operations might be reused or re-initialized as needed by the getter methods.

    # `async_create` gets the async collection and calls the fully async `_async_create_fts_index()`.

    await couchbase_db.async_create()  # This will attempt to get/create collection and create FTS index.
    assert await couchbase_db.async_exists() is True

    # Clean up by calling the original sync delete to ensure the fixture's finally block has a consistent state.
    couchbase_db.delete()  # This is sync, part of the fixture's teardown logic is similar.
    assert await couchbase_db.async_exists() is False  # Should be false after sync delete too.


@pytest.mark.asyncio
async def test_async_cluster_level_index(
    cluster_options: ClusterOptions, search_index: SearchIndex, embedder: OpenAIEmbedder, test_documents: list[Document]
):
    """Test async operations with cluster-level index."""
    db = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string=os.getenv("COUCHBASE_CONNECTION_STRING", ""),
        cluster_options=cluster_options,
        search_index=search_index,
        embedder=embedder,
        overwrite=True,
        is_global_level_index=True,
        wait_until_index_ready=30,
    )

    try:
        await db.async_create()
        assert await db.async_exists() is True

        # Use a document that might align with index expectations (e.g., meta_data.type = "test")
        doc_to_insert = copy.deepcopy(test_documents[0])
        doc_to_insert.name = "async_cluster_doc"  # Give it a unique name for clarity

        await db.async_insert([doc_to_insert])
        await asyncio.sleep(5)  # Allow time for indexing

        # Verify count (optional, get_count is sync)
        # current_count = db.get_count()
        # assert current_count >= 1

        # Verify search works
        results = await db.async_search(doc_to_insert.content[:15], limit=1)
        assert len(results) == 1
        assert results[0].name == doc_to_insert.name
        assert results[0].id == md5(doc_to_insert.content.encode("utf-8")).hexdigest()  # Check ID consistency

    finally:
        # Clean up the collection. The FTS index (if global) might persist,
        # but overwrite=True in constructor should handle it on next run.
        if (
            hasattr(db, "_async_collection") and db._async_collection is not None
        ):  # ensure db was initialized enough to have _async_collection
            if await db.async_exists():
                await db.async_drop()


# Helper mock classes for testing __async_get_doc_from_kv
class MockAsyncSearchRow:
    def __init__(self, id_val, score_val=0.0):
        self.id = id_val
        self.score = score_val

class MockAsyncSearchIndex:
    def __init__(self, rows_data):
        # rows_data is a list of tuples (id_val, score_val)
        self.rows_data = rows_data

    async def rows(self):
        for id_val, score_val in self.rows_data:
            yield MockAsyncSearchRow(id_val, score_val)


@pytest.mark.asyncio
async def test_async_get_doc_from_kv_not_found(couchbase_db: CouchbaseSearch):
    """Test _CouchbaseSearch__async_get_doc_from_kv returns an empty list
       when the ID from search results is not found in the KV store."""
    non_existent_id = "this_id_should_not_exist_in_kv_integration_test"

    # Create a mock AsyncSearchIndex that simulates a search result
    # containing the non-existent ID.
    mock_search_response = MockAsyncSearchIndex(rows_data=[(non_existent_id, 1.0)])

    # Patch the logger to capture warning messages
    from unittest.mock import patch

    with patch("agno.vectordb.couchbase.couchbase.logger") as mock_logger:
        # We directly call the private method as requested by the original test goal,
        # using its mangled name.
        retrieved_documents = await couchbase_db._CouchbaseSearch__async_get_doc_from_kv(mock_search_response)

        # The method should attempt to fetch this ID from KV, fail (as it's non-existent),
        # log a warning (internally), and thus return an empty list of documents.
        assert isinstance(retrieved_documents, list)
        assert len(retrieved_documents) == 0

        # Assert that a warning was logged about the missing document
        found_warning = False
        for call in mock_logger.warning.call_args_list:
            if non_existent_id in str(call) and "not found or error fetching from KV store" in str(call):
                found_warning = True
                break
        assert found_warning, "Expected warning about missing document not found in logger output"
