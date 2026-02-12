# TEST_LOG

## custom_retriever — v2.5 Review

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

### retriever.py

**Status:** FAIL

**Description:** Custom knowledge retriever using Qdrant vector DB. Demonstrates `knowledge_retriever` parameter on Agent.

**Result:** ImportError — `qdrant-client` package not installed. Not a v2.5 regression.

---

### async_retriever.py

**Status:** FAIL

**Description:** Async variant of custom retriever using Qdrant. Demonstrates async `knowledge_retriever` with `aprint_response`.

**Result:** ImportError — `qdrant-client` package not installed. Not a v2.5 regression.

---

### retriever_with_dependencies.py

**Status:** PASS

**Description:** Custom retriever with RunContext dependency injection. Loads agno docs from URL, uses PgVector, and demonstrates `dependencies` parameter on Agent.

**Result:** Successfully loaded 400+ docs from agno docs URL, inserted into PgVector, and agent answered questions using custom retriever with dependency injection.

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| PASS   | 1     | retriever_with_dependencies |
| FAIL   | 2     | retriever (qdrant), async_retriever (qdrant) |

No v2.5 regressions detected. Failures are missing optional dependency (qdrant-client).
