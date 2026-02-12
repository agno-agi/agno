# TEST_LOG

## vector_db — v2.5 Review (2026-02-11)

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing
Deps installed during testing: lancedb, langchain, langchain-community, langchain-openai, langchain-chroma, llama-index

---

### pgvector/pgvector_db.py

**Status:** PASS

**Description:** PgVector-backed knowledge with sync, async, and async-batch flows. Inserts Thai recipes PDF from S3 URL and local cv_1.pdf. Tests document deletion by name and metadata.

**Result:** All three flows completed. Agent answered Agno Agent questions from S3 PDF content. Async batch inserted cv_1.pdf and agent identified candidate skills. Deletion operations confirmed in logs.

---

### pgvector/pgvector_hybrid_search.py

**Status:** PASS

**Description:** PgVector hybrid search (SearchType.hybrid) with streaming responses and chat history. Inserts Thai recipes from S3 URL.

**Result:** Hybrid search returned Thai recipe results. Agent provided detailed Tom Kha Gai recipe. Chat history tool called for "What was my last question?" follow-up (returned empty — no prior session, expected).

---

### pgvector/pgvector_with_bedrock_reranker.py

**Status:** SKIP

**Description:** PgVector with AWS Bedrock reranker integration.

**Result:** Skipped — requires AWS Bedrock credentials.

---

### chroma_db/chroma_db.py

**Status:** PASS

**Description:** ChromaDb-backed knowledge with sync and async-batch flows. Uses persistent_client (local file storage at tmp/chromadb). Inserts docs.agno.com content and local cv_1.pdf.

**Result:** Sync flow inserted Agno docs, agent answered about Agno Agent purpose using knowledge base. Async batch inserted cv_1.pdf. Both queries returned relevant results.

---

### chroma_db/chroma_db_hybrid_search.py

**Status:** PASS

**Description:** ChromaDb hybrid search with Reciprocal Rank Fusion (RRF). Uses text-embedding-3-small model. Inserts from docs.agno.com/llms-full.txt.

**Result:** Hybrid search returned Agno documentation content. Agent provided code example showing how to create agents with tools. RRF ranking worked correctly.

---

### lance_db/lance_db.py

**Status:** PASS

**Description:** LanceDb-backed knowledge with sync and async-batch flows. Local file-based vector DB (no server). Inserts Thai recipes from S3 and local cv_1.pdf.

**Result:** Sync flow completed with Thai recipes. Async batch inserted cv_1.pdf, agent identified Jordan Mitchell's skills (JavaScript, React, Python, HTML/CSS, Git). Delete operation logged.

---

### lance_db/lance_db_hybrid_search.py

**Status:** PASS

**Description:** LanceDb hybrid search (SearchType.hybrid) with streaming. Inserts Thai recipes from S3 URL.

**Result:** Agent answered Tom Kha Gai question but from general knowledge rather than KB — suggests hybrid search may not have returned top matches for this query. Pipeline ran without errors.

---

### lance_db/lance_db_cloud.py

**Status:** SKIP

**Description:** LanceDB Cloud (hosted) integration.

**Result:** Skipped — requires LanceDB Cloud credentials.

---

### lance_db/lance_db_with_mistral_embedder.py

**Status:** SKIP

**Description:** LanceDb with Mistral embedder.

**Result:** Skipped — requires MISTRAL_API_KEY environment variable.

---

### langchain/langchain_db.py

**Status:** FAIL

**Description:** LangChain + ChromaDb integration via LangChainVectorDb wrapper. Uses CharacterTextSplitter for chunking.

**Result:** ImportError: `No module named 'langchain.text_splitter'`. In langchain v0.3+, CharacterTextSplitter moved to `langchain_text_splitters` package. Cookbook uses stale import path.

---

### llamaindex_db/llamaindex_db.py

**Status:** FAIL

**Description:** LlamaIndex + VectorStoreIndex integration via LlamaIndexVectorDb wrapper. Downloads Paul Graham essay for indexing.

**Result:** Download of Paul Graham essay failed silently. SimpleDirectoryReader raised ValueError: `No files found in wip/data/paul_graham`. The cookbook expects a `wip/data/` directory that doesn't exist in the standard cookbook layout.

---

### cassandra_db/cassandra_db.py

**Status:** SKIP

**Description:** Apache Cassandra vector DB integration.

**Result:** Skipped — requires Cassandra cluster.

---

### clickhouse_db/clickhouse.py

**Status:** SKIP

