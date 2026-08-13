"""Integration test for Couchbase v2 → v3 migration.

Requires a running Couchbase server with Search Service enabled:
    ./cookbook/scripts/run_couchbase.sh

This test verifies that:
1. v2 documents (no user_id) are properly stamped with __shared__
2. The FTS index is updated to include user_id field
3. Scoped search returns results after migration
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, Generator

import pytest

# Skip entire module if couchbase not installed
couchbase = pytest.importorskip("couchbase")

from couchbase.auth import PasswordAuthenticator  # noqa: E402
from couchbase.cluster import Cluster  # noqa: E402
from couchbase.exceptions import BucketDoesNotExistException  # noqa: E402
from couchbase.management.buckets import BucketSettings, BucketType  # noqa: E402
from couchbase.management.collections import CollectionSpec  # noqa: E402
from couchbase.management.search import SearchIndex  # noqa: E402
from couchbase.options import ClusterOptions  # noqa: E402
from couchbase.search import SearchRequest, TermQuery  # noqa: E402

if TYPE_CHECKING:
    pass


CB_USER = "Administrator"
CB_PASS = "password"
CB_CONN = "couchbase://localhost"
BUCKET = "migration_integration_test"
SCOPE = "test_scope"
COLLECTION = "test_docs"
INDEX = "test_migration_idx"


def _v2_fts_index() -> SearchIndex:
    """v2-style FTS index WITHOUT user_id field."""
    return SearchIndex(
        name=INDEX,
        source_type="gocbcore",
        idx_type="fulltext-index",
        source_name=BUCKET,
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
                "index_dynamic": False,
                "store_dynamic": False,
                "default_mapping": {"dynamic": True, "enabled": False},
                "types": {
                    f"{SCOPE}.{COLLECTION}": {
                        "dynamic": False,
                        "enabled": True,
                        "properties": {
                            "content": {
                                "enabled": True,
                                "fields": [
                                    {
                                        "docvalues": True,
                                        "index": True,
                                        "name": "content",
                                        "store": True,
                                        "type": "text",
                                    }
                                ],
                            },
                        },
                    }
                },
            },
        },
    )


@pytest.fixture(scope="module")
def couchbase_cluster() -> Generator[Cluster, None, None]:
    """Connect to Couchbase and set up test bucket."""
    try:
        auth = PasswordAuthenticator(CB_USER, CB_PASS)
        cluster = Cluster(CB_CONN, ClusterOptions(auth))
        cluster.wait_until_ready(timedelta(seconds=30))
    except Exception as e:
        pytest.skip(f"Couchbase not available: {e}")

    bucket_mgr = cluster.buckets()

    # Clean up any existing test bucket
    try:
        bucket_mgr.drop_bucket(BUCKET)
        time.sleep(2)
    except BucketDoesNotExistException:
        pass

    # Create test bucket
    try:
        bucket_mgr.create_bucket(BucketSettings(name=BUCKET, ram_quota_mb=256, bucket_type=BucketType.COUCHBASE))
    except Exception as e:
        if "RAM quota" in str(e):
            pytest.skip(f"Couchbase: not enough RAM for test bucket: {e}")
        raise
    time.sleep(3)

    yield cluster

    # Cleanup
    try:
        bucket_mgr.drop_bucket(BUCKET)
    except Exception:
        pass


@pytest.fixture(scope="class")
def setup_v2_data(couchbase_cluster: Cluster):
    """Create v2-style scope, collection, FTS index, and insert test documents."""
    bucket = couchbase_cluster.bucket(BUCKET)
    coll_mgr = bucket.collections()

    # Create scope
    try:
        coll_mgr.create_scope(SCOPE)
    except Exception:
        pass
    time.sleep(1)

    # Create collection
    try:
        coll_mgr.create_collection(CollectionSpec(COLLECTION, SCOPE))
    except Exception:
        pass
    time.sleep(2)

    scope = bucket.scope(SCOPE)
    collection = scope.collection(COLLECTION)

    # Create v2 FTS index (NO user_id)
    search_mgr = scope.search_indexes()
    try:
        search_mgr.drop_index(INDEX)
        time.sleep(2)
    except Exception:
        pass

    search_mgr.upsert_index(_v2_fts_index())
    time.sleep(5)

    # Insert v2 documents (no user_id field)
    collection.upsert("doc1", {"content": "Alice private salary info"})
    collection.upsert("doc2", {"content": "Bob private salary info"})
    collection.upsert("doc3", {"content": "Shared company holidays"})
    time.sleep(3)

    return {
        "cluster": couchbase_cluster,
        "bucket": bucket,
        "scope": scope,
        "collection": collection,
        "search_mgr": search_mgr,
    }


class TestCouchbaseMigration:
    """Test that Couchbase migration fixes FTS scoped search."""

    def test_v2_fts_index_cannot_query_user_id(self, setup_v2_data):
        """Before migration, FTS TermQuery on user_id returns 0 results."""
        scope = setup_v2_data["scope"]

        # Try to search with user_id filter - should return 0 results
        term_query = TermQuery("__shared__", field="user_id")
        request = SearchRequest.create(term_query)

        result = scope.search(INDEX, request, limit=10)
        rows = list(result.rows())

        # v2 FTS index has no user_id field, so TermQuery returns nothing
        assert len(rows) == 0, "v2 FTS index should not be able to query user_id"

    def test_migration_stamps_documents(self, setup_v2_data):
        """Migration stamps user_id='__shared__' on documents."""
        import importlib.util
        from pathlib import Path

        cluster = setup_v2_data["cluster"]

        # Load the migration script
        script_path = Path(__file__).resolve().parents[3] / "migrations" / "v2_to_v3" / "migrate_sentinel_vectordbs.py"
        spec = importlib.util.spec_from_file_location("migrate", script_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Configure and run migration
        mod.couchbase_config["connection_string"] = CB_CONN
        mod.couchbase_config["username"] = CB_USER
        mod.couchbase_config["password"] = CB_PASS
        mod.couchbase_config["bucket_name"] = BUCKET
        mod.couchbase_config["scope_name"] = SCOPE
        mod.couchbase_config["collection_name"] = COLLECTION
        mod.couchbase_config["search_index_name"] = INDEX

        mod.migrate_couchbase()

        # Verify documents have user_id via N1QL
        keyspace = f"`{BUCKET}`.`{SCOPE}`.`{COLLECTION}`"
        result = cluster.query(f"SELECT META().id, user_id FROM {keyspace}")
        rows = list(result.rows())

        assert len(rows) == 3
        for row in rows:
            assert row.get("user_id") == "__shared__", f"Document should have user_id='__shared__': {row}"

    def test_migration_updates_fts_index(self, setup_v2_data):
        """Migration adds user_id field to FTS index mapping."""
        search_mgr = setup_v2_data["search_mgr"]

        # Check FTS index has user_id field now
        index = search_mgr.get_index(INDEX)
        params = index.params or {}
        mapping = params.get("mapping", {})
        types = mapping.get("types", {})
        type_key = f"{SCOPE}.{COLLECTION}"
        properties = types.get(type_key, {}).get("properties", {})

        assert "user_id" in properties, "FTS index should have user_id field after migration"

        user_id_field = properties["user_id"]
        fields = user_id_field.get("fields", [])
        assert len(fields) > 0
        assert fields[0].get("analyzer") == "keyword", "user_id should use keyword analyzer"

    def test_scoped_search_works_after_migration(self, setup_v2_data):
        """After migration, FTS TermQuery on user_id returns results."""
        scope = setup_v2_data["scope"]

        # Wait for FTS to reindex
        time.sleep(5)

        # Now TermQuery should work
        term_query = TermQuery("__shared__", field="user_id")
        request = SearchRequest.create(term_query)

        result = scope.search(INDEX, request, limit=10)
        rows = list(result.rows())

        assert len(rows) == 3, f"Scoped search should return 3 shared documents, got {len(rows)}"
