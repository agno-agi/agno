# Search Coordination

Coordinated search across multiple agents and knowledge sources.

## Setup

```bash
pip install agno openai anthropic cohere lancedb tantivy sqlalchemy
```

Set your API key based on your provider:
```bash
export OPENAI_API_KEY=xxx
export ANTHROPIC_API_KEY=xxx
export CO_API_KEY=xxx
```


## Examples

- **[01_coordinated_agentic_rag.py](./01_coordinated_agentic_rag.py)** - Coordinated agentic RAG
- **[02_coordinated_reasoning_rag.py](./02_coordinated_reasoning_rag.py)** - RAG with reasoning coordination
- **[03_distributed_infinity_search.py](./03_distributed_infinity_search.py)** - Distributed infinity search
