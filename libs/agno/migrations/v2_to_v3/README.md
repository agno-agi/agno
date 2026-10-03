# Vector-DB migration for per-user isolation (v2 → v3)

Agno v3 adds per-user RAG isolation: every stored chunk carries an owner `user_id`, and a
scoped search returns own-OR-shared results. Whether your existing (pre-v3) vector data needs
a migration — and whether one is even possible — depends on the backend. There are three
kinds of migration, one script each:

| Script | Backends | What it does |
| --- | --- | --- |
| `migrate_sql_vectordbs.py` | pgvector, singlestore | Add the `user_id` column to existing tables. |
| `migrate_field_vectordbs.py` | milvus, lancedb, clickhouse, surrealdb | Add the `user_id` field/column/property to existing stores (+ optional Qdrant owner assignment). Milvus also backfills the `"__shared__"` sentinel. Weaviate cannot be migrated in place — the script refuses and tells you to recreate. |
| `migrate_sentinel_vectordbs.py` | redis, couchbase, cassandra | Backfill `user_id = "__shared__"` onto existing vectors. |

Two things decide whether a backend needs work:

- **Schema** — backends that declare `user_id` in a fixed schema only create it when the store
  is first created. Until the field is added to an existing store, the scoped filter either
  fails with a schema error (LanceDB `No field named user_id`, ClickHouse
  `Unknown identifier user_id`) or, on SurrealDB, silently drops new owner-writes.
- **"Shared" representation** — `NULL` / absent / `''` are auto-matched as shared, so existing
  rows stay visible once the field exists. The literal `"__shared__"` sentinel is not
  auto-matched: an existing vector with no `user_id` matches neither side of the filter and is
  invisible until backfilled. Milvus needs both — the field added and the sentinel stamped.

---

## The full matrix

| Backend | `user_id` storage | "shared" = | Existing data on upgrade | Migration |
| --- | --- | --- | --- | --- |
| **pgvector** | SQL column | `NULL` | visible once column exists | schema — `ALTER TABLE ADD COLUMN user_id` |
| **singlestore** | SQL column | `NULL` | visible once column exists | schema — `ALTER TABLE ADD COLUMN user_id` |
| **milvus** | schema field | `"__shared__"` | **invisible** until field added and backfilled | schema + mandatory backfill — `add_collection_field` (Milvus 2.6+) then stamp `"__shared__"` |
| **weaviate** | class property (+ null-state index) | `NULL` | search fails until recreated | **recreate + re-ingest** — cannot migrate in place (see note) |
| **lancedb** | Arrow column | `NULL` | scoped search fails until column exists | schema — `add_columns` |
| **clickhouse** | `String DEFAULT ''` column | `''` | scoped query fails until column exists | schema — `ALTER TABLE ADD COLUMN` |
| **surrealdb** | `SCHEMAFUL` field | `NONE` | visible; new owner-writes silently dropped until field exists | schema — `DEFINE FIELD IF NOT EXISTS` |
| **redis** | hash TAG field | `"__shared__"` | **invisible** until backfilled | data backfill |
| **valkey** | hash TAG field | `"__shared__"` | n/a — shipped with `user_id` from the start | none (see note) |
| **couchbase** | document field + FTS index | `"__shared__"` | **invisible** until backfilled + FTS updated | data backfill (N1QL UPDATE) + FTS index update (see note) |
| **cassandra** | `metadata_s` map | `"__shared__"` | **invisible** until backfilled | data backfill (CQL map update) |
| **qdrant** | payload field (schemaless) | absent | visible | none (optional owner assignment) |
| **upstash** | metadata key (schemaless) | absent | visible | none |
| **mongodb** | document field (schemaless) | `null` / absent | visible | none |
| **pineconedb** | metadata field (schemaless) | absent | visible | none |
| **chromadb** | collection-per-user | base collection | visible | none |
| **opensearch** | dynamic-mapping field | absent | visible | none |
| **lightrag** | — (no per-vector owner) | — | visible; `user_id` ignored, results never scoped | not possible |
| **llamaindex** | — (no per-vector owner) | — | visible; `user_id` ignored, results never scoped | not possible |
| **langchaindb** | — (no per-vector owner) | — | visible; `user_id` ignored, results never scoped | not possible |

> **Milvus note:** v3 switched Milvus from `NULL`-shared to sentinel-shared (`"__shared__"`),
> and its scoped search has no "is null" branch — so a pre-v3 entity is invisible to every
> scoped caller until backfilled. The migration therefore adds the `user_id` field and then
> stamps `"__shared__"` onto every owner-less entity. Adding a field to an existing collection
> requires Milvus 2.6+ (`AddCollectionField`); on 2.5.x and earlier the migration raises a clear
> error and the only option is to recreate the collection with the new schema and re-ingest.

