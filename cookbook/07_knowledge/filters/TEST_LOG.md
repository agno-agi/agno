# Test Log — filters

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| agentic_filtering.py | PASS | Agent autonomously determined filters from query, North America sales data |
| agentic_filtering_with_output_schema.py | PASS | Agentic filtering with Pydantic output_schema for structured response |
| async_agentic_filtering.py | PASS | Async agentic filtering, returned North America sales breakdown |
| async_filtering.py | PASS | Async filtering with DOCX data, returned candidate info |
| filtering.py | PASS | Basic EQ/AND filtering on CSV sales data with PgVector |
| filtering_on_load.py | PASS | Filters applied at insert time to tag documents with metadata |
| filtering_with_conditions_on_agent.py | PASS | Agent-level knowledge_filters, returned EU region sales data |
| filtering_with_conditions_on_team.py | PASS | Team-level filtering, returned detailed candidate information |
| filtering_with_invalid_keys.py | PASS | Invalid filter keys gracefully handled, returned no results |
| vector_dbs/filtering_pgvector.py | PASS | PgVector filtering with EQ/AND/IN operators on CV data |
| vector_dbs/filtering_chroma_db.py | SKIP | Missing: ChromaDB server |
| vector_dbs/filtering_lance_db.py | SKIP | Missing: LanceDB package |
| vector_dbs/filtering_milvus.py | SKIP | Missing: Milvus server |
| vector_dbs/filtering_mongo_db.py | SKIP | Missing: MongoDB Atlas credentials |
| vector_dbs/filtering_pinecone.py | SKIP | Missing: Pinecone API key |
| vector_dbs/filtering_qdrant_db.py | SKIP | Missing: Qdrant server |
| vector_dbs/filtering_surrealdb.py | SKIP | Missing: SurrealDB server |
| vector_dbs/filtering_weaviate.py | SKIP | Missing: Weaviate server |

## Summary

| Status | Count |
|--------|-------|
| PASS   | 10    |
| SKIP   | 8     |

All main filter cookbooks pass. Vector DB-specific filters skipped (services not available except pgvector).
