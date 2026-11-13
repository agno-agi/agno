# mypy: disable-error-code=var-annotated
"""Use this script to backfill the shared-owner sentinel on your VectorDBs (v2 -> v3)

This script works with Redis, Couchbase and Cassandra.

v3 adds per-user RAG isolation. These backends spell "shared" as a literal ``user_id``
value ``"__shared__"`` and their scoped search has no "field is absent" branch, so pre-v3
vectors — which carry no ``user_id`` — are invisible to scoped callers until stamped. This
backfill is mandatory for them, and idempotent: vectors that already carry a ``user_id``
are left untouched.

Valkey is not listed: it shipped with the ``user_id`` TAG in its schema from the start
(v2.7.3), so no Valkey index predates per-user isolation and there is nothing to
backfill.

To use the script simply:
- Fill in the config block for the backend(s) you use
- Run the script
"""

from functools import partial
from typing import Any, Callable, Dict, List, Tuple

from agno.utils.log import log_error, log_info, log_warning

# ------------ Setup for Redis ------------
# Provide EITHER redis_url OR an already-constructed client via redis_config["redis_client"].
redis_config: Dict[str, Any] = {
    # "redis_url": "redis://localhost:6379",
    # "index_names": ["my_index"],   # the RedisDb index_name(s) to migrate
}
# -----------------------------------------

# ------------ Setup for Couchbase ------------
# The FTS index MUST be updated to include user_id for scoped search to work.
# Provide the search_index_name so the migration can add user_id to its mapping.
couchbase_config: Dict[str, Any] = {
    # "connection_string": "couchbase://localhost",
    # "username": "Administrator",
    # "password": "password",
    # "bucket_name": "my_bucket",
    # "scope_name": "my_scope",
    # "collection_name": "my_collection",
    # "search_index_name": "my_fts_index",  # Required: FTS index to update
}
# -----------------------------------------

# ------------ Setup for Cassandra ------------
# Provide a live cassandra-driver Session, plus the keyspace and table name.
cassandra_config: Dict[str, Any] = {
    # "session": None,          # cassandra.cluster.Session
    # "keyspace": "my_keyspace",
    # "table_name": "my_table",
}
# -----------------------------------------


def _decode(value: Any) -> Any:
    """FT.INFO answers in bytes on some clients and str on others."""
    return value.decode() if isinstance(value, bytes) else value


def _indexed_vector_dimensions(info: Any) -> Any:
    """Read the vector dimension out of an FT.INFO payload.

    The rebuilt schema has to keep the dimension the stored vectors were written with:
    the adapter takes it from the embedder, so a migration run with a different (or
    default) embedder would otherwise silently orphan every stored vector.

    Returns None when the payload has no vector attribute to read.
    """
    items = info.items() if hasattr(info, "items") else []
    for key, value in items:
        if _decode(key) != "attributes":
            continue
        for attribute in value:
            flat = [_decode(entry) for entry in attribute]
            if "VECTOR" not in flat:
                continue
            for entry in flat:
                # The vector params arrive as a nested [name, value, ...] sequence
                if isinstance(entry, (list, tuple)):
                    params = [_decode(param) for param in entry]
                    if "dimensions" in params:
                        return params[params.index("dimensions") + 1]
            if "dim" in flat:
                return flat[flat.index("dim") + 1]
    return None