> **Weaviate note (cannot migrate in place):** the shared-bucket filter needs
> `index_null_state=True`, which Weaviate only accepts at collection creation and refuses to add
> afterward. The migration refuses and tells you to recreate the collection through the v3
> adapter (which sets the flag) and re-ingest. Do not add the `user_id` property by hand: the
> collection then reports as migrated while every unscoped query throws
> `Nullstate must be indexed to be filterable!`, and since `content_hash_exists` runs that filter
> on every ingest, `Knowledge.insert` breaks irreparably. A pristine pre-v3 collection keeps
> working until something adds the property.

> **chromadb note:** isolation is by physical collection — a user's chunks go to
> `{collection}__{user_id}` and a scoped search reads the caller's collection plus the base
> collection. Pre-v3 data lives in the base collection, so it stays visible as shared.

> **opensearch note:** mappings are dynamic — a scoped read uses `must_not exists` on `user_id`,
> which matches existing (field-absent) documents, so pre-v3 data stays visible as shared and no
> backfill is needed. The adapter declares `user_id` as a `keyword` on the live index before the
> first owner-write: OpenSearch would otherwise dynamic-map that first value as analyzed `text`,
> a scope filter would match its tokens rather than the owner (`user_id="123"` also matching
> `"team-123"`), and a field's type cannot be changed once set.

> **valkey note (no backfill):** unlike Redis, Valkey shipped with the `user_id` TAG already in
> its index schema (v2.7.3), so no Valkey index predates per-user isolation and there is
> nothing to stamp. The adapter still checks the live schema before a scoped call: an index
> created outside Agno — by a provisioning script or a hand-written `FT.CREATE` — can lack the
> field, and the check turns that into a clear error instead of an empty result set.

> **Couchbase note (FTS index update required):** Couchbase uses a separate FTS (Full-Text Search)
> index for vector search. Stamping `user_id` on documents via N1QL is not enough — the FTS index
> must also be updated to include `user_id` as a keyword-indexed field, otherwise `TermQuery` on
> `user_id` returns 0 results. The migration script updates the FTS index automatically if you
> provide `search_index_name` in the config. If omitted, you must manually add the `user_id` field
> to your FTS index mapping with `analyzer: "keyword"` and wait for reindexing.

> **lightrag / llamaindex / langchaindb:** these wrap an external index and store no per-vector
> `user_id` in Agno, so there is nothing to backfill. They also cannot enforce a scope: a
> `user_id` passed to one of them is logged as unsupported and **ignored**, and the call returns
> the external index's results unscoped — every owner's chunks, not the caller's. Do not rely on
> `user_id` for isolation on these backends. Isolation for those deployments must be handled at
> the external index / application layer, or by using a vector db that supports it natively.

---

## Usage

Each script has a config block at the top. Fill in the connection details for the backend(s)
you use, then run the file:

```bash
python libs/agno/migrations/v2_to_v3/migrate_sql_vectordbs.py
python libs/agno/migrations/v2_to_v3/migrate_field_vectordbs.py
python libs/agno/migrations/v2_to_v3/migrate_sentinel_vectordbs.py
```

All migrations are idempotent — re-running is safe: the schema scripts skip a store that
already has the `user_id` field, and the sentinel backfills skip vectors that already carry a
`user_id`.

> **Weaviate is the one backend that cannot be migrated, by design.** Running the script against
> a pre-v3 collection refuses and changes nothing — that is the expected outcome, not a failure
> of the script. The error message contains the recreate recipe: `vector_db.drop()`,
> `vector_db.create()`, re-ingest with owners. In the batch `run()`, a Weaviate refusal does not
> block the other backends — their migrations still run, and the failure summary lists Weaviate
> for manual follow-up.

Each script also exposes its functions for programmatic use (they are import-safe; the runner
only fires under `if __name__ == "__main__"`), e.g.:

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

- **No data is destroyed.** The schema scripts only add a field/column; the sentinel backfills
  only set an owner on vectors that had none. Existing owners are never overwritten.
- **Ownership backfill is optional** on the NULL/absent-scheme backends: once the field exists,
  existing vectors are already shared. Assign owners only to move specific existing chunks into
  a user's private bucket.
- **ID-folding caveat** (singlestore, milvus, pinecone, mongodb, couchbase, cassandra): these
  fold `user_id` into the vector's primary/record id. Setting an owner field in place satisfies
  search, but the stored id was computed from the shared form — a later scoped re-upsert of the
  same content computes a different id and creates a duplicate. To reassign an owner on these,
  delete and re-insert the chunk under the target user. (Backfilling to the shared sentinel, as
  the mandatory scripts do, is safe: shared uses the un-folded id form.)
