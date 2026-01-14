# Knowledge Cookbook Testing Log

Testing knowledge/RAG examples in `cookbook/08_knowledge/`.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Date: 2026-01-14

---

## basic_operations/

### sync/01_from_path.py

**Status:** NOT TESTED

**Description:** Load knowledge from local files.

---

### sync/02_from_url.py

**Status:** NOT TESTED

**Description:** Load knowledge from URLs.

---

## vector_db/

### lancedb/basic.py

**Status:** NOT TESTED

**Description:** LanceDb (local, no setup needed).

---

### pgvector/basic.py

**Status:** NOT TESTED

**Description:** PgVector integration.

**Dependencies:** PgVector running

---

## embedders/

### openai_embedder.py

**Status:** NOT TESTED

**Description:** OpenAI embeddings.

---

## TESTING SUMMARY

**Summary:**
- Total examples: 204
- Tested: 0
- Passed: 0

**Notes:**
- Largest cookbook folder
- Start with lancedb/chromadb (no external deps)
- Many embedders require API keys
