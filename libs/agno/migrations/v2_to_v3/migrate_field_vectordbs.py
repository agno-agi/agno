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

# ------------ SurrealDB ------------
# Provide a live SurrealDB client (already connected to the right ns/db).
surrealdb_config: Dict[str, Any] = {
    # "client": None,   # a connected surrealdb client
    # "collections": ["my_collection"],
}
# -----------------------------------

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
    """Add the ``user_id`` field to an existing Milvus collection AND backfill the
    shared sentinel onto every existing entity.

    Two steps:
      1. Add the ``user_id`` field. ``add_collection_field`` can only add a
         *nullable* field to a populated collection, so it is added ``nullable=True``
         here even though a freshly-created v3 collection declares it non-null. The
         backfill immediately fills every row, leaving no nulls behind.
      2. Backfill: stamp ``user_id = "__shared__"`` onto every entity that has no
         owner yet, restoring them to the shared bucket. Safe in place: the shared
         bucket uses the UN-folded primary id (``_scoped_doc_id`` with
         ``user_id=None`` returns the base id), which is exactly the id a pre-v3
         (owner-less) row already has — so no id changes and no duplicate is created.

    Idempotent: entities that already carry a ``user_id`` are left untouched, and a
    collection whose field already exists skips straight to the backfill.

    NOTE: adding a field to an existing collection requires **Milvus 2.6+**
    (``AddCollectionField``). On Milvus 2.5.x and earlier the server has no such
    API — the only option there is to recreate the collection with the new schema
    and re-ingest the data. This function detects the unsupported case and raises a
    clear error rather than a raw gRPC failure.

    Args:
        collection: The Milvus collection name.
    """
    try:
        from pymilvus import DataType, MilvusClient

        from agno.vectordb.milvus.milvus import SHARED_USER_ID_VALUE, USER_ID_FIELD

        client = MilvusClient(uri=milvus_config.get("uri"), token=milvus_config.get("token"))
        if not client.has_collection(collection):
            log_warning(f"Milvus collection '{collection}' not found. Skipping.")
            return

        fields = [f["name"] for f in client.describe_collection(collection)["fields"]]
        if USER_ID_FIELD not in fields:
            log_info(f"Adding {USER_ID_FIELD} field to Milvus collection '{collection}'")
            try:
                client.add_collection_field(
                    collection_name=collection,
                    field_name=USER_ID_FIELD,
                    data_type=DataType.VARCHAR,
                    max_length=256,
                    nullable=True,
                )
            except Exception as add_err:
                if "AddCollectionField" in str(add_err) or "UNIMPLEMENTED" in str(add_err):
                    raise RuntimeError(
                        f"Milvus server does not support adding a field to an existing collection "
                        f"(requires Milvus 2.6+). Recreate collection '{collection}' with the new "
                        f"schema and re-ingest instead."
                    ) from add_err
                raise
        else:
            log_info(f"Milvus collection '{collection}' already has {USER_ID_FIELD}; checking backfill.")

        # Backfill the shared sentinel onto every owner-less entity. Page through
        # the primary keys with a query_iterator so large collections don't load at
        # once, then upsert the sentinel in batches.
        log_info(f"Backfilling {USER_ID_FIELD}='{SHARED_USER_ID_VALUE}' onto owner-less entities in '{collection}'")
        patched = 0
        iterator = client.query_iterator(
            collection_name=collection,
            # Rows whose owner is unset: field absent (pre-migration) or NULL (just added).
            filter=f'{USER_ID_FIELD} == "" or {USER_ID_FIELD} is null',
            output_fields=["*"],
            batch_size=1000,
        )
        try:
            while True:
                batch = iterator.next()
                if not batch:
                    break
                for row in batch:
                    row[USER_ID_FIELD] = SHARED_USER_ID_VALUE
                # upsert by primary id: the id is unchanged, so this rewrites in place.
                client.upsert(collection_name=collection, data=batch)
                patched += len(batch)
        finally:
            iterator.close()

        log_info(f"Successfully migrated Milvus collection '{collection}': backfilled {patched} shared entities.")

    except Exception as e:
        log_error(f"Error migrating Milvus collection {collection}: {e}")
        raise


