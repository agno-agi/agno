# Agent Knowledge

**Knowledge Base:** is information that the Agent can search to improve its responses. This directory contains a series of cookbooks that demonstrate how to build a knowledge base for the Agent.

> Note: Fork and clone this repository if needed

## Getting Started

### 1. Setup Environment

```bash
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
uv pip install -U agno openai pgvector "psycopg[binary]" sqlalchemy
```

### 2. Start PgVector Database

```bash
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pgvolume:/var/lib/postgresql/data \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:16
```

### 3. Basic Knowledge Base

```python
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="vectors",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)

# Add content from URL
knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
)

# Create agent with knowledge
agent = Agent(
    name="Knowledge Agent",
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response("What can you tell me about Thai recipes?")
```

## Examples

Add docs, manuals, and databases so agents can search and cite specific sources instead of guessing.

### Quickstart
- **[01_from_path.py](./01_quickstart/01_from_path.py)** - Add content from local files
- **[02_from_url.py](./01_quickstart/02_from_url.py)** - Add content from URLs
- **[04_from_multiple.py](./01_quickstart/04_from_multiple.py)** - Add multiple sources
- **[13_specify_reader.py](./01_quickstart/13_specify_reader.py)** - Use specific document readers
- **[15_batching.py](./01_quickstart/15_batching.py)** - Batch embedding workflow

### Other Topics
- **[chunking/](./chunking/)** - Text chunking strategies
- **[embedders/](./embedders/)** - Embedding model providers  
- **[filters/](./filters/)** - Content filtering and access control
- **[readers/](./readers/)** - Document format processors
- **[search_type/](./search_type/)** - Search algorithm options
- **[vector_db/](./vector_db/)** - Vector database implementations
