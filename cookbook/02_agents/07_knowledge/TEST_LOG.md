# Test Log -- 07_knowledge

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### agentic_rag.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates agentic rag. Ran successfully and produced expected output.
**Result:** Completed successfully in 18s.

---

### agentic_rag_with_reasoning.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates agentic rag with reasoning. Failed due to missing dependency: ModuleNotFoundError: No module named 'cohere'
**Result:** Missing dependency - should be reclassified as SKIP or dependency added to demo env.

---

### agentic_rag_with_reranking.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates agentic rag with reranking. Failed due to missing dependency: ModuleNotFoundError: No module named 'cohere'
**Result:** Missing dependency - should be reclassified as SKIP or dependency added to demo env.

---

### custom_retriever.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates custom retriever. Ran successfully and produced expected output.
**Result:** Completed successfully in 10s.

---

### knowledge_filters.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates knowledge filters. Ran successfully and produced expected output.
**Result:** Completed successfully in 14s.

---

### rag_custom_embeddings.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates rag custom embeddings. Failed due to missing dependency: ModuleNotFoundError: No module named 'sentence_transformers'
**Result:** Missing dependency - should be reclassified as SKIP or dependency added to demo env.

---

### references_format.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates references format. Ran successfully and produced expected output.
**Result:** Completed successfully in 13s.

---

### traditional_rag.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates traditional rag. Ran successfully and produced expected output.
**Result:** Completed successfully in 12s.

---
