# Per-User RAG Isolation

Each example in this directory demonstrates the same scenario — Alice's
private docs, Bob's private docs, and admin-uploaded shared content —
against a different vector backend. The `Knowledge.asearch(user_id=...)`
API is identical across all of them; the backend handles isolation using
whatever native primitive it was designed for.

## Backend matrix

Every backend stores the owner on each chunk and scopes reads to
`user_id = X OR <unowned>`; the column shape and the "unowned" predicate
differ per backend.

| File               | Backend     | Isolation primitive                                                            |
| ------------------ | ----------- | ------------------------------------------------------------------------------ |
| `pgvector_db.py`   | PgVector    | Nullable `user_id` column, `WHERE user_id = X OR user_id IS NULL`              |
| `lance_db.py`      | LanceDB     | `user_id` column, `.where("user_id = X OR user_id IS NULL", prefilter=True)`   |
| `chroma_db.py`     | Chroma      | One collection per user (`{base}__{user_id}`), base collection = shared bucket |
| `qdrant_db.py`     | Qdrant      | Single collection, indexed `user_id` payload field, `should` match + is-empty  |
| `milvus_db.py`     | Milvus      | Nullable `user_id` field, `user_id == X or user_id is null`                    |
| `mongo_db.py`      | MongoDB     | Top-level `user_id` field, `$match {$in: [X, null]}` before `$vectorSearch`    |
| `weaviate_db.py`   | Weaviate    | `user_id` text property (`tokenization: field`), `where` OR `is_none`          |
| `redis_db.py`      | Redis       | `user_id` TAG field, `(@user_id:{X}) \| ismissing(@user_id)`                   |
| `clickhouse.py`    | ClickHouse  | Non-nullable `String` column, `""` sentinel for shared, bound-param `WHERE`    |
| `cassandra_db.py`  | Cassandra   | `user_id` metadata, `__shared__` sentinel for unowned chunks                   |
| `couchbase_db.py`  | Couchbase   | Keyword-indexed FTS `user_id` field, `__shared__` sentinel (no is-missing)     |
| `singlestore_db.py`| SingleStore | Nullable `user_id` column, `WHERE user_id = X OR user_id IS NULL`              |
| `surreal_db.py`    | SurrealDB   | `user_id` field, dedicated `$scope_user_id` bind (can't collide with filters)  |
| `pinecone_db.py`   | Pinecone    | `user_id` in vector metadata, `$or [{$eq: X}, {$exists: false}]` filter         |
| `upstash_db.py`    | Upstash     | `user_id` in metadata, `user_id = X OR HAS NOT FIELD user_id`                  |

In every case `user_id=None` drops the scope predicate entirely (admin /
unscoped view). Values are always passed as bound parameters or quoted
filter literals — never concatenated into a query string.

## How the API stays uniform

The caller code is the same regardless of backend:

```python
# Upload as Alice
await knowledge.ainsert(path="doc.pdf", user_id="alice")

# Upload as admin (shared)
await knowledge.ainsert(path="company-policy.pdf")

# Search as Alice — sees her own chunks + shared
results = await knowledge.asearch(query="...", user_id="alice")

# Search as admin / debug — sees everything
results = await knowledge.asearch(query="...", user_id=None)
```

Each backend's `search()` implementation translates `user_id` into its
own primitive. You can read the per-backend file to see what that
translation actually looks like — it's all kept in the backend wrapper,
not in the Knowledge class or the cookbook.

## Three-way isolation contract

Every backend implementation must satisfy:

1. **Alice asks about Alice's content** → returns Alice's chunks (and any
   relevant shared chunks).
2. **Alice asks about Bob's content** → returns NO Bob chunks. The
   `assert` in each cookbook verifies this — if isolation breaks, the
   cookbook crashes with a clear error.
3. **Bob asks about shared content** → returns the shared chunks.
4. **Admin (`user_id=None`) asks about anything** → sees everything.

The assertion at step 2 is the canonical isolation test. New backend
cookbooks should keep it verbatim so we have a uniform contract check
across the matrix.
