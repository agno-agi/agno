# TEST LOG

Generated: 2026-02-10 UTC

Pattern Check: Checked 5 file(s) in cookbook/02_agents/rag. Violations: 0

Requires: pgvector (`./cookbook/scripts/run_pgvector.sh`)

### agentic_rag.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### agentic_rag_with_reasoning.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Failed with import dependency error: `cohere` not installed. Please install using `pip install cohere`.

---

### agentic_rag_with_reranking.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Failed with import dependency error: `cohere` not installed. Please install using `pip install cohere`.

---

### rag_custom_embeddings.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Failed with import dependency error: `sentence-transformers` not installed. Please install using `pip install sentence-transformers`.

---

### traditional_rag.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### custom_retriever.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### knowledge_filters.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0 (requires pgvector for full execution).

---

### references_format.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0 (requires pgvector for full execution).

---


---

## v2.5 Audit Results

# TEST LOG

Generated: 2026-02-11 UTC (v2.5 three-layer review)

Requires: pgvector (`./cookbook/scripts/run_pgvector.sh`), OPENAI_API_KEY

### agentic_rag.py

**Status:** PASS

**Description:** Agentic RAG with PgVector hybrid search. Agent searches knowledge on demand via `search_knowledge=True`.

**Result:** Inserted docs from agno docs URL, agent queried knowledge and responded with sources. No v2.5 issues.

---

### traditional_rag.py

**Status:** PASS

**Description:** Traditional RAG with `search_knowledge=True, add_references=True`. Always searches before responding.

**Result:** Loaded agno docs, retrieved relevant chunks, included references in response. No v2.5 issues.

---

### agentic_rag_with_reasoning.py

**Status:** SKIP

**Description:** Agentic RAG with Cohere embedder/reranker + ReasoningTools.

**Reason:** Requires `cohere` package and COHERE_API_KEY (CohereEmbedder, CohereReranker). Not installed in demo venv.

---

### agentic_rag_with_reranking.py

**Status:** SKIP

**Description:** Agentic RAG with Cohere reranker for improved relevance.

**Reason:** Requires `cohere` package and COHERE_API_KEY (CohereReranker). Not installed in demo venv.

---

### rag_custom_embeddings.py

**Status:** SKIP

**Description:** RAG with SentenceTransformer local embeddings instead of API-based.

**Reason:** Requires `sentence-transformers` package (SentenceTransformerEmbedder). Not installed in demo venv.

---