def migrate_redis_index(index_name: str) -> None:
    """Stamp the shared sentinel onto every Redis vector lacking a ``user_id``.

    Args:
        index_name: The RedisDb ``index_name`` whose vectors should be backfilled.
    """
    try:
        from agno.vectordb.redis.redisdb import RedisDb

        log_info(f"Starting shared-sentinel backfill for Redis index: {index_name}")

        # Only the adapter's field constants are needed; hashes are scanned and patched directly.
        redis_url = redis_config.get("redis_url")
        client = redis_config.get("redis_client")
        if client is None and redis_url is None:
            log_warning("Redis: provide `redis_url` or `redis_client` in redis_config. Skipping.")
            return
        if client is None:
            from redis import Redis

            assert redis_url is not None  # narrows for the type checker
            client = Redis.from_url(redis_url)

        field = RedisDb.USER_ID_FIELD
        sentinel = RedisDb.SHARED_OWNER_TAG

        patched = 0
        scanned = 0
        # Vectors live under "{index_name}:*"; iterate without blocking Redis.
        for key in client.scan_iter(match=f"{index_name}:*", count=1000):
            scanned += 1
            existing = client.hget(key, field)
            if existing in (None, b"", ""):  # missing or empty -> stamp shared
                client.hset(key, field, sentinel)
                patched += 1

        log_info(
            f"Redis index '{index_name}': scanned {scanned} vectors, backfilled {patched} with user_id='{sentinel}'."
        )

    except Exception as e:
        log_error(f"Error backfilling Redis index {index_name}: {e}")
        raise

    # A pre-v3 index has no ``user_id`` TAG in its schema,
    # so the scope filter still matches nothing. The schema is fixed at FT.CREATE, so it has
    # to be dropped and rebuilt. The vectors are already stamped at this point, so a failure
    # here is reported rather than raised — it must not undo a backfill that succeeded.
    try:
        db = RedisDb(index_name=index_name, redis_url=redis_url, redis_client=client)
        if db._index_has_user_id_field():
            log_info(f"Redis index '{index_name}': schema already has '{field}'. No rebuild needed.")
            return

        # The rebuilt schema must keep the dimension the stored vectors were written with.
        # It comes from the embedder, so read it off the live index rather than defaulting.
        live_dimensions = _indexed_vector_dimensions(db.index.info())
        if live_dimensions is None:
            raise ValueError("could not read the vector dimension from the live index")
        if live_dimensions != db.dimensions:
            log_info(f"Redis index '{index_name}': preserving the live vector dimension {live_dimensions}.")
            db.dimensions = live_dimensions
            # RedisDb snapshots its schema in __init__, so the new dimension only reaches
            # FT.CREATE if the schema and the index built from it are regenerated here.
            db.schema = db._get_schema()
            db.index = db._create_index()

        log_info(f"Redis index '{index_name}': rebuilding schema to add the '{field}' field...")
        # drop=False is FT.DROPINDEX without DD: it removes the schema and leaves every
        # hash in place. ``drop()`` on the adapter would delete the vectors as well.
        db.index.delete(drop=False)
        db._owner_field_exists = None
        db.create()
        log_info(f"Redis index '{index_name}': schema rebuilt; scoped search is now available.")
    except Exception as e:
        log_warning(
            f"Redis index '{index_name}': vectors are stamped, but the index schema could not be "
            f"rebuilt ({e}). Scoped search stays unavailable until the index carries the "
            f"'{field}' field: recreate it from your own RedisDb instance (same embedder), which "
            "rebuilds the schema without touching the stored vectors."
        )


def migrate_couchbase() -> None:
    """Stamp the shared sentinel onto Couchbase documents and update the FTS index.

    Two steps are required for Couchbase migration:
    1. N1QL UPDATE to stamp user_id='__shared__' on existing documents
    2. FTS index update to add user_id field so TermQuery can filter on it

    Without step 2, scoped search returns 0 results because FTS cannot query
    a field that is not in its index mapping.
    """
    try:
        from copy import deepcopy
        from datetime import timedelta
        from time import sleep

        from couchbase.auth import PasswordAuthenticator
        from couchbase.cluster import Cluster
        from couchbase.management.search import SearchIndex
        from couchbase.options import ClusterOptions

        from agno.vectordb.couchbase.couchbase import CouchbaseSearch

        required = ["connection_string", "username", "password", "bucket_name", "scope_name", "collection_name"]
        if not all(couchbase_config.get(k) for k in required):
            log_warning(f"Couchbase: config missing one of {required}. Skipping.")
            return

        field = CouchbaseSearch.USER_ID_FIELD
        sentinel = CouchbaseSearch.SHARED_USER_ID
        bucket_name = couchbase_config["bucket_name"]
        scope_name = couchbase_config["scope_name"]
        collection_name = couchbase_config["collection_name"]
        search_index_name = couchbase_config.get("search_index_name")

        log_info(f"Starting Couchbase migration for {bucket_name}.{scope_name}.{collection_name}")

        auth = PasswordAuthenticator(couchbase_config["username"], couchbase_config["password"])
        cluster = Cluster(couchbase_config["connection_string"], ClusterOptions(auth))
        cluster.wait_until_ready(timedelta(seconds=10))

        # 1. N1QL UPDATE only rows that don't yet have the owner field -> idempotent
        keyspace = f"`{bucket_name}`.`{scope_name}`.`{collection_name}`"
        from couchbase.options import QueryOptions

        query = f"UPDATE {keyspace} SET {field} = $sentinel WHERE {field} IS MISSING OR {field} IS NULL"
        result = cluster.query(query, QueryOptions(named_parameters={"sentinel": sentinel}, metrics=True))
        # Drain the result so the mutation executes
        for _ in result.rows():
            pass
        try:
            mutated = str(int(result.metadata().metrics().mutation_count()))
        except Exception:
            mutated = "?"
        log_info(f"Couchbase: backfilled {mutated} documents with {field}='{sentinel}'.")

        # 2. Update FTS index to include user_id field
        if not search_index_name:
            log_warning(
                "Couchbase: search_index_name not provided. Documents are stamped but FTS index "
                "was NOT updated. Scoped search will return 0 results until you manually add "
                f"the '{field}' field to your FTS index mapping with analyzer='keyword'."
            )
            return

        bucket = cluster.bucket(bucket_name)
        scope = bucket.scope(scope_name)
        search_mgr = scope.search_indexes()

        try:
            existing_index = search_mgr.get_index(search_index_name)
        except Exception as e:
            log_warning(f"Couchbase: could not fetch FTS index '{search_index_name}': {e}. Skipping FTS update.")
            return

        # Check if user_id already exists ANYWHERE in the mapping
        params = existing_index.params or {}
        mapping = params.get("mapping", {})
        types = mapping.get("types", {})
        default_mapping = mapping.get("default_mapping", {})

        def has_field_in_properties(props: dict) -> bool:
            return field in props

        # Check all type mappings
        for type_name, type_def in types.items():
            if has_field_in_properties(type_def.get("properties", {})):
                log_info(
                    f"Couchbase: FTS index '{search_index_name}' already has '{field}' in type '{type_name}'. No update needed."
                )
                return

        # Check default_mapping
        if has_field_in_properties(default_mapping.get("properties", {})):
            log_info(
                f"Couchbase: FTS index '{search_index_name}' already has '{field}' in default_mapping. No update needed."
            )
            return

        # Detect which mapping mode the index uses
        doc_config = params.get("doc_config", {})
        mode = doc_config.get("mode", "scope.collection.type_field")

        # Find where to add user_id based on existing mappings
        target_type_key = None
        if types:
            # Use the first existing type mapping (user's actual index structure)
            target_type_key = next(iter(types.keys()))
        elif default_mapping.get("enabled"):
            # Index uses default_mapping mode
            target_type_key = None  # Will add to default_mapping
        else:
            # Fallback to scope.collection convention
            target_type_key = f"{scope_name}.{collection_name}"

        log_info(
            f"Couchbase: adding '{field}' field to FTS index '{search_index_name}' "
            f"(target: {target_type_key or 'default_mapping'}, mode: {mode})..."
        )

        user_id_field_def = {
            "enabled": True,
            "fields": [
                {
                    "docvalues": True,
                    "include_in_all": False,
                    "include_term_vectors": False,
                    "index": True,
                    "name": field,
                    "store": True,
                    "analyzer": "keyword",
                    "type": "text",
                }
            ],
        }

        # Build updated index definition
        updated_params = deepcopy(params)
        if "mapping" not in updated_params:
            updated_params["mapping"] = {}

        if target_type_key is None:
            # Add to default_mapping
            if "default_mapping" not in updated_params["mapping"]:
                updated_params["mapping"]["default_mapping"] = {"dynamic": True, "enabled": True, "properties": {}}
            if "properties" not in updated_params["mapping"]["default_mapping"]:
                updated_params["mapping"]["default_mapping"]["properties"] = {}
            updated_params["mapping"]["default_mapping"]["properties"][field] = user_id_field_def
        else:
            # Add to specific type mapping
            if "types" not in updated_params["mapping"]:
                updated_params["mapping"]["types"] = {}
            if target_type_key not in updated_params["mapping"]["types"]:
                updated_params["mapping"]["types"][target_type_key] = {
                    "dynamic": False,
                    "enabled": True,
                    "properties": {},
                }
            if "properties" not in updated_params["mapping"]["types"][target_type_key]:
                updated_params["mapping"]["types"][target_type_key]["properties"] = {}
            updated_params["mapping"]["types"][target_type_key]["properties"][field] = user_id_field_def

        updated_index = SearchIndex(
            name=existing_index.name,
            source_type=existing_index.source_type,
            idx_type=existing_index.idx_type,
            source_name=existing_index.source_name,
            uuid=existing_index.uuid,
            plan_params=existing_index.plan_params,
            params=updated_params,
        )

        search_mgr.upsert_index(updated_index)
        log_info(f"Couchbase: FTS index '{search_index_name}' updated with '{field}' field.")

        # Wait for index to reprocess documents
        log_info("Couchbase: waiting for FTS index to reindex documents (this may take a moment)...")
        sleep(5)
        log_info("Couchbase: migration complete. FTS scoped search should now work.")

    except Exception as e:
        log_error(f"Error migrating Couchbase: {e}")
        raise


