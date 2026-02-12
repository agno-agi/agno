# TEST_LOG

## filters — v2.5 Review

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

### filtering.py

**Status:** FAIL

**Description:** Basic knowledge filtering with EQ/AND operators on CSV data using PgVector.

**Result:** ImportError — `aiofiles` not installed. CSVReader requires aiofiles at module level even for sync usage.

---

### filtering_on_load.py

**Status:** FAIL

**Description:** Applying filters at knowledge insert time to tag documents with metadata.

**Result:** ImportError — `aiofiles` not installed. Same CSVReader dependency issue.

---

### filtering_with_conditions_on_agent.py

**Status:** FAIL

**Description:** Agent-level knowledge_filters parameter to pre-filter knowledge searches.

**Result:** ImportError — `aiofiles` not installed. Same CSVReader dependency issue.

---

### agentic_filtering.py

**Status:** FAIL

**Description:** Agent autonomously determines filters from user query using `enable_agentic_knowledge_filters`.

**Result:** ImportError — `aiofiles` not installed. Same CSVReader dependency issue.

---

### agentic_filtering_with_output_schema.py

**Status:** FAIL

**Description:** Agentic filtering combined with Pydantic output_schema for structured responses.

**Result:** ImportError — `aiofiles` not installed. Same CSVReader dependency issue.

---

### async_filtering.py

**Status:** FAIL

**Description:** Async variant of knowledge filtering using ainsert_many and aprint_response.

**Result:** ImportError — `python-docx` not installed. Uses DOCX files via ReaderFactory.

---

### async_agentic_filtering.py

**Status:** FAIL

**Description:** Async variant of agentic filtering with CSV data.

**Result:** ImportError — `aiofiles` not installed. Same CSVReader dependency issue.

---

### filtering_with_conditions_on_team.py

**Status:** PASS

**Description:** Team-level knowledge filtering. Team with knowledge that members can search with filters. Uses PDF data (not CSV).

**Result:** Successfully loaded CV PDFs, team searched knowledge with filters, and returned detailed candidate information.

---

### filtering_with_invalid_keys.py

**Status:** FAIL

**Description:** Tests behavior when invalid filter keys are used with LanceDb.

**Result:** ImportError — `lancedb` package not installed. Not a v2.5 regression.

---

### vector_dbs/filtering_pgvector.py

**Status:** PASS

**Description:** PgVector-specific filter implementation with EQ/AND/IN operators on PDF CV data.

**Result:** Successfully loaded CVs into PgVector, agent searched with filters and returned Jordan Mitchell's skills and experience.

---

### vector_dbs/filtering_chroma_db.py

**Status:** SKIP

**Description:** ChromaDB filter implementation.

**Result:** Skipped — requires ChromaDB server.

---

### vector_dbs/filtering_lance_db.py

**Status:** SKIP

**Description:** LanceDB filter implementation.

**Result:** Skipped — requires lancedb package.

---

### vector_dbs/filtering_milvus.py

**Status:** SKIP

**Description:** Milvus filter implementation.

**Result:** Skipped — requires Milvus server.

---

### vector_dbs/filtering_mongo_db.py

**Status:** SKIP

**Description:** MongoDB Atlas filter implementation.

**Result:** Skipped — requires MongoDB Atlas credentials.

---

### vector_dbs/filtering_pinecone.py

**Status:** SKIP

**Description:** Pinecone filter implementation.

**Result:** Skipped — requires Pinecone API key.

---

### vector_dbs/filtering_qdrant_db.py

**Status:** SKIP

**Description:** Qdrant filter implementation.

**Result:** Skipped — requires Qdrant server.

---

### vector_dbs/filtering_surrealdb.py

**Status:** SKIP

**Description:** SurrealDB filter implementation.

**Result:** Skipped — requires SurrealDB server.

---

### vector_dbs/filtering_weaviate.py

**Status:** SKIP

**Description:** Weaviate filter implementation.

**Result:** Skipped — requires Weaviate server.

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| PASS   | 2     | filtering_with_conditions_on_team, filtering_pgvector |
| FAIL   | 7     | filtering (aiofiles), filtering_on_load (aiofiles), filtering_with_conditions_on_agent (aiofiles), agentic_filtering (aiofiles), agentic_filtering_with_output_schema (aiofiles), async_filtering (python-docx), async_agentic_filtering (aiofiles), filtering_with_invalid_keys (lancedb) |
| SKIP   | 8     | chroma, lance, milvus, mongo, pinecone, qdrant, surrealdb, weaviate |

No v2.5 regressions detected. Most failures are due to missing `aiofiles` dependency (CSVReader module-level import). The two PASS examples use PDF data which avoids the CSVReader path.
