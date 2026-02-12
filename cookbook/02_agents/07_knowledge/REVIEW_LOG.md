# REVIEW LOG

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Framework Issues

[FRAMEWORK] knowledge/knowledge.py — `name` and `description` default to empty string; downstream vector search may store empty metadata fields, making filtering unreliable when users omit these.

[FRAMEWORK] vectordb/pgvector/pgvector.py — `_id_seed()` omits `schema` from the hash seed. Two tables with the same name in different PG schemas would collide on deterministic IDs.

[FRAMEWORK] vectordb/pgvector/pgvector.py — `search_kwargs` parameter uses mutable default `{}`. Multiple PgVector instances sharing the same dict could cause subtle cross-contamination.

[FRAMEWORK] knowledge/knowledge.py — `text_content` on a Document can be empty string after chunking edge cases; `ainsert_many` doesn't guard against inserting empty-content chunks.

## Cookbook Quality

[QUALITY] agentic_rag.py — Good minimal example of agentic RAG. Demonstrates `search_knowledge=True` (default) with PgVector hybrid search.

[QUALITY] traditional_rag.py — Clear contrast with agentic RAG: uses `add_references=True` for always-search pattern. Good teaching pair.

[QUALITY] agentic_rag_with_reasoning.py — Good advanced example combining ReasoningTools + Cohere embedder/reranker. Shows hybrid search with external reranking.

[QUALITY] agentic_rag_with_reranking.py — Demonstrates Cohere reranker integration. Would benefit from a comment explaining why reranking improves retrieval quality.

[QUALITY] rag_custom_embeddings.py — Shows SentenceTransformer local embeddings. Good for users who want to avoid API-based embedding costs.

## Fixes Applied

None — all cookbooks are v2.5 compatible as-is.
