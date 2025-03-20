import os
import time
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
        print(f"Created secondary index on name field: idx_name")
        
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
