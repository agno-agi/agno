# Getting Started with Knowledge

Start here to learn the basics of RAG (Retrieval-Augmented Generation) with Agno.

## Prerequisites

1. Run Qdrant: `./cookbook/scripts/run_qdrant.sh`
2. Set `OPENAI_API_KEY` environment variable

## Examples

| File | What It Shows |
|------|---------------|
| [01_basic_rag.py](./01_basic_rag.py) | Traditional RAG with automatic context injection |
| [02_agentic_rag.py](./02_agentic_rag.py) | Agentic RAG where the agent decides when to search |
| [03_loading_content.py](./03_loading_content.py) | Loading from files, URLs, text, topics, and batches |
| [04_choosing_components.md](./04_choosing_components.md) | Decision guide for vector DBs, embedders, and chunking |

## Start Here

```bash
# Basic RAG (simplest pattern)
.venvs/demo/bin/python cookbook/07_knowledge/01_getting_started/01_basic_rag.py

# Agentic RAG (recommended for production)
.venvs/demo/bin/python cookbook/07_knowledge/01_getting_started/02_agentic_rag.py
```

## Basic vs Agentic RAG

- **Basic RAG** (`add_knowledge_to_context=True`): Context is fetched and injected into the prompt automatically. Simple, predictable, but always searches.
- **Agentic RAG** (`search_knowledge=True`): Agent gets a search tool and decides when to use it. More flexible, can search multiple times or skip searching. This is the default.

## Further Reading

- [Knowledge Overview](https://docs.agno.com/knowledge/overview)
- [Agents](https://docs.agno.com/agents/overview)
