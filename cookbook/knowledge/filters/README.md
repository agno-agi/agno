# Filters

Filters help you selectively retrieve and process knowledge based on metadata, content patterns, or custom criteria. They're essential for building production-ready knowledge systems.

Filtering transforms generic knowledge bases into relevant information sources by:
- **Limiting search scope** to relevant documents and sections  
- **Implementing access control** for isolation
- **Applying business rules** for content governance
- **Optimizing performance** by reducing search space

## Setup

```bash
pip install agno lancedb pandas
```

Set your API key:
```bash
export OPENAI_API_KEY=your_api_key
```

## Filtering Examples

### 1. Basic Metadata Filtering (`filtering.py`)

**When to use**: Fast, deterministic filtering based on document attributes.

**How it works**: Filters documents based on structured metadata after they're loaded into the knowledge base.

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

# Initialize knowledge base
vector_db = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",
)

knowledge = Knowledge(
    name="CSV Knowledge Base", 
    description="A knowledge base for CSV files",
    vector_db=vector_db,
)

# Load documents into the vector database
knowledge.add_contents(
    documents_to_add,
    metadata_key="file_name"
)

# Apply filters during search
results = knowledge.search(
    query="your query",
    metadata_filters={
        "file_name": "specific_file.csv"
    }
)
```

### 2. Filtering on Load (`filtering_on_load.py`)

**When to use**: Apply filters during document ingestion to preprocess and clean data.

**How it works**: Filters are considered during the loading process to control what content enters the knowledge base.

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb
from agno.db.postgres.postgres import PostgresDb

# Initialize vector and contents databases
vector_db = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",
)

knowledge = Knowledge(
    vector_db=vector_db,
    max_results=5,
    contents_db=PostgresDb(
        table_name="content_store",
        host="localhost",
        port=5432,
        username="ai",
        password="ai",
        database="ai",
    ),
)

# Load content with specific criteria
knowledge.add_contents(
    documents_to_add,
    metadata_key="file_name"
)
```

### 3. Async Filtering (`async_filtering.py`)

**When to use**: High-performance applications requiring concurrent filtering operations.

**How it works**: Asynchronous processing enables parallel filtering across multiple data sources.

```python
import asyncio
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

async def async_filtering_example():
    vector_db = LanceDb(
        table_name="async_recipes",
        uri="tmp/lancedb",
    )
    
    knowledge = Knowledge(
        name="Async Knowledge Base",
        vector_db=vector_db,
    )
    
    # Async content loading
    await knowledge.add_content(
        path="data/documents",
    )
    
    # Async search with filters
    results = await knowledge.async_search(
        query="your query",
        metadata_filters={"category": "recipes"}
    )
    
    return results

# Run async example
results = asyncio.run(async_filtering_example())
```

### 4. Agentic Filtering (`agentic_filtering.py`)

**When to use**: Complex filtering logic requiring AI understanding and decision-making.

**How it works**: Uses AI agents to intelligently filter content based on semantic understanding and context.

```python
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

# Create knowledge base
vector_db = LanceDb(table_name="agentic_recipes", uri="tmp/lancedb")
knowledge = Knowledge(name="Agentic Filtered KB", vector_db=vector_db)

# Create filtering agent
filter_agent = Agent(
    name="Content Filter Agent",
    role="Intelligent content filtering specialist", 
    instructions=[
        "Analyze documents for relevance, quality, and appropriateness",
        "Apply business rules and contextual understanding",
        "Provide filtering rationale for transparency"
    ],
    knowledge=knowledge,
    search_knowledge=True,
)

# Load content and let agent filter intelligently
knowledge.add_contents(documents_to_add)

# Agent can now intelligently filter and retrieve content
response = filter_agent.run("Find high-quality technical documentation")
```

### 5. Invalid Keys Handling (`filtering_with_invalid_keys.py`)

**When to use**: Robust filtering in environments with inconsistent or missing metadata.

**How it works**: Graceful handling of missing, malformed, or inconsistent metadata keys during filtering operations.

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

def robust_filtering_example():
    vector_db = LanceDb(table_name="robust_recipes", uri="tmp/lancedb")
    knowledge = Knowledge(vector_db=vector_db)
    
    # Load content with potentially inconsistent metadata
    knowledge.add_contents(documents_with_mixed_metadata)
    
    try:
        # Search with filters, handling missing keys gracefully
        results = knowledge.search(
            query="recipe query",
            metadata_filters={
                "category": "desserts",
                "difficulty": "easy"  # May not exist in all documents
            }
        )
        return results
    except Exception as e:
        print(f"Filtering error handled: {e}")
        # Fallback to unfiltered search
        return knowledge.search(query="recipe query")
```

## Common Use Cases

- **Content Quality Control**: Filter out low-quality or inappropriate content
- **Access Control**: Restrict access based on user permissions and document sensitivity
- **Domain Filtering**: Focus searches on specific departments, projects, or topics  
- **Temporal Filtering**: Find recent documents or content from specific time periods
- **Language and Localization**: Filter content by language or geographic relevance