# 07_knowledge

Examples for retrieval-augmented generation, knowledge filters, and custom retrievers.

## Files
- `agentic_rag.py` - Agentic RAG with PgVector.
- `agentic_rag_with_reasoning.py` - Agentic RAG with reasoning tools.
- `agentic_rag_with_reranking.py` - Agentic RAG with Cohere reranking.
- `custom_retriever.py` - Use a custom retrieval function instead of a Knowledge instance.
- `knowledge_filters.py` - Filter knowledge searches with static or agentic filters.
- `rag_custom_embeddings.py` - RAG with custom embeddings.
- `references_format.py` - Control reference format (JSON vs YAML).
- `traditional_rag.py` - Traditional RAG with context injection.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Requires PostgreSQL with pgvector: `./cookbook/scripts/run_pgvector.sh`

## Run
- `.venvs/demo/bin/python cookbook/02_agents/07_knowledge/<file>.py`
