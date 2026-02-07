# TEST_LOG
Generated: 2026-02-07 23:53:42

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Ran `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/02_agents/_relocated`.

**Result:** Structure validation passed with no violations (checked 3 file(s)).

---

### agentic_rag_infinity_reranker.py

**Status:** FAIL

**Description:** Ran `.venvs/demo/bin/python cookbook/02_agents/_relocated/agentic_rag_infinity_reranker.py`.

**Result:** Failed with exit code 1. ImportError: `cohere` not installed. Please install using `pip install cohere`.

---

### agentic_rag_with_lightrag.py

**Status:** FAIL

**Description:** Ran `.venvs/demo/bin/python cookbook/02_agents/_relocated/agentic_rag_with_lightrag.py`.

**Result:** Failed with exit code 1. ImportError: The `wikipedia` package is not installed. Please install it via `pip install wikipedia`.

---

### local_rag_langchain_qdrant.py

**Status:** FAIL

**Description:** Ran `.venvs/demo/bin/python cookbook/02_agents/_relocated/local_rag_langchain_qdrant.py`.

**Result:** Failed with exit code 1. ImportError: `ollama` not installed. Please install using `pip install ollama`

---
