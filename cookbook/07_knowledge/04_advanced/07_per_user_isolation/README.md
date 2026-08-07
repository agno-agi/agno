# Per-User RAG Isolation

Every example demonstrates the same scenario against a different vector
backend: Alice and Bob upload private docs, an admin uploads shared
content, and `Knowledge.asearch(user_id=...)` scopes retrieval so each
user sees only their own chunks plus shared ones. `user_id=None` drops
the scope (admin view). An `assert` in each cookbook verifies Bob's
chunks never surface in Alice's results.

## Examples

| File                | Backend     | Isolation primitive                                                            |
| ------------------- | ----------- | ------------------------------------------------------------------------------ |
| `pgvector_db.py`       | PgVector    | Nullable `user_id` column, `WHERE user_id = X OR user_id IS NULL`              |
| `lance_db.py`        | LanceDB     | `user_id` column, `.where("user_id = X OR user_id IS NULL", prefilter=True)`   |
| `chroma_db.py`       | Chroma      | One collection per user (`{base}__{user_id}`), base collection = shared bucket |
| `qdrant_db.py`         | Qdrant      | Single collection, indexed `user_id` payload field, `should` match + is-empty  |
| `milvus_db.py`      | Milvus      | Nullable `user_id` field, `user_id == X or user_id is null`                    |
| `mongo_db.py`       | MongoDB     | Top-level `user_id` field, `$match {$in: [X, null]}` before `$vectorSearch`    |
| `weaviate_db.py`    | Weaviate    | `user_id` text property, `where` OR `is_none`                                  |
| `redis_db.py`       | Redis       | `user_id` TAG field, `__shared__` sentinel tag                                 |
| `clickhouse_db.py`  | ClickHouse  | Non-nullable `String` column, `""` sentinel for shared                         |
| `cassandra_db.py`   | Cassandra   | `user_id` metadata, `__shared__` sentinel for unowned chunks                   |
| `couchbase_db.py`   | Couchbase   | Keyword-indexed FTS `user_id` field, `__shared__` sentinel                     |
| `singlestore_db.py` | SingleStore | Nullable `user_id` column, `WHERE user_id = X OR user_id IS NULL`              |
| `surreal_db.py`     | SurrealDB   | `user_id` field, dedicated `$scope_user_id` bind                               |
| `pinecone_db.py`    | Pinecone    | `user_id` in vector metadata, `$or [{$eq: X}, {$exists: false}]` filter        |
| `upstash_db.py`     | Upstash     | `user_id` in metadata, `user_id = X OR HAS NOT FIELD user_id`                  |

## Prerequisites

Every example needs `OPENAI_API_KEY`. The embedded backends (LanceDB,
Chroma, Qdrant in-memory, Milvus Lite) need nothing else; the rest have a
one-line setup:

| Backend     | Setup                                                                  |
| ----------- | ---------------------------------------------------------------------- |
| PgVector    | `./cookbook/scripts/run_pgvector.sh`                                   |
| Cassandra   | `./cookbook/scripts/run_cassandra.sh`                                  |
| ClickHouse  | `./cookbook/scripts/run_clickhouse.sh`                                 |
| Couchbase   | `./cookbook/scripts/run_couchbase.sh`                                  |
| MongoDB     | `docker run -d -p 27017:27017 mongodb/mongodb-atlas-local:latest`      |
| Redis       | `./cookbook/scripts/run_redis.sh`                                      |
| SingleStore | `./cookbook/scripts/run_singlestore.sh` + `SINGLESTORE_*` env vars     |
| SurrealDB   | `./cookbook/scripts/run_surrealdb.sh`                                  |
| Weaviate    | `./cookbook/scripts/run_weaviate.sh`                                   |
| Pinecone    | `PINECONE_API_KEY` (cloud-hosted)                                      |
| Upstash     | `UPSTASH_VECTOR_REST_URL` + `UPSTASH_VECTOR_REST_TOKEN` (cloud-hosted) |

## Running

```bash
.venvs/demo/bin/python cookbook/07_knowledge/04_advanced/07_per_user_isolation/pgvector_db.py
```