def migrate_cassandra() -> None:
    """Stamp the shared sentinel onto every Cassandra chunk lacking a ``user_id``.

    Cassandra (via cassio) keeps metadata in the CQL map column ``metadata_s``, so the
    backfill is an in-place single-key map update and leaves ``row_id`` untouched.
    """
    try:
        from agno.vectordb.cassandra.cassandra import SHARED_USER_ID_VALUE, USER_ID_METADATA_KEY

        required = ["session", "keyspace", "table_name"]
        if not all(cassandra_config.get(k) for k in required):
            log_warning(f"Cassandra: config missing one of {required} (need a live driver `session`). Skipping.")
            return

        session = cassandra_config["session"]
        keyspace = cassandra_config["keyspace"]
        table = cassandra_config["table_name"]
        full = f"{keyspace}.{table}"

        log_info(f"Starting shared-sentinel backfill for Cassandra {full}")

        # Full scan (cassio metadata isn't efficiently filterable for "missing key").
        rows = session.execute(f"SELECT row_id, metadata_s FROM {full}")
        update_cql = f"UPDATE {full} SET metadata_s[%s] = %s WHERE row_id = %s"

        patched = 0
        scanned = 0
        for row in rows:
            scanned += 1
            metadata_s = getattr(row, "metadata_s", None) or {}
            if metadata_s.get(USER_ID_METADATA_KEY) in (None, ""):
                session.execute(
                    update_cql,
                    (USER_ID_METADATA_KEY, SHARED_USER_ID_VALUE, getattr(row, "row_id")),
                )
                patched += 1

        log_info(
            f"Cassandra {full}: scanned {scanned} rows, backfilled {patched} "
            f"with metadata_s['{USER_ID_METADATA_KEY}']='{SHARED_USER_ID_VALUE}'."
        )

    except Exception as e:
        log_error(f"Error backfilling Cassandra: {e}")
        raise


def run() -> None:
    """Run the configured sentinel backfills.

    Each backend runs independently; failures are collected and re-raised at the end so a
    partial backfill is not reported as a success.
    """
    tasks: List[Tuple[str, Callable[[], None]]] = []
    for name in redis_config.get("index_names", []):
        tasks.append((f"redis:{name}", partial(migrate_redis_index, name)))
    if couchbase_config.get("collection_name"):
        tasks.append(("couchbase", migrate_couchbase))
    if cassandra_config.get("table_name"):
        tasks.append(("cassandra", migrate_cassandra))

    failures = []
    for label, task in tasks:
        try:
            task()
        except Exception as e:
            log_error(f"Backfill failed for {label}: {e}")
            failures.append(label)

    if failures:
        raise RuntimeError(
            f"Sentinel backfill FAILED for: {', '.join(failures)}. "
            "Those stores' legacy vectors remain invisible to scoped searches until re-run."
        )

    log_info("Sentinel VectorDB user-isolation backfill completed.")


if __name__ == "__main__":
    run()
