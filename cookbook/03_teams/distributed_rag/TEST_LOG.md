# Test Log: distributed_rag

> Updated: 2026-02-11

### 01_distributed_rag_pgvector.py

**Status:** PASS

**Description:** Demonstrates distributed team-based RAG using PostgreSQL + pgvector with 4 member agents (Vector Retriever, Hybrid Searcher, Data Validator, Response Composer). Runs sync demo by default, querying Thai recipes PDF.

**Result:** Completed successfully. Knowledge inserted into both vector and hybrid PgVector tables, team coordinated retrieval and produced comprehensive recipe guidance. Duration ~30s.

---

### 02_distributed_rag_lancedb.py

**Status:** PASS

**Description:** Demonstrates distributed RAG with LanceDB using primary (vector) and context (hybrid) knowledge bases. 4 member agents with async demo by default.

**Result:** Completed successfully after installing `tantivy` for LanceDB hybrid search. Knowledge inserted into both LanceDB tables, async team coordination produced detailed Thai recipe with cooking tips and variations. Prior run (2026-02-08) failed due to missing `lancedb` package.

---

### 03_distributed_rag_with_reranking.py

**Status:** PASS

**Description:** Demonstrates distributed RAG with Cohere reranking via `CohereReranker(model="rerank-v3.5")`. Uses standalone `print_response`/`aprint_response` from `agno.utils.print_response.team` instead of team method. Async demo by default.

**Result:** Completed successfully after installing `tantivy`. Cohere reranking applied to hybrid LanceDB search results. Team produced comprehensive Tom Kha Gai recipe with traditional and modern variations. Prior run (2026-02-08) failed due to missing `cohere` package.

---
