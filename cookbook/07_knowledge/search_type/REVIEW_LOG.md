# REVIEW_LOG

## search_type — v2.5 Review (2026-02-11)

## Framework Issues

[FRAMEWORK] agno/knowledge/knowledge.py:515 — `Knowledge.search(search_type=...)` mutates `self.vector_db.search_type` persistently. Calling `knowledge.search(search_type=SearchType.keyword)` permanently changes the vector_db's search type for all future calls. Should use a local copy or context manager.

[FRAMEWORK] agno/knowledge/knowledge.py:528 — `Knowledge.search()` injects `linked_to` filter only for dict-style filters. List/DSL filters bypass instance isolation, potentially leaking data between Knowledge instances sharing a table.

[FRAMEWORK] agno/knowledge/knowledge.py:567 — Same `linked_to` isolation gap in `Knowledge.asearch()` for list/DSL filters.

[FRAMEWORK] agno/vectordb/pgvector/pgvector.py:339 — sync `insert()` does not guard against empty `batch_records` (async version does).

[FRAMEWORK] agno/vectordb/pgvector/pgvector.py:1402 — Exception handlers call `sess.rollback()` even when session context may already be invalid.

## Cookbook Quality

[QUALITY] All 3 files use `vector_db.search()` directly instead of `knowledge.search()`. For teaching purposes, should demonstrate the Knowledge abstraction layer which handles linked_to isolation and search type management.

[QUALITY] All 3 files share `table_name="recipes"` — running them in sequence causes cross-knowledge data leakage. keyword_search results included CV documents from other cookbooks. Should use unique table names (e.g., recipes_hybrid, recipes_keyword, recipes_vector).

## Fixes Applied

None — all 3 cookbooks ran successfully without modification.
