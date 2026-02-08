# TEST_LOG
Generated: 2026-02-07 23:53:42

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Ran `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/02_agents/rag`.

**Result:** Structure validation passed with no violations (checked 5 file(s)).

---

### agentic_rag.py

**Status:** PASS

**Description:** Ran `.venvs/demo/bin/python cookbook/02_agents/rag/agentic_rag.py`.

**Result:** Example completed successfully. (exit code 0, ~9.49s).

---

### agentic_rag_with_reasoning.py

**Status:** FAIL

**Description:** Ran `.venvs/demo/bin/python cookbook/02_agents/rag/agentic_rag_with_reasoning.py`.

**Result:** Failed with exit code 1. ImportError: `cohere` not installed. Please install using `pip install cohere`.

---

### agentic_rag_with_reranking.py

**Status:** FAIL

**Description:** Ran `.venvs/demo/bin/python cookbook/02_agents/rag/agentic_rag_with_reranking.py`.

**Result:** Failed with exit code 1. ImportError: cohere not installed, please run pip install cohere

---

### rag_custom_embeddings.py

**Status:** FAIL

**Description:** Ran `.venvs/demo/bin/python cookbook/02_agents/rag/rag_custom_embeddings.py`.

**Result:** Failed with exit code 1. ImportError: `sentence-transformers` not installed, please run `pip install sentence-transformers`

---

### traditional_rag.py

**Status:** PASS

**Description:** Ran `.venvs/demo/bin/python cookbook/02_agents/rag/traditional_rag.py`.

**Result:** Example completed successfully. (exit code 0, ~10.94s).

---
