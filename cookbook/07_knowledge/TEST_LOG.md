# TEST_LOG

## 07_knowledge

No tests recorded yet.

---

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Validated restructured knowledge cookbooks by running the checker across merged quickstart, embedders, and all vector_db backend subdirectories.

**Result:** All checked directories reported 0 violations after restructuring.

---

## 04_advanced/07_per_user_isolation

### check_cookbook_pattern.py

**Status:** PASS

**Description:** `python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/07_knowledge/04_advanced/07_per_user_isolation`.

**Result:** Checked 17 file(s). Violations: 0. `ruff format` and `ruff check` clean over the folder.

---

### cassandra_db.py

**Status:** PASS

**Description:** Cassandra on localhost:9042, keyspace `per_user_demo`, embedder pinned to 1024 dimensions. Owner in chunk metadata with a `__shared__` sentinel.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### chroma_db.py

**Status:** PASS

**Description:** Embedded Chroma at `tmp/per_user_isolation_chromadb`. One collection per user plus a shared base collection.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### clickhouse_db.py

**Status:** PASS

**Description:** ClickHouse on localhost:8123, database `ai`. Non-nullable `String` owner column with `""` as the shared sentinel.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### couchbase_db.py

**Status:** PASS

**Description:** Couchbase on localhost, bucket/scope/collection created by the example, FTS index over a keyword-mapped `user_id` field. Includes a 3-second wait for FTS indexing.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### lance_db.py

**Status:** PASS

**Description:** Embedded LanceDB at `tmp/per_user_isolation_lancedb`. `user_id` column with a prefiltered `user_id = X OR user_id IS NULL` scope.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### milvus_db.py

**Status:** PASS

**Description:** Milvus standalone 2.5.4 on localhost:19530. `user_id` scalar field with a `__shared__` sentinel for unowned chunks. Milvus Lite is not usable here: it drops scalar fields on the search read path.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### mongo_db.py

**Status:** PASS

**Description:** MongoDB Atlas Local, `$match` on `user_id` before `$vectorSearch`. Includes a 10-second wait for the search index to build.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary. A plain `mongo:7` server fails at setup with `no such command: 'createSearchIndexes'` - Atlas Local is required.

---

### opensearch_db.py

**Status:** PASS

**Description:** OpenSearch on localhost:9200, index `per_user_isolation_demo`. `user_id` keyword field scoped with `term` OR `must_not exists`.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### pgvector_db.py

**Status:** PASS

**Description:** PgVector on localhost:5532. Nullable indexed `user_id` column scoped with `WHERE user_id = X OR user_id IS NULL`.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### pinecone_db.py

**Status:** PASS

**Description:** Pinecone serverless index, `user_id` in vector metadata scoped with `$or [{$eq: X}, {$exists: false}]`. Includes a 5-second wait for eventual consistency.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### qdrant_db.py

**Status:** PASS

**Description:** Embedded Qdrant. Indexed `user_id` payload field scoped with a `should` match plus is-empty.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### redis_db.py

**Status:** PASS

**Description:** Redis Stack, `user_id` TAG field with a `__shared__` sentinel tag. Requires the RediSearch module.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary. Against a Valkey server on the same port the scoped search returns 0 results, so the two are not interchangeable.

---

### singlestore_db.py

**Status:** PASS

**Description:** SingleStore over the `SINGLESTORE_*` env vars. Nullable `user_id` column scoped with `WHERE user_id = X OR user_id IS NULL`.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### surreal_db.py

**Status:** PASS

**Description:** SurrealDB on ws://localhost:8000/rpc, namespace `agno`, database `demo`. `user_id` field scoped through a dedicated `$scope_user_id` bind.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### upstash_db.py

**Status:** PASS

**Description:** Upstash Vector over `UPSTASH_VECTOR_REST_URL` / `_TOKEN`, index at 1536 dimensions, cosine. `user_id` in metadata scoped with `user_id = X OR HAS NOT FIELD user_id`. Waits for eventual consistency: 2s after the index reset, 5s after the upserts.

**Result:** Alice 2 results, Bob 2, admin 3, identical across three consecutive runs. All assertions passed; the agent did not state Bob's salary.

---

### valkey_db.py

**Status:** PASS

**Description:** Valkey on localhost:6379, index `per_user_isolation_valkey`. `user_id` TAG field with a `__shared__` sentinel tag. Needs the valkey-bundle image; plain `valkey/valkey` ships no search module, and a stray Redis Stack on 6379 answers the same FT.* commands and fails only on the writes.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---

### weaviate_db.py

**Status:** PASS

**Description:** Weaviate on localhost:8080. `user_id` text property scoped with `where` OR `is_none`.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed; the agent did not state Bob's salary.

---
