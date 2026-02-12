# Test Log — search_type

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| hybrid_search.py | PASS | Hybrid search (vector + keyword), 5 results from Thai recipes |
| keyword_search.py | PASS | Keyword (BM25) search, 5 results including recipes and CVs |
| vector_search.py | PASS | Vector (semantic) search, 5 results, top: Tom Kha Gai |

## Summary

| Status | Count |
|--------|-------|
| PASS   | 3     |
