# mypy: disable-error-code=var-annotated
"""Use this script to backfill the shared-owner sentinel on your VectorDBs (v2 -> v3)

This script works with Redis, Valkey, Couchbase and Cassandra.

v3 adds per-user RAG isolation. These backends spell "shared" as a literal ``user_id``
value ``"__shared__"`` and their scoped search has no "field is absent" branch, so pre-v3
vectors — which carry no ``user_id`` — are invisible to scoped callers until stamped. This
backfill is mandatory for them, and idempotent: vectors that already carry a ``user_id``
are left untouched.

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
    # "index_names": ["my_index"],   # the RedisDB index_name(s) to migrate
}
# -----------------------------------------

# ------------ Setup for Valkey ------------
# Valkey is Redis-compatible; provide a valkey/redis URL or a client.
valkey_config: Dict[str, Any] = {
    # "valkey_url": "redis://localhost:6379",
    # "valkey_client": None,
    # "index_names": ["my_index"],
}
# ------------------------------------------

# ------------ Setup for Couchbase ------------
couchbase_config: Dict[str, Any] = {
    # "connection_string": "couchbase://localhost",
    # "username": "Administrator",
    # "password": "password",
    # "bucket_name": "my_bucket",
    # "scope_name": "my_scope",
    # "collection_name": "my_collection",
    # "search_index_name": "my_fts_index",
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


def migrate_redis_index(index_name: str) -> None:
    """Stamp the shared sentinel onto every Redis vector lacking a ``user_id``.

    Args:
        index_name: The RedisDB ``index_name`` whose vectors should be backfilled.
    """
    try:
        from agno.vectordb.redis.redisdb import RedisDB

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

        field = RedisDB.USER_ID_FIELD
        sentinel = RedisDB.SHARED_OWNER_TAG

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


def migrate_valkey_index(index_name: str) -> None:
    """Stamp the shared sentinel onto every Valkey vector lacking a ``user_id``.

    Args:
        index_name: The ValkeyDb ``index_name`` whose vectors should be backfilled.
    """
    try:
        from agno.vectordb.valkey.valkeydb import ValkeyDB

        log_info(f"Starting shared-sentinel backfill for Valkey index: {index_name}")

        valkey_url = valkey_config.get("valkey_url")
        client = valkey_config.get("valkey_client")
        if client is None and valkey_url is None:
            log_warning("Valkey: provide `valkey_url` or `valkey_client` in valkey_config. Skipping.")
            return
        if client is None:
            from redis import Redis

            assert valkey_url is not None  # narrows for the type checker
            client = Redis.from_url(valkey_url)

        field = ValkeyDB.USER_ID_FIELD
        sentinel = ValkeyDB.SHARED_OWNER_TAG

        patched = 0
        scanned = 0
        for key in client.scan_iter(match=f"{index_name}:*", count=1000):
            scanned += 1
            existing = client.hget(key, field)
            if existing in (None, b"", ""):
                client.hset(key, field, sentinel)
                patched += 1

        log_info(
            f"Valkey index '{index_name}': scanned {scanned} vectors, backfilled {patched} with user_id='{sentinel}'."
        )

    except Exception as e:
        log_error(f"Error backfilling Valkey index {index_name}: {e}")
        raise


def migrate_couchbase() -> None:
    """Stamp the shared sentinel onto every Couchbase document lacking a ``user_id``."""
    try:
        from datetime import timedelta

        from couchbase.auth import PasswordAuthenticator
        from couchbase.cluster import Cluster
        from couchbase.options import ClusterOptions

        from agno.vectordb.couchbase.couchbase import CouchbaseSearch

        required = ["connection_string", "username", "password", "bucket_name", "scope_name", "collection_name"]
        if not all(couchbase_config.get(k) for k in required):
            log_warning(f"Couchbase: config missing one of {required}. Skipping.")
            return

        field = CouchbaseSearch.USER_ID_FIELD
        sentinel = CouchbaseSearch.SHARED_USER_ID

        log_info(
            f"Starting shared-sentinel backfill for Couchbase "
            f"{couchbase_config['bucket_name']}.{couchbase_config['scope_name']}.{couchbase_config['collection_name']}"
        )

        auth = PasswordAuthenticator(couchbase_config["username"], couchbase_config["password"])
        cluster = Cluster(couchbase_config["connection_string"], ClusterOptions(auth))
        cluster.wait_until_ready(timedelta(seconds=10))

        keyspace = (
            f"`{couchbase_config['bucket_name']}`.`{couchbase_config['scope_name']}`."
            f"`{couchbase_config['collection_name']}`"
        )
        # N1QL UPDATE only rows that don't yet have the owner field -> idempotent.
        from couchbase.options import QueryOptions

        query = f"UPDATE {keyspace} SET {field} = $sentinel WHERE {field} IS MISSING OR {field} IS NULL"
        result = cluster.query(query, QueryOptions(named_parameters={"sentinel": sentinel}, metrics=True))
        # Drain the result so the mutation executes.
        for _ in result.rows():
            pass
        try:
            mutated = str(int(result.metadata().metrics().mutation_count()))
        except Exception:
            mutated = "?"
        log_info(f"Couchbase: backfilled {mutated} documents with {field}='{sentinel}'.")

    except Exception as e:
        log_error(f"Error backfilling Couchbase: {e}")
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
    for name in valkey_config.get("index_names", []):
        tasks.append((f"valkey:{name}", partial(migrate_valkey_index, name)))
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
