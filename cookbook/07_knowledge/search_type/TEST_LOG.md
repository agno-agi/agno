# TEST_LOG

## search_type — v2.5 Review (2026-02-11)

### vector_search.py

**Status:** PASS

**Description:** PgVector vector (semantic) search. Inserts Thai recipes PDF from S3 URL, searches with embeddings.

**Result:** Successfully inserted 14 documents, found 5 results for "chicken coconut soup". Top result: Tom Kha Gai recipe.

---

### keyword_search.py

**Status:** PASS

**Description:** PgVector keyword (BM25 full-text) search. Same PDF insert, keyword-based search.

**Result:** Successfully inserted 14 documents, found 5 results. Keyword search returned Thai recipes plus some CV documents from shared table (cross-knowledge leakage via shared table name).

---

### hybrid_search.py

**Status:** PASS

**Description:** PgVector hybrid search (combines vector + keyword). Same PDF insert, hybrid search.

**Result:** Successfully inserted 14 documents, found 5 results. Hybrid results were recipe-focused (better relevance than keyword-only).

---
