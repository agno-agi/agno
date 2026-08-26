# Per-User RAG Isolation

One knowledge base, a private view per user. Alice and Bob each upload a private
document, a third upload has no owner and is therefore shared, and
`Knowledge.asearch(user_id=...)` scopes retrieval to the caller's own chunks plus the
shared ones. `user_id=None` drops the scope - the admin view.

Every example runs that scenario against a different vector backend, then repeats it
through `Agent(user_id="alice")` and asserts on the documents in `RunOutput.references`.
A dropped `user_id` becomes `None`, which is the admin view, so a broken handoff returns
every user's chunks instead of raising - which is why the examples assert rather than
rely on an error.

## Prerequisites

1. Set `OPENAI_API_KEY`
2. LanceDB, Chroma and Qdrant run embedded - nothing else to start
3. For a server backend, run the matching script: `./cookbook/scripts/run_pgvector.sh`, `run_weaviate.sh`, `run_opensearch.sh`, `run_redis.sh`, `run_valkey.sh`, `run_clickhouse.sh`, `run_cassandra.sh`, `run_couchbase.sh`, `run_surrealdb.sh`, `run_singlestore.sh`
4. For Milvus: `bash standalone_embed.sh start` - Milvus Lite drops scalar fields on the search read path, so this one needs a standalone server
5. For MongoDB: `docker run -d -p 27017:27017 mongodb/mongodb-atlas-local:latest` - plain MongoDB has no `$vectorSearch`
6. For the cloud backends: Pinecone needs `PINECONE_API_KEY`; Upstash needs `UPSTASH_VECTOR_REST_URL` and `UPSTASH_VECTOR_REST_TOKEN` on a 1536-dimension index; SingleStore and Couchbase need their own credential env vars

Redis and Valkey both bind port 6379, so run only one of them at a time.

## Examples

| File | Isolation Primitive |
|------|---------------------|
| [pgvector_db.py](./pgvector_db.py) | Nullable `user_id` column, `WHERE user_id = X OR user_id IS NULL` |
| [lance_db.py](./lance_db.py) | `user_id` column, `.where("user_id = X OR user_id IS NULL", prefilter=True)` |
| [chroma_db.py](./chroma_db.py) | One collection per user (`{base}__{user_id}`), base collection = shared bucket |
| [qdrant_db.py](./qdrant_db.py) | Indexed `user_id` payload field, `should` match + is-empty |
| [milvus_db.py](./milvus_db.py) | `user_id` scalar field, `__shared__` sentinel for unowned chunks |
| [mongo_db.py](./mongo_db.py) | Top-level `user_id` field, `$match {$in: [X, null]}` before `$vectorSearch` |
| [weaviate_db.py](./weaviate_db.py) | `user_id` text property, `where` OR `is_none` |
| [opensearch_db.py](./opensearch_db.py) | `user_id` keyword field, `term` OR `must_not exists` |
| [redis_db.py](./redis_db.py) | `user_id` TAG field, `__shared__` sentinel tag |
| [valkey_db.py](./valkey_db.py) | `user_id` TAG field, `__shared__` sentinel tag |
| [clickhouse_db.py](./clickhouse_db.py) | Non-nullable `String` column, `""` sentinel for shared |
| [cassandra_db.py](./cassandra_db.py) | `user_id` metadata, `__shared__` sentinel for unowned chunks |
| [couchbase_db.py](./couchbase_db.py) | Keyword-indexed FTS `user_id` field, `__shared__` sentinel |
| [singlestore_db.py](./singlestore_db.py) | Nullable `user_id` column, `WHERE user_id = X OR user_id IS NULL` |
| [surreal_db.py](./surreal_db.py) | `user_id` field, dedicated `$scope_user_id` bind |
| [pinecone_db.py](./pinecone_db.py) | `user_id` in vector metadata, `$or [{$eq: X}, {$exists: false}]` filter |
| [upstash_db.py](./upstash_db.py) | `user_id` in metadata, `user_id = X OR HAS NOT FIELD user_id` |

## Running

```bash
.venvs/demo/bin/python cookbook/07_knowledge/04_advanced/07_per_user_isolation/pgvector_db.py
```

Run them one at a time - several share a default port. Each drops its own
collection on startup, so reruns are safe.

## Further Reading

- [Knowledge Overview](https://docs.agno.com/knowledge/overview)
- [Vector Databases](https://docs.agno.com/knowledge/concepts/vector-db)
