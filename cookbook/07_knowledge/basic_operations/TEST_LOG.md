# TEST_LOG

## basic_operations — v2.5 Review

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

### async/04_from_multiple.py

**Status:** PASS

**Description:** Async-only example of multiple source loading using ainsert_many with dicts and keyword variants. Uses OpenAIEmbedder and PgVector.

**Result:** Successfully inserted from multiple paths and URLs with metadata. Agent answered "What can you tell me about my documents?" using knowledge search.

---

### async/05_isolate_vector_search.py

**Status:** FAIL

**Description:** Tests knowledge isolation via isolate_vector_search=True flag for multi-tenancy with shared VectorDB.

**Result:** TypeError — `Knowledge.__init__() got an unexpected keyword argument 'isolate_vector_search'`. This parameter has been removed from the Knowledge class in v2.5. This is a v2.5 breaking change.

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| PASS   | 1     | async/04_from_multiple |
| FAIL   | 1     | async/05_isolate_vector_search (v2.5 breaking change) |
