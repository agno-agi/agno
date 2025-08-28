# Distributed RAG

Distributed retrieval-augmented generation with teams for scalable knowledge processing.

## Setup

```bash
pip install agno openai anthropic cohere lancedb pgvector "psycopg[binary]" sqlalchemy
```

Set your API key based on your provider:
```bash
export OPENAI_API_KEY=xxx
export ANTHROPIC_API_KEY=xxx
export CO_API_KEY=xxx
```

### Start PgVector Database

```bash
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:16
```

## Basic Integration

Distributed teams for RAG operations:

```python
from agno.agent import Agent
from agno.team import Team
from agno.knowledge.knowledge import Knowledge

knowledge = Knowledge()

# agents for different retrieval tasks
vector_agent = Agent(name="Vector Searcher", knowledge=knowledge)
hybrid_agent = Agent(name="Hybrid Searcher", knowledge=knowledge)
validator_agent = Agent(name="Data Validator", knowledge=knowledge)

team = Team(
    members=[vector_agent, hybrid_agent, validator_agent],
    mode="coordinate",
)
```

## Examples

- **[01_distributed_rag_pgvector.py](./01_distributed_rag_pgvector.py)** - PgVector distributed RAG
- **[02_distributed_rag_lancedb.py](./02_distributed_rag_lancedb.py)** - LanceDB distributed RAG
- **[03_distributed_rag_with_reranking.py](./03_distributed_rag_with_reranking.py)** - RAG with reranking
