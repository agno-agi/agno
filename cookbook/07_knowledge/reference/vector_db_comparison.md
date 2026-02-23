# Vector Database Comparison

Feature matrix for all supported vector databases.

## Quick Recommendation

| Use Case | Recommended DB | Why |
|----------|---------------|-----|
| Production | PgVector | Full SQL, reliable, hybrid search, reranking |
| Local Dev | LanceDB or ChromaDB | No server needed, file-based |
| Managed Cloud | Pinecone or Qdrant | Zero ops, auto-scaling |

## Feature Matrix

| Database | Search Types | Reranking | Filters | Scale | Setup |
|----------|-------------|-----------|---------|-------|-------|
| PgVector | vector, keyword, hybrid | Yes | Full | Medium-Large | Docker |
| LanceDB | vector, keyword, hybrid | Yes | Full | Small-Medium | pip install |
| ChromaDB | vector | No | Basic | Small | pip install |
| Pinecone | vector | No | Full | Large | Cloud account |
| Qdrant | vector, hybrid | No | Full | Large | Cloud or Docker |
| Milvus | vector, hybrid | No | Full | Large | Docker |
| Weaviate | vector, hybrid | No | Full | Large | Docker |
| Redis | vector | No | Basic | Medium | Docker |
| MongoDB | vector | No | Full | Large | Docker |
| SingleStore | vector | No | Full | Large | Cloud |
| Cassandra | vector | No | Basic | Large | Docker |
| ClickHouse | vector | No | Full | Large | Docker |
| Couchbase | vector | No | Full | Large | Docker |
| SurrealDB | vector | No | Basic | Medium | Docker |

## Notes

- **Hybrid search** combines vector similarity with keyword (BM25) matching for better results
- **Reranking** uses a second model to re-score results after initial retrieval
- **Filters** refer to metadata-based filtering support
- All databases use the same Knowledge API - switching databases only requires changing the vector_db parameter