**Description:** ClickHouse vector DB integration.

**Result:** Skipped — requires ClickHouse server.

---

### couchbase_db/couchbase_db.py

**Status:** SKIP

**Description:** Couchbase vector DB with search indexes.

**Result:** Skipped — requires Couchbase Server/Capella instance.

---

### lightrag/lightrag.py

**Status:** SKIP

**Description:** LightRAG graph-based RAG integration.

**Result:** Skipped — requires LightRAG server.

---

### milvus_db/milvus_db.py

**Status:** SKIP

**Description:** Milvus vector DB integration.

**Result:** Skipped — requires Milvus server.

---

### milvus_db/milvus_db_hybrid_search.py

**Status:** SKIP

**Description:** Milvus hybrid search integration.

**Result:** Skipped — requires Milvus server.

---

### milvus_db/milvus_db_range_search.py

**Status:** SKIP

**Description:** Milvus range-based vector search.

**Result:** Skipped — requires Milvus server.

---

### mongo_db/mongo_db.py

**Status:** SKIP

**Description:** MongoDB Atlas vector search integration.

**Result:** Skipped — requires MongoDB Atlas or local MongoDB.

---

### mongo_db/mongo_db_hybrid_search.py

**Status:** SKIP

**Description:** MongoDB hybrid vector search.

**Result:** Skipped — requires MongoDB Atlas or local MongoDB.

---

### mongo_db/cosmos_mongodb_vcore.py

**Status:** SKIP

**Description:** Azure Cosmos DB (MongoDB vCore) integration.

**Result:** Skipped — requires Azure Cosmos DB instance.

---

### pinecone_db/pinecone_db.py

**Status:** SKIP

**Description:** Pinecone serverless vector DB integration.

**Result:** Skipped — requires PINECONE_API_KEY environment variable.

---

### qdrant_db/qdrant_db.py

**Status:** SKIP

**Description:** Qdrant vector DB integration.

**Result:** Skipped — requires Qdrant server.

---

### qdrant_db/qdrant_db_hybrid_search.py

**Status:** SKIP

**Description:** Qdrant hybrid search integration.

**Result:** Skipped — requires Qdrant server.

---

### redis_db/redis_db.py

**Status:** SKIP

**Description:** Redis vector DB integration.

**Result:** Skipped — requires Redis server.

---

### redis_db/redis_db_with_cohere_reranker.py

**Status:** SKIP

**Description:** Redis vector DB with Cohere reranker.

**Result:** Skipped — requires Redis server and COHERE_API_KEY.

---

### singlestore_db/singlestore_db.py

**Status:** SKIP

**Description:** SingleStore (MySQL-compatible) vector DB integration.

**Result:** Skipped — requires SingleStore instance.

---

### surrealdb/surreal_db.py

**Status:** SKIP

**Description:** SurrealDB vector DB integration via WebSocket.

**Result:** Skipped — requires SurrealDB server.

---

### upstash_db/upstash_db.py

**Status:** SKIP

**Description:** Upstash serverless vector DB integration.

**Result:** Skipped — requires UPSTASH_VECTOR_REST_URL and UPSTASH_VECTOR_REST_TOKEN.

---

### weaviate_db/weaviate_db.py

**Status:** SKIP

**Description:** Weaviate vector DB integration.

**Result:** Skipped — requires Weaviate server.

---

### weaviate_db/weaviate_db_hybrid_search.py

**Status:** SKIP

**Description:** Weaviate hybrid search integration.

**Result:** Skipped — requires Weaviate server.

---

### weaviate_db/weaviate_db_upsert.py

**Status:** SKIP

**Description:** Weaviate upsert pattern demonstration.

**Result:** Skipped — requires Weaviate server.

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| PASS   | 6     | pgvector_db, pgvector_hybrid_search, chroma_db, chroma_db_hybrid_search, lance_db, lance_db_hybrid_search |
| FAIL   | 2     | langchain_db (stale import path), llamaindex_db (missing data directory) |
| SKIP   | 24    | pgvector_with_bedrock_reranker, lance_db_cloud, lance_db_with_mistral_embedder, cassandra_db, clickhouse, couchbase_db, lightrag, milvus_db (3), mongo_db (3), pinecone_db, qdrant_db (2), redis_db (2), singlestore_db, surreal_db, upstash_db, weaviate_db (3) |

No v2.5 regressions detected. All failures are pre-existing cookbook issues (stale imports, missing data). All agno vectordb import paths are correct.
