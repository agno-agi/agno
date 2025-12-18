# Custom Retrievers

Custom retrievers provide complete control over how your agents find and process information from knowledge sources.

## Setup

```bash
pip install agno qdrant-client openai
```

Start Qdrant locally:
```bash
docker run -p 6333:6333 qdrant/qdrant
```

Set your API key:
```bash
export OPENAI_API_KEY=your_api_key
```

## Basic Integration

Custom retrievers integrate with agents to replace default knowledge search:

```python
from agno.agent import Agent

def custom_knowledge_retriever(query: str, num_documents: int = 5) -> str:
    # Your custom retrieval logic
    results = your_search_logic(query, num_documents)
    return format_results(results)

agent = Agent(
    knowledge_retriever=custom_knowledge_retriever,
    search_knowledge=True
)

agent.print_response(query, markdown=True)
```

## Supported Custom Retrievers

- **[Async Retriever](./async_retriever.py)** - Asynchronous retrieval with concurrent processing
- **[Basic Retriever](./retriever.py)** - Custom retrieval logic and processing
- **[Retriever with Dependencies](./retriever_with_dependencies.py)** - Access runtime dependencies in custom retrievers