# Per-User RAG Isolation

Each example in this directory demonstrates the same scenario — Alice's
private docs, Bob's private docs, and admin-uploaded shared content —
against a different vector backend. The `Knowledge.asearch(user_id=...)`
API is identical across all of them; the backend handles isolation using
whatever native primitive it was designed for.

## Backend matrix

| File           | Backend  | Isolation primitive                                                            | Status   |
| -------------- | -------- | ------------------------------------------------------------------------------ | -------- |
| `pgvector.py`  | PgVector | Top-level `user_id` column, `WHERE user_id = X OR IS NULL`                     | Shipped  |
| `lancedb.py`   | LanceDB  | Top-level `user_id` column, `.where("... OR IS NULL", prefilter=True)`         | Shipped  |
| `chromadb.py`  | Chroma   | One collection per user (`{base}__{user_id}`), base collection = shared bucket | Shipped  |
| `pinecone.py`  | Pinecone | Namespaces (`user_id` → namespace, `__shared__` namespace)                     | Pending  |
| `qdrant.py`    | Qdrant   | Indexed payload + multi-tenant collection                                      | Pending  |
| `weaviate.py`  | Weaviate | Native multi-tenancy mode                                                      | Pending  |
| `milvus.py`    | Milvus   | Partitions                                                                     | Pending  |
| `mongodb.py`   | MongoDB  | Indexed `user_id` field + `$match` before `$vectorSearch`                      | Pending  |

Backends not in this table (Cassandra, ClickHouse, Redis, SingleStore)
haven't been audited yet — they silently accept filters without applying
them in their current Agno wrappers, so isolation would silently leak.
Don't enable `user_isolation=True` against them until their per-backend
work has shipped.

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
