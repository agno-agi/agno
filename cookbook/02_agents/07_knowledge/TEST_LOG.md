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
