# Test Log — 07_knowledge

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| agentic_rag.py | PASS | Agentic RAG with PgVector, Thai recipe knowledge base, returns Tom Kha Gai recipe |
| agentic_rag_with_reasoning.py | PASS | RAG with reasoning model, returns Agno agent concepts from docs knowledge base |
| agentic_rag_with_reranking.py | PASS | RAG with CohereReranker, returns Agno key features |
| custom_retriever.py | PASS | Custom retriever returns Python overview from hardcoded docs |
| knowledge_filters.py | PASS | Knowledge filters with metadata, returns Thai dessert recipe (Kluay Buat Chi) |
| rag_custom_embeddings.py | SKIP | Missing: sentence-transformers (huggingface_hub version conflict) |
| references_format.py | PASS | References format with PgVector, returns Tom Kha Gai recipe with source references |
| traditional_rag.py | PASS | Traditional RAG (always_search), returns Tom Kha Gai recipe from PgVector |
