# TEST_LOG

## 07_knowledge

No tests recorded yet.

---

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Validated restructured knowledge cookbooks by running the checker across merged quickstart, embedders, and all vector_db backend subdirectories.

**Result:** All checked directories reported 0 violations after restructuring.

---

## 09_archive/filters

### filtering_elasticsearch.py

**Status:** PASS

**Description:** Every metadata filter form against Elasticsearch 9.1.0, index `filtering-cv`: equality on a string, a number and a date string; list and `$in`; numeric and date ranges; two ANDed filters; and a filter matching nothing. Five sample CVs with `user_id`, `document_type`, `year` and `published_on` metadata.

**Result:** All nine filters returned the expected documents. Equality on `published_on="2024-01-15"` matched morgan_lee (this form previously matched nothing, before date detection was turned off), and the date range `gte 2024-07-01` correctly returned casey_jordan, jordan_mitchell and taylor_brooks while excluding the January 2024 and 2023 CVs. The agent, given `knowledge_filters={"user_id": "jordan_mitchell"}`, answered only from his CV.

---

## 09_archive/vector_dbs

### elasticsearch_db.py

**Status:** PASS

**Description:** Sync ingestion and retrieval against Elasticsearch 9.1.0 on localhost:9200, index `recipe`. Thai recipes PDF, default vector search.

**Result:** 14 chunks upserted, retrieval returned the curry recipe and the agent answered from it.

---

### async_elasticsearch_db.py

**Status:** PASS

**Description:** Async ingestion and retrieval, index `recipe_async`. Also exercises `async_close()`.

**Result:** 14 chunks upserted, vector search returned 10 documents, Tom Kha Gai answered from them. No unclosed-connector warning on exit.

---

### elasticsearch_db_hybrid_search.py

**Status:** PASS

**Description:** `search_type=hybrid` on index `recipe_hybrid`, which uses the default `boost` strategy rather than `rrf`.

**Result:** 14 chunks upserted, hybrid search returned 10 documents. Confirms the boost strategy works on a basic licence, which `rrf` does not.

---

### async_elasticsearch_db_with_batch_embedder.py

**Status:** PASS

**Description:** `OpenAIEmbedder(enable_batch=True)` on index `recipes_batch`, so the async path uses `async_get_embeddings_batch_and_usage` for the whole batch.

**Result:** Batch embedding ran ("Getting embeddings and usage for 1 texts in batches of 100 (async)"), upsert succeeded, and the agent answered from the retrieved chunk.

---

### elasticsearch_db_cloud.py

**Status:** NOT RUN

**Description:** Elastic Cloud connection paths - `cloud_id`+`api_key`, `url`+`api_key`, and `url`+`basic_auth` with `ca_certs`.

**Result:** Not executed - needs a hosted Elastic Cloud deployment, which this environment has none. Verified that without `ELASTIC_CLOUD_ID`/`ELASTIC_API_KEY` it exits with an actionable message rather than a stack trace. The adapter's own handling of these arguments is covered by unit tests.

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

### elasticsearch_db.py

**Status:** PASS

**Description:** Elasticsearch 9.1.0 on localhost:9200, index `per_user_isolation_demo`. `user_id` keyword field scoped with `term` OR `must_not exists`, applied inside the `knn` clause so the scope pre-filters.

**Result:** Alice 2 results, Bob 2, admin 3. All assertions passed. Alice's agent, asked for Bob's salary, retrieved nothing of his and answered that it did not know.

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
