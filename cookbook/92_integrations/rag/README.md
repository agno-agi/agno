# RAG Integrations

Examples for third-party RAG and retrieval-stack integrations.

## Files

- [`agentic_rag_infinity_reranker.py`](./agentic_rag_infinity_reranker.py): Agentic RAG with Infinity reranker.
- [`agentic_rag_with_lightrag.py`](./agentic_rag_with_lightrag.py): Agentic RAG with LightRAG.
- [`local_rag_langchain_qdrant.py`](./local_rag_langchain_qdrant.py): Local RAG with LangChain + Qdrant.

## Prerequisites

- Load environment variables with `direnv allow` (including `OPENAI_API_KEY` and provider-specific keys where needed).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services and dependencies (for example Infinity, Ollama, or extra pip packages).

## Run

```bash
.venvs/demo/bin/python cookbook/92_integrations/rag/<file>.py
```
