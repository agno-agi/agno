# RAG Integrations

Examples for third-party RAG and retrieval-stack integrations.

## Files

- [`agentic_rag_infinity_reranker.py`](./agentic_rag_infinity_reranker.py): Agentic RAG with Infinity reranker.
- [`agentic_rag_with_lightrag.py`](./agentic_rag_with_lightrag.py): Agentic RAG with LightRAG.
- [`local_rag_langchain_qdrant.py`](./local_rag_langchain_qdrant.py): Local RAG with LangChain + Qdrant.
- [`local_rag_langchain_pixeltable.py`](./local_rag_langchain_pixeltable.py): Local RAG with LangChain + Pixeltable.

## Prerequisites

- Load environment variables with `direnv allow` (including `OPENAI_API_KEY` and provider-specific keys where needed).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services and dependencies (for example Infinity, Ollama, or extra pip packages).
- `local_rag_langchain_pixeltable.py` needs `langchain-pixeltable`, `langchain-huggingface`, `langchain-text-splitters`, `sentence-transformers`, `ollama`, and `openai`. Embeddings are local sentence-transformers. The agent model is Ollama, and importing that model also imports Agno's OpenAI client.

## Run

```bash
.venvs/demo/bin/python cookbook/07_knowledge/05_integrations/rag/<file>.py
```
