# mypy: disable-error-code=var-annotated
"""Field-scheme VectorDBs: v3 per-user isolation schema migration.

v3 adds per-user RAG isolation (each chunk carries an owner ``user_id``; scoped
search returns own-OR-shared). All backends here spell "shared" as a NULL / absent
/ empty ``user_id`` (so existing owner-less vectors stay VISIBLE — no data
backfill is needed, unlike the sentinel backends). BUT several of them declare
``user_id`` as part of a FIXED schema that is only created when the store is
first created:

    milvus      explicit schema field (hybrid search cannot filter a dynamic
                field, so the adapter declares it) -> existing collection lacks it
    weaviate    class Property, added at collection-create only
    lancedb     fixed Arrow column, not added to an existing table
    clickhouse  ``user_id String DEFAULT ''`` column in CREATE TABLE

For these four, an EXISTING (pre-v3) store has no ``user_id`` field, and the
scoped search filter references it — so the query FAILS with a schema error
(verified: LanceDB ``No field named user_id``; ClickHouse ``Unknown identifier
user_id``; Milvus hybrid-search error). They need a one-time schema add.

Two backends are genuinely schemaless and need NOTHING:
    qdrant      payload field, ``IsEmptyCondition`` matches absent = shared
    upstash     metadata key, ``HAS NOT FIELD`` matches absent = shared

This script adds the ``user_id`` field to existing milvus / weaviate / lancedb /
clickhouse stores. Existing rows read as NULL/'' = shared, so nothing disappears
and no data is rewritten. It also offers an OPTIONAL owner-assignment helper for
Qdrant (clean in-place ``set_payload``; stable point id).

All operations are idempotent — a field that already exists is left as-is.
"""

from typing import Any, Dict, List

from agno.utils.log import log_error, log_info, log_warning

# ------------ Milvus ------------
milvus_config: Dict[str, Any] = {
    # "uri": "http://localhost:19530",   # or a milvus-lite .db path
    # "token": None,
    # "collections": ["my_collection"],
}
# --------------------------------

# ------------ Weaviate ------------
weaviate_config: Dict[str, Any] = {
    # "http_host": "localhost",
    # "http_port": 8080,
    # "collections": ["My_collection"],  # Weaviate class names are capitalized
}
# ----------------------------------

# ------------ LanceDB ------------
lancedb_config: Dict[str, Any] = {
    # "uri": "/path/to/lancedb",
    # "table_names": ["my_table"],
}
# ---------------------------------

# ------------ ClickHouse ------------
clickhouse_config: Dict[str, Any] = {
    # "host": "localhost",
    # "port": 8123,
    # "username": "default",
    # "password": "",
    # "database": "ai",
    # "table_names": ["my_table"],
}
# ------------------------------------

# ------------ OPTIONAL: assign owner for Qdrant points ------------
# Qdrant needs NO schema migration (payload is schemaless, absent = shared).
# This only moves specific existing shared points into a user's private bucket.
qdrant_config: Dict[str, Any] = {
    # "url": "http://localhost:6333",
    # "api_key": None,
    # "collection": "my_collection",
    # "assignments": [
    #     # {"point_ids": ["id1", "id2"], "user_id": "alice"},
    # ],
}
# -----------------------------------------------------------------


def migrate_milvus_collection(collection: str) -> None:
    """Add the ``user_id`` field to an existing Milvus collection.

    Matches the adapter's declaration: VARCHAR(256), nullable. Existing entities
    read as NULL = shared. Required so hybrid search can filter on ``user_id``.

    Args:
        collection: The Milvus collection name.
    """
    try:
        from pymilvus import DataType, MilvusClient

        from agno.vectordb.milvus.milvus import Milvus

        client = MilvusClient(uri=milvus_config.get("uri"), token=milvus_config.get("token"))
        if not client.has_collection(collection):
            log_warning(f"Milvus collection '{collection}' not found. Skipping.")
            return

        fields = [f["name"] for f in client.describe_collection(collection)["fields"]]
        if Milvus.USER_ID_KEY in fields:
            log_info(f"Milvus collection '{collection}' already has {Milvus.USER_ID_KEY}. No migration needed.")
            return

        log_info(f"Adding {Milvus.USER_ID_KEY} field to Milvus collection '{collection}'")
        client.add_collection_field(
            collection_name=collection,
            field_name=Milvus.USER_ID_KEY,
            data_type=DataType.VARCHAR,
            max_length=256,
            nullable=True,
        )
        log_info(f"Successfully migrated Milvus collection '{collection}'")

    except Exception as e:
        log_error(f"Error migrating Milvus collection {collection}: {e}")
        raise


def migrate_weaviate_collection(collection: str) -> None:
    """Add the ``user_id`` property to an existing Weaviate collection (class).

    Args:
        collection: The Weaviate collection (class) name.
    """
    try:
        import weaviate
        from weaviate.classes.config import DataType, Property, Tokenization

        from agno.vectordb.weaviate.weaviate import Weaviate

        client = weaviate.connect_to_local(
            host=weaviate_config.get("http_host", "localhost"),
            port=weaviate_config.get("http_port", 8080),
        )
        try:
            if not client.collections.exists(collection):
                log_warning(f"Weaviate collection '{collection}' not found. Skipping.")
                return

            coll = client.collections.get(collection)
            existing = [p.name for p in coll.config.get().properties]
            if Weaviate.USER_ID_KEY in existing:
                log_info(f"Weaviate collection '{collection}' already has {Weaviate.USER_ID_KEY}. No migration needed.")
                return

            log_info(f"Adding {Weaviate.USER_ID_KEY} property to Weaviate collection '{collection}'")
            coll.config.add_property(
                Property(name=Weaviate.USER_ID_KEY, data_type=DataType.TEXT, tokenization=Tokenization.FIELD)
            )
            log_info(f"Successfully migrated Weaviate collection '{collection}'")
        finally:
            client.close()

    except Exception as e:
        log_error(f"Error migrating Weaviate collection {collection}: {e}")
        raise


