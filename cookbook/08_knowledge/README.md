# Agent Knowledge

**Knowledge Base:** is information that the Agent can search to improve its responses. This directory contains a series of cookbooks that demonstrate how to build a knowledge base for the Agent.

> Note: Fork and clone this repository if needed

## Getting Started

### 1. Setup Environment

```bash
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
pip install -U agno openai pgvector "psycopg[binary]" sqlalchemy
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

### Basic Operations
- **[from_path.py](./basic_operations/from_path.py)** - Add content from local files
- **[from_url.py](./basic_operations/from_url.py)** - Add content from URLs  
- **[from_multiple.py](./basic_operations/from_multiple.py)** - Add multiple sources
- **[specify_reader.py](./basic_operations/specify_reader.py)** - Use specific document readers
- **[async_speedup.py](./basic_operations/async_speedup.py)** - Async processing for performance

### Other Topics
- **[chunking/](./chunking/)** - Text chunking strategies
- **[embedders/](./embedders/)** - Embedding model providers  
- **[filters/](./filters/)** - Content filtering and access control
- **[readers/](./readers/)** - Document format processors
- **[search_type/](./search_type/)** - Search algorithm options
- **[vector_db/](./vector_db/)** - Vector database implementations
