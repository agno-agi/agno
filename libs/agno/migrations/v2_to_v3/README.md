# Vector-DB migration for per-user isolation (v2 → v3)

Agno v3 adds **per-user RAG isolation**: every stored chunk carries an owner
`user_id`, and scoped search returns *own-OR-shared* results. Whether your
existing (pre-v3) vector data needs a migration — and whether one is even
possible — depends on two things per backend: (1) whether `user_id` needs a
**schema** to exist before it can be stored/filtered, and (2) how the **"shared"**
bucket is spelled.

There are three kinds of migration, one script each:

| Script | Backends | What it does |
| --- | --- | --- |
| `migrate_sql_vectordbs.py` | pgvector, singlestore | Add the `user_id` **column** to existing tables. |
| `migrate_field_vectordbs.py` | milvus, weaviate, lancedb, clickhouse | Add the `user_id` **field/column/property** to existing stores (+ optional Qdrant owner assignment). |
| `migrate_sentinel_vectordbs.py` | redis, couchbase, cassandra | **Backfill** `user_id = "__shared__"` onto existing vectors. |

Two things drive whether a backend needs work:

- **Schema** — backends that declare `user_id` in a fixed schema (SQL column, a
  Milvus/Weaviate field, a LanceDB column) only create it when the store is first
  created. An **existing** store has no such field, and the scoped search filter
  references it, so the query **fails with a schema error** until the field is
  added. (Confirmed live: LanceDB `No field named user_id`; ClickHouse `Unknown
  identifier user_id`; Milvus hybrid-search error.)
- **"Shared" representation** — `NULL` / absent / `''` are auto-matched as shared,
  so existing rows stay visible once the field exists. But `"__shared__"` (a
  literal sentinel used by redis/couchbase/cassandra) is **not** auto-matched: an
  existing vector with no `user_id` matches neither side of the filter and becomes
  **invisible** until backfilled. Those three are the mandatory data backfills.

---

## The full matrix

| Backend | `user_id` storage | "shared" = | Existing data on upgrade | Migration |
| --- | --- | --- | --- | --- |
| **pgvector** | SQL column | `NULL` | visible once column exists | **schema** — `ALTER TABLE ADD COLUMN user_id` |
| **singlestore** | SQL column | `NULL` | visible once column exists | **schema** — `ALTER TABLE ADD COLUMN user_id` |
| **milvus** | schema field | `NULL` | hybrid search fails until field exists | **schema** — `add_collection_field` |
| **weaviate** | class property | `NULL` | search fails until property exists | **schema** — `config.add_property` |
| **lancedb** | Arrow column | `NULL` | scoped search fails until column exists | **schema** — `add_columns` |
| **clickhouse** | `String DEFAULT ''` column | `''` | scoped query fails until column exists | **schema** — `ALTER TABLE ADD COLUMN` |
| **redis** | hash TAG field | `"__shared__"` | **invisible** until backfilled | **data backfill** |
| **couchbase** | document field | `"__shared__"` | **invisible** until backfilled | **data backfill** (N1QL UPDATE) |
| **cassandra** | `metadata_s` map | `"__shared__"` | **invisible** until backfilled | **data backfill** (CQL map update) |
| **qdrant** | payload field (schemaless) | absent | visible | **none** (optional owner assignment) |
| **upstash** | metadata key (schemaless) | absent | visible | **none** |
| **lightrag** | — (external graph) | — | — | **not possible** |
| **llamaindex** | — (external retriever) | — | — | **not possible** |
| **langchaindb** | — (external vectorstore) | — | — | **not possible** |

### Backends where migration is **not possible**

`lightrag`, `llamaindex` and `langchaindb` are **wrappers over external indexes**
(a LightRAG server, a LlamaIndex retriever, a LangChain vectorstore). They do not
store a per-vector `user_id` in Agno at all, so there is nothing to backfill.
Per-user isolation on these fails closed — a scoped call cannot be satisfied — so
there is no migration to run. Isolation for those deployments must be handled at
the external index / application layer.

---

## Usage

Each script has a config block at the top. Fill in the connection details for the
backend(s) you use, then run the file:

```bash
python libs/agno/migrations/v2_to_v3/migrate_sql_vectordbs.py
python libs/agno/migrations/v2_to_v3/migrate_field_vectordbs.py
python libs/agno/migrations/v2_to_v3/migrate_sentinel_vectordbs.py
```

All migrations are **idempotent** — re-running is safe: the schema scripts skip a
store that already has the `user_id` field, and the sentinel backfills skip
vectors that already carry a `user_id`.

Each script also exposes its functions for programmatic use (they are import-safe;
the runner only fires under `if __name__ == "__main__"`), e.g.:

```python
import importlib.util

spec = importlib.util.spec_from_file_location("m", ".../migrate_sentinel_vectordbs.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.redis_config["redis_url"] = "redis://localhost:6379"
m.redis_config["index_names"] = ["my_index"]
m.run()
```

### Notes

- **No data is destroyed.** The schema scripts only add a field/column; the
  sentinel backfills only *set* an owner on vectors that had none. Existing owners
  are never overwritten.
- **Ownership backfill is optional** on the NULL/absent-scheme backends: once the
  field exists, existing vectors are already shared. Assign owners only if you want
  to *move* specific existing chunks into a user's private bucket.
- **ID-folding caveat** (singlestore, milvus, pinecone, mongodb, couchbase,
  cassandra): these fold `user_id` into the vector's primary/record id. Setting an
  owner *field* in place satisfies search, but the stored id was computed from the
  shared form — a later scoped re-upsert of the same content computes a different
  id and creates a duplicate. To **reassign** an owner on these, delete and
  re-insert the chunk under the target user. (Backfilling to the *shared* sentinel,
  as the mandatory scripts do, is safe: shared uses the un-folded id form.)