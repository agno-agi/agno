# Advanced Patterns

Advanced knowledge patterns for power users and custom integrations.

## Prerequisites

1. Run Qdrant: `./cookbook/scripts/run_qdrant.sh`
2. Set `OPENAI_API_KEY` environment variable
3. For Graph RAG: `pip install lightrag-agno`

## Examples

| File | What It Shows |
|------|---------------|
| [01_custom_retriever.py](./01_custom_retriever.py) | Custom retrieval function bypassing Knowledge class |
| [02_custom_chunking.py](./02_custom_chunking.py) | Implementing a custom chunking strategy |
| [03_graph_rag.py](./03_graph_rag.py) | LightRAG knowledge graph integration |
| [04_knowledge_tools.py](./04_knowledge_tools.py) | KnowledgeTools: think, search, analyze |
| [05_knowledge_protocol.py](./05_knowledge_protocol.py) | Custom KnowledgeProtocol implementation |

## Running

```bash
.venvs/demo/bin/python cookbook/07_knowledge/04_advanced/01_custom_retriever.py
```

## Further Reading

- [Knowledge Overview](https://docs.agno.com/knowledge/overview)