def migrate_lancedb_table(table_name: str) -> None:
    """Add the ``user_id`` column to an existing LanceDB table.

    Uses ``add_columns`` with a NULL default so existing rows are shared.

    Args:
        table_name: The LanceDB table name.
    """
    try:
        import lancedb

        from agno.vectordb.lancedb.lance_db import LanceDb

        conn = lancedb.connect(lancedb_config["uri"])
        if table_name not in conn.table_names():
            log_warning(f"LanceDB table '{table_name}' not found. Skipping.")
            return

        table = conn.open_table(table_name)
        if LanceDb.USER_ID_COL in table.schema.names:
            log_info(f"LanceDB table '{table_name}' already has {LanceDb.USER_ID_COL}. No migration needed.")
            return

        log_info(f"Adding {LanceDb.USER_ID_COL} column to LanceDB table '{table_name}'")
        # SQL-expression form: a NULL-valued string column for every existing row.
        table.add_columns({LanceDb.USER_ID_COL: "CAST(NULL AS STRING)"})
        log_info(f"Successfully migrated LanceDB table '{table_name}'")

    except Exception as e:
        log_error(f"Error migrating LanceDB table {table_name}: {e}")
        raise


def migrate_clickhouse_table(table_name: str) -> None:
    """Add the ``user_id`` column to an existing ClickHouse table.

    Matches the adapter: ``String DEFAULT ''`` (empty string = shared), so all
    existing rows become shared automatically.

    Args:
        table_name: The ClickHouse table name.
    """
    try:
        import clickhouse_connect

        client = clickhouse_connect.get_client(
            host=clickhouse_config.get("host", "localhost"),
            port=clickhouse_config.get("port", 8123),
            username=clickhouse_config.get("username", "default"),
            password=clickhouse_config.get("password", ""),
            database=clickhouse_config.get("database", "default"),
        )
        db = clickhouse_config.get("database", "default")

        cols = [r[0] for r in client.query(f"DESCRIBE {db}.{table_name}").result_rows]
        if "user_id" in cols:
            log_info(f"ClickHouse table '{db}.{table_name}' already has user_id. No migration needed.")
            return

        log_info(f"Adding user_id column to ClickHouse table '{db}.{table_name}'")
        client.command(f"ALTER TABLE {db}.{table_name} ADD COLUMN IF NOT EXISTS user_id String DEFAULT ''")
        log_info(f"Successfully migrated ClickHouse table '{db}.{table_name}'")

    except Exception as e:
        log_error(f"Error migrating ClickHouse table {table_name}: {e}")
        raise


def assign_qdrant_owner(collection: str, point_ids: List[str], user_id: str) -> None:
    """Set ``user_id`` on specific existing Qdrant points (optional ownership move).

    In-place ``set_payload``; the point id does not fold ``user_id``, so this is
    idempotent and creates no duplicates.

    Args:
        collection: Qdrant collection name.
        point_ids: The point ids to assign.
        user_id: The owner to set.
    """
    try:
        from qdrant_client import QdrantClient

        from agno.vectordb.qdrant.qdrant import Qdrant

        log_info(f"Assigning user_id='{user_id}' to {len(point_ids)} Qdrant points in '{collection}'")
        client = QdrantClient(url=qdrant_config.get("url"), api_key=qdrant_config.get("api_key"))
        client.set_payload(collection_name=collection, payload={Qdrant.USER_ID_KEY: user_id}, points=point_ids)
        log_info(f"Assigned {len(point_ids)} points to user_id='{user_id}'.")

    except Exception as e:
        log_error(f"Error assigning Qdrant owners in {collection}: {e}")
        raise


def run() -> None:
    """Run the configured schema migrations and optional Qdrant assignments."""
    try:
        for name in milvus_config.get("collections", []):
            migrate_milvus_collection(name)
        for name in weaviate_config.get("collections", []):
            migrate_weaviate_collection(name)
        for name in lancedb_config.get("table_names", []):
            migrate_lancedb_table(name)
        for name in clickhouse_config.get("table_names", []):
            migrate_clickhouse_table(name)

        if qdrant_config.get("collection") and qdrant_config.get("assignments"):
            for a in qdrant_config["assignments"]:
                assign_qdrant_owner(qdrant_config["collection"], a["point_ids"], a["user_id"])

    except Exception as e:
        log_error(f"Error during migration: {e}")

    log_warning(
        "qdrant and upstash need NO action for v3 isolation (schemaless; absent user_id = shared). "
        "The sentinel backends (couchbase, cassandra, redis) require a separate mandatory backfill "
        "— see migrate_sentinel_vectordbs.py."
    )
    log_info("Field VectorDB user-isolation migration completed.")


if __name__ == "__main__":
    run()