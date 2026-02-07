# _relocated

Staging area for integration-specific examples scheduled to move into cookbook/integrations/.

## Files
- `agentic_rag_infinity_reranker.py` - Demonstrates agentic rag infinity reranker.
- `agentic_rag_with_lightrag.py` - Demonstrates agentic rag with lightrag.
- `local_rag_langchain_qdrant.py` - Demonstrates local rag langchain qdrant.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
