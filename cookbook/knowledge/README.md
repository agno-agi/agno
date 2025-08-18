# Agent Knowledge

**Knowledge Base:** is information that the Agent can search to improve its responses. This directory contains a series of cookbooks that demonstrate how to build a knowledge base for the Agent.

> Note: Fork and clone this repository if needed

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Knowledge Base** | External information that agents can search to improve responses |
| **Vector Database** | Storage system for document embeddings and similarity search |
| **Chunking** | Breaking documents into manageable pieces for processing |
| **Embeddings** | Vector representations of text for semantic search |
| **Retrieval** | Finding relevant information from the knowledge base |

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
```

## Examples

### Basic Operations
- **from_path.py** - Add content from local files
- **from_url.py** - Add content from URLs  
- **from_multiple.py** - Add multiple sources
- **specify_reader.py** - Use specific document readers
- **async_speedup.py** - Async processing for performance

### Other Topics
- **chunking/** - Text chunking strategies
- **embedders/** - Embedding model providers  
- **filters/** - Content filtering and access control
- **readers/** - Document format processors
- **search_type/** - Search algorithm options
- **vector_db/** - Vector database implementations
