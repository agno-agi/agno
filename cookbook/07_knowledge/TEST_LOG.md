# TEST_LOG

## 07_knowledge

Semantic cache updates recorded.

---

### test_knowledge_semantic_cache.py

**Status:** PASS

**Description:** Added focused unit tests for semantic query caching in `Knowledge.search()` / `Knowledge.asearch()` including hit/miss behavior, threshold gating, TTL, entry eviction, context isolation, async parity, fail-open behavior, and cache immutability.

**Result:** `python -m pytest libs/agno/tests/unit/knowledge/test_knowledge_semantic_cache.py -q` passed.

---

### 04_advanced/06_semantic_cache.py

**Status:** PASS

**Description:** Added an advanced cookbook example that demonstrates first-query miss and second-query semantic cache hit using a search call counter.

**Result:** Executed with `OPENAI_API_KEY` and local Qdrant. Observed `first_docs=1`, `second_docs=1`, `vector_search_calls=1`, and `semantic_cache_hit=True`.

---

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Validated restructured knowledge cookbooks by running the checker across merged quickstart, embedders, and all vector_db backend subdirectories.

**Result:** All checked directories reported 0 violations after restructuring.

---
