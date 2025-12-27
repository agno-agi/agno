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

## Examples

- **[01_distributed_rag_pgvector.py](./01_distributed_rag_pgvector.py)** - PgVector distributed RAG
- **[02_distributed_rag_lancedb.py](./02_distributed_rag_lancedb.py)** - LanceDB distributed RAG
- **[03_distributed_rag_with_reranking.py](./03_distributed_rag_with_reranking.py)** - RAG with reranking
