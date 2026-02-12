# Test Log — vector_db

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| pgvector/pgvector_db.py | PASS | Sync/async/batch flows, agent answered Agno questions |
| pgvector/pgvector_hybrid_search.py | PASS | Hybrid search with streaming, Tom Kha Gai recipe |
| pgvector/pgvector_with_bedrock_reranker.py | SKIP | Missing: AWS Bedrock inference profile |
| cassandra_db/cassandra_db.py | SKIP | Service not available |
| chroma_db/chroma_db.py | SKIP | Service not available |
| chroma_db/chroma_db_hybrid_search.py | SKIP | Service not available |
| clickhouse_db/clickhouse.py | SKIP | Service not available |
| couchbase_db/couchbase_db.py | SKIP | Service not available |
| lance_db/lance_db.py | SKIP | Service not available |
| lance_db/lance_db_cloud.py | SKIP | Service not available |
| lance_db/lance_db_hybrid_search.py | SKIP | Service not available |
| lance_db/lance_db_with_mistral_embedder.py | SKIP | Service not available |
| langchain/langchain_db.py | SKIP | Service not available |
| lightrag/lightrag.py | SKIP | Service not available |
| llamaindex_db/llamaindex_db.py | SKIP | Service not available |
| milvus_db/milvus_db.py | SKIP | Service not available |
| milvus_db/milvus_db_hybrid_search.py | SKIP | Service not available |
| milvus_db/milvus_db_range_search.py | SKIP | Service not available |
| mongo_db/cosmos_mongodb_vcore.py | SKIP | Service not available |
| mongo_db/mongo_db.py | SKIP | Service not available |
| mongo_db/mongo_db_hybrid_search.py | SKIP | Service not available |
| pinecone_db/pinecone_db.py | SKIP | Service not available |
| qdrant_db/qdrant_db.py | SKIP | Service not available |
| qdrant_db/qdrant_db_hybrid_search.py | SKIP | Service not available |
| redis_db/redis_db.py | SKIP | Service not available |
| redis_db/redis_db_with_cohere_reranker.py | SKIP | Service not available |
| singlestore_db/singlestore_db.py | SKIP | Service not available |
| surrealdb/surreal_db.py | SKIP | Service not available |
| upstash_db/upstash_db.py | SKIP | Service not available |
| weaviate_db/weaviate_db.py | SKIP | Service not available |
| weaviate_db/weaviate_db_hybrid_search.py | SKIP | Service not available |
| weaviate_db/weaviate_db_upsert.py | SKIP | Service not available |

## Summary

| Status | Count |
|--------|-------|
| PASS   | 2     |
| SKIP   | 30    |

Only pgvector tested per instructions. All other vector DB providers skipped (services not available).
