# Review Log: distributed_rag

> Updated: 2026-02-11

## Framework Issues

[FRAMEWORK] libs/agno/agno/vectordb/lancedb/lance_db.py:168-170 — LanceDB with `SearchType.hybrid` requires `tantivy` module but the error only fires at `__init__` time (module-level). This means importing any cookbook that constructs a hybrid LanceDb will fail immediately, even if the user only wants vector search. The check should be deferred to the actual hybrid search call.

[FRAMEWORK] libs/agno/agno/utils/print_response/team.py — Standalone `print_response(team, query)` and `aprint_response(input=query, team=team)` have inconsistent signatures. The sync version takes positional `(team, input)`, while the async version uses keyword `(input=, team=)`. This inconsistency can confuse users.

## Cookbook Quality

[QUALITY] 01_distributed_rag_pgvector.py — Defaults to `sync_pgvector_rag_demo()` with `async_pgvector_rag_demo()` and `complex_query_demo()` commented out. Good that it shows both patterns but would be better to run at least one by default and mention the others.

[QUALITY] 02_distributed_rag_lancedb.py — Requires 3 optional packages (lancedb, tantivy, openai embedder). Dependencies should be documented at the top of the file or in a requirements comment.

[QUALITY] 03_distributed_rag_with_reranking.py — Uses standalone `from agno.utils.print_response.team import aprint_response, print_response` instead of `team.print_response()`. This is a valid but uncommon pattern that may confuse users. The inconsistent call signatures between sync `print_response(team, query)` and async `await aprint_response(input=query, team=team)` are especially confusing.

[QUALITY] All 3 files download the same ThaiRecipes.pdf from S3 and insert into knowledge bases each run. No `skip_if_exists` or caching, so repeated runs re-download and re-embed. Consider adding `skip_existing=True` to the insert calls.

## Fixes Applied

None — all cookbooks are compatible with v2.5 API as-is (after installing dependencies).
