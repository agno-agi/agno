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
    filters={
        "file_name": "specific_file.csv"
    }
)
```

### 2. Metadata on Load (`filtering_on_load.py`)

**How it works**: Sets metadata attributes when loading content into the knowledge base, enabling filtering during search.

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

knowledge = Knowledge(vector_db=LanceDb(table_name="recipes", uri="tmp/lancedb"))

# Add content with metadata for filtering
knowledge.add_content(
    path="sales_q1.csv",
    metadata={
        "data_type": "sales",
        "quarter": "Q1", 
        "year": 2024,
        "region": "north_america"
    }
)

# filter by metadata during search
results = knowledge.search(
    query="revenue trends",
    filters={"quarter": "Q1", "region": "north_america"}
)
```

### 3. Async Filtering (`async_filtering.py`)

**How it works**: Creates an agent that uses filtered knowledge base for targeted information retrieval.

```python
import asyncio
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb
from agno.models.openai import OpenAIChat

async def async_filtering_example():
    knowledge = Knowledge(
        name="CV Knowledge Base",
        vector_db=LanceDb(table_name="cvs", uri="tmp/lancedb")
    )
    
    # Add CVs with user metadata
    knowledge.add_content(
        path="jordan_cv.docx",
        metadata={"user_id": "jordan_mitchell", "document_type": "cv"}
    )
    
    # Create agent with filtered knowledge
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge,
        instructions="Search knowledge before answering questions about specific users."
    )
    
    # Agent automatically filters knowledge based on context
    response = await agent.arun(
        "What are Jordan's technical skills?",
        knowledge_filters={"user_id": "jordan_mitchell"}
    )
    
    return response

# Run example
result = asyncio.run(async_filtering_example())
```

### 4. Agentic Filtering (`agentic_filtering.py`)

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
    enable_agentic_knowledge_filters=True,
)

# Load content and let agent filter intelligently
knowledge.add_contents(documents_to_add)

# Agent can now intelligently filter and retrieve content
response = filter_agent.run("Find high-quality technical documentation")
```

### 5. Invalid Keys Handling (`filtering_with_invalid_keys.py`)

**How it works**: Handling of missing, malformed, or inconsistent metadata keys during filtering operations.

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
            filters={
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