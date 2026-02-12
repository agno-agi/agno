# REVIEW_LOG

## vector_db — v2.5 Review (2026-02-11)

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing
Deps installed during testing: lancedb, langchain, langchain-community, langchain-openai, langchain-chroma, llama-index

---

## Framework Issues

[FRAMEWORK] agno/knowledge/knowledge.py — `Knowledge.search(search_type=...)` mutates `self.vector_db.search_type` permanently. Affects all vector_db cookbooks that use Knowledge.search(). If one query uses keyword, subsequent queries default to keyword.

[FRAMEWORK] agno/vectordb/lancedb/ — lance_db_hybrid_search.py returned results that the agent ignored in favor of general knowledge. May indicate hybrid search ranking issue with LanceDb backend where keyword component dilutes vector results.

## Cookbook Quality

[QUALITY] All vector_db cookbooks — Hardcoded `postgresql+psycopg://ai:ai@localhost:5532/ai` for PgVector files. Should use environment variable.

[QUALITY] pgvector_db.py — Excellent quality. Demonstrates sync, async, batch, deletion by name and metadata. Comprehensive coverage of PgVector operations.

[QUALITY] chroma_db_hybrid_search.py — Good quality. Clean demonstration of RRF hybrid search with configurable parameters. Uses smaller embedding model (text-embedding-3-small) which is a good practice.

[QUALITY] lance_db.py — Path inconsistency: uses `tmp/lancedb` (relative) for sync and `/tmp/lancedb` (absolute) for async. Should be consistent.

[QUALITY] lance_db_hybrid_search.py — Agent answered from general knowledge instead of KB, which undermines the hybrid search demo. Should verify search results contain relevant content.

[QUALITY] langchain_db.py — Stale import: `from langchain.text_splitter import CharacterTextSplitter` should be `from langchain_text_splitters import CharacterTextSplitter` for langchain v0.3+.

[QUALITY] llamaindex_db.py — Downloads Paul Graham essay to `wip/data/paul_graham/` which doesn't exist in standard cookbook layout. Download step fails silently, then SimpleDirectoryReader raises ValueError.

[QUALITY] All 32 import paths verified — Every file uses correct agno v2.5 import paths (`agno.vectordb.*`, `agno.knowledge.*`, `agno.agent.*`). Zero broken imports.

---

## Fixes Applied

None — all failures are pre-existing cookbook issues (stale langchain imports, missing data directory). No v2.5 regressions detected.