def migrate_weaviate_collection(collection: str) -> None:
    """Weaviate CANNOT be migrated in place — this refuses with a recreate instruction.

    The adapter filters the shared bucket with ``user_id IS NONE`` (``is_none``), and
    Weaviate only allows an ``is_none`` filter on a property whose collection was
    created with ``index_null_state=True``. That flag is **create-time only**: it
    cannot be added to an existing collection (``Reconfigure.inverted_index()`` has no
    such kwarg, and the raw API returns ``422 IndexNullState cannot be changed``).

    So merely adding the ``user_id`` property — which is all a v2 collection lacks the
    machinery for — produces a WORSE state than doing nothing: the property exists (so
    a naive "is it there?" gate reports "migrated"), but every unscoped query
    ``is_none(user_id)`` then throws ``Nullstate must be indexed to be filterable!``.
    ``content_hash_exists`` runs that filter on every ingest, so ``Knowledge.insert``
    breaks on the collection — and it can't be repaired, only dropped and re-embedded.

    Because the required index setting can't be retrofitted, there is no safe in-place
    migration. The only correct path is to recreate the collection through the v3
    adapter (which creates it with ``index_null_state=True``) and re-ingest the data.
    This function detects the pre-v3 collection and raises that instruction rather than
    creating the broken state.

    Args:
        collection: The Weaviate collection (class) name.
    """
    try:
        import weaviate

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
                log_info(
                    f"Weaviate collection '{collection}' already has {Weaviate.USER_ID_KEY}. "
                    "Assuming it was created by the v3 adapter (with null-state indexing). No migration needed."
                )
                return

            raise RuntimeError(
                f"Weaviate collection '{collection}' predates per-user isolation and cannot be migrated in place: "
                f"the shared-bucket filter needs 'index_null_state=True', which Weaviate only accepts at collection "
                f"creation and refuses to add afterward. Recreate the collection through the v3 Weaviate adapter "
                f"(which sets it) and re-ingest the data. Adding the 'user_id' property alone would break "
                f"Knowledge.insert on the collection irreparably."
            )
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


def migrate_surrealdb_collection(collection: str) -> None:
    """Declare the ``user_id`` field on an existing SurrealDB collection.

    SurrealDB collections are ``SCHEMAFUL``, so the scoped filter (``user_id = X OR
    user_id = NONE``) fails on an existing table that lacks the field. This runs the
    idempotent ``DEFINE FIELD IF NOT EXISTS`` — matching the adapter's own schema —
    so existing records read as NONE = shared.

    Args:
        collection: The SurrealDB table (collection) name.
    """
    try:
        client = surrealdb_config.get("client")
        if client is None:
            log_warning("SurrealDB: provide a connected `client` in surrealdb_config. Skipping.")
            return

        log_info(f"Declaring user_id field on SurrealDB collection '{collection}'")
        client.query(f"DEFINE FIELD IF NOT EXISTS user_id ON {collection} TYPE option<string>;")
        log_info(f"Successfully migrated SurrealDB collection '{collection}'")

    except Exception as e:
        log_error(f"Error migrating SurrealDB collection {collection}: {e}")
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
    """Run the configured schema migrations and optional Qdrant assignments.

    Each store runs independently so one failure does not skip the others, but the
    run FAILS LOUDLY: any store that raises is collected and re-raised at the end,
    so a partial migration is never reported as a success.
    """
    tasks = []
    tasks += [(f"milvus:{n}", lambda n=n: migrate_milvus_collection(n)) for n in milvus_config.get("collections", [])]
    tasks += [
        (f"weaviate:{n}", lambda n=n: migrate_weaviate_collection(n)) for n in weaviate_config.get("collections", [])
    ]
    tasks += [(f"lancedb:{n}", lambda n=n: migrate_lancedb_table(n)) for n in lancedb_config.get("table_names", [])]
    tasks += [
        (f"clickhouse:{n}", lambda n=n: migrate_clickhouse_table(n)) for n in clickhouse_config.get("table_names", [])
    ]
    tasks += [
        (f"surrealdb:{n}", lambda n=n: migrate_surrealdb_collection(n)) for n in surrealdb_config.get("collections", [])
    ]
    if qdrant_config.get("collection") and qdrant_config.get("assignments"):
        for a in qdrant_config["assignments"]:
            tasks.append(
                (
                    f"qdrant:{qdrant_config['collection']}",
                    lambda a=a: assign_qdrant_owner(qdrant_config["collection"], a["point_ids"], a["user_id"]),
                )
            )

    failures = []
    for label, task in tasks:
        try:
            task()
        except Exception as e:
            log_error(f"Migration failed for {label}: {e}")
            failures.append(label)

    log_warning(
        "qdrant and upstash need NO action for v3 isolation (schemaless; absent user_id = shared). "
        "The sentinel backends (couchbase, cassandra, redis) require a separate mandatory backfill "
        "— see migrate_sentinel_vectordbs.py."
    )

    if failures:
        raise RuntimeError(f"Field migration FAILED for: {', '.join(failures)}. Re-run after fixing the cause.")

    log_info("Field VectorDB user-isolation migration completed.")


if __name__ == "__main__":
    run()
