# mypy: disable-error-code=var-annotated
"""Backfill the shared-owner sentinel for sentinel-based VectorDBs (v2 -> v3).

v3 adds per-user RAG isolation. Most backends spell "shared / org-wide" as a
NULL/absent ``user_id`` and their scoped search accepts it (``... OR user_id IS
NULL``), so existing data stays visible with no data migration.

Redis, Couchbase and Cassandra are different: they spell "shared" as a LITERAL
sentinel value ``"__shared__"`` written into the ``user_id`` field, and their
scoped search is ``user_id == <caller> OR user_id == "__shared__"`` — there is NO
"field is absent" branch. So a pre-v3 vector (which has NO ``user_id`` field at
all) matches NEITHER side of the filter and becomes INVISIBLE to every scoped
caller after v3 ships.

This script fixes that: it stamps ``user_id = "__shared__"`` onto every existing
vector that has no owner yet, restoring them to the shared bucket so scoped users
keep seeing them. This backfill is MANDATORY for these three backends (unlike the
NULL-scheme SQL backends, where it's optional).

Idempotent: vectors that already carry a ``user_id`` (a real owner or the
sentinel) are left untouched.

Backends: Redis, Couchbase, Cassandra.

Usage: fill in the config block for the backend(s) you use and run the script.
"""

from typing import Any, Dict

from agno.utils.log import log_error, log_info, log_warning

# ------------ Setup for Redis ------------
# Provide EITHER redis_url OR an already-constructed client via redis_config["redis_client"].
redis_config: Dict[str, Any] = {
    # "redis_url": "redis://localhost:6379",
    # "index_names": ["my_index"],   # the RedisDB index_name(s) to migrate
}
# -----------------------------------------

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
# Provide a live cassandra-driver Session (same object you pass to the Cassandra
# adapter), plus the keyspace and table name.
cassandra_config: Dict[str, Any] = {
    # "session": None,          # cassandra.cluster.Session
    # "keyspace": "my_keyspace",
    # "table_name": "my_table",
}
# -----------------------------------------


def migrate_redis_index(index_name: str) -> None:
    """Stamp the shared sentinel onto every Redis vector lacking a ``user_id``.

    Redis stores each vector as a hash under ``{index_name}:{id}`` with ``user_id``
    as a TAG field. Existing (pre-v3) hashes have no such field.

    Args:
        index_name: The RedisDB ``index_name`` whose vectors should be backfilled.
    """
    try:
        from agno.vectordb.redis.redisdb import RedisDB

        log_info(f"Starting shared-sentinel backfill for Redis index: {index_name}")

        # Reuse the adapter only for its client + constants; we scan/patch hashes directly.
        redis_url = redis_config.get("redis_url")
        client = redis_config.get("redis_client")
        if client is None and redis_url is None:
            log_warning("Redis: provide `redis_url` or `redis_client` in redis_config. Skipping.")
            return
        if client is None:
            from redis import Redis

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
            f"Redis index '{index_name}': scanned {scanned} vectors, "
            f"backfilled {patched} with user_id='{sentinel}'."
        )

    except Exception as e:
        log_error(f"Error backfilling Redis index {index_name}: {e}")
        raise


def migrate_couchbase() -> None:
    """Stamp the shared sentinel onto every Couchbase document lacking a ``user_id``.

    Couchbase stores each chunk as a document with a ``user_id`` field; the shared
    bucket uses the literal ``"__shared__"``. Existing docs have no field.
    """
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

        query = (
            f"UPDATE {keyspace} SET {field} = $sentinel "
            f"WHERE {field} IS MISSING OR {field} IS NULL"
        )
        # metrics=True so we can report the real mutation count.
        result = cluster.query(query, QueryOptions(named_parameters={"sentinel": sentinel}, metrics=True))
        # Drain the result so the mutation executes.
        for _ in result.rows():
            pass
        try:
            mutated = int(result.metadata().metrics().mutation_count())
        except Exception:
            mutated = "?"
        log_info(f"Couchbase: backfilled {mutated} documents with {field}='{sentinel}'.")

    except Exception as e:
        log_error(f"Error backfilling Couchbase: {e}")
        raise


def migrate_cassandra() -> None:
    """Stamp the shared sentinel onto every Cassandra chunk lacking a ``user_id``.

    Cassandra (via cassio) stores metadata in a CQL map column ``metadata_s``, keyed
    by string. The adapter scopes search with ``user_id == <caller> OR user_id ==
    "__shared__"`` (no absent branch), so pre-v3 rows — whose ``metadata_s`` has no
    ``user_id`` key — are invisible until backfilled.

    Approach mirrors the adapter's own row handling: scan ``row_id, metadata_s``,
    and for rows missing the key, do an in-place single-key map update
    ``UPDATE ... SET metadata_s['user_id'] = '__shared__' WHERE row_id = ?``. This
    does NOT change the row id, which is correct: the shared bucket uses the
    un-folded id form (see the adapter's ``_scoped_row_id`` — ``user_id=None`` /
    shared is the base id), so no re-embedding or id change is needed.

    Requires ``cassandra_config`` with ``session`` (a live cassandra driver Session),
    ``keyspace`` and ``table_name``.
    """
    try:
        from agno.vectordb.cassandra.cassandra import SHARED_USER_ID_VALUE, USER_ID_METADATA_KEY

        required = ["session", "keyspace", "table_name"]
        if not all(cassandra_config.get(k) for k in required):
            log_warning(
                f"Cassandra: config missing one of {required} (need a live driver `session`). Skipping."
            )
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
    """Run the configured sentinel backfills."""
    try:
        if redis_config.get("index_names"):
            for name in redis_config["index_names"]:
                migrate_redis_index(name)

        if couchbase_config.get("collection_name"):
            migrate_couchbase()

        if cassandra_config.get("table_name"):
            migrate_cassandra()

    except Exception as e:
        log_error(f"Error during migration: {e}")

    log_info("Sentinel VectorDB user-isolation backfill completed.")


if __name__ == "__main__":
    run()