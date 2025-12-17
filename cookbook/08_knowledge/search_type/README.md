# Search Types

Search strategies determine how your agents find relevant information in knowledge bases using different algorithms and approaches.

## Basic Integration

Search types integrate with vector databases to control retrieval behavior:

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType
from agno.agent import Agent
from agno.models.openai import OpenAIChat

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="docs",
        db_url="your_db_url",
        search_type=SearchType.hybrid
    )
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True
)

agent.print_response("Ask anything - the search type determines how I find answers")
```

## Supported Search Types

- **[Hybrid Search](./hybrid_search.py)** - Combines vector and keyword search
- **[Keyword Search](./keyword_search.py)** - Traditional text-based search
- **[Vector Search](./vector_search.py)** - Semantic similarity search
