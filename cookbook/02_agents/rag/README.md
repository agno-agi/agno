# rag

Examples for traditional and agentic retrieval-augmented generation.

## Files
- `agentic_rag.py` - Demonstrates agentic rag.
- `agentic_rag_with_reasoning.py` - Demonstrates agentic rag with reasoning.
- `agentic_rag_with_reranking.py` - Demonstrates agentic rag with reranking.
- `rag_custom_embeddings.py` - Demonstrates rag custom embeddings.
- `traditional_rag.py` - Demonstrates traditional rag.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
