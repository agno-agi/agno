# Custom Retrievers

Custom retrievers provide complete control over how your agents find and process information. 

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

### Retriever Components

```python
# Core retriever interface
def custom_retriever(
    query: str,                    # User query
    num_documents: int = 5,        # Number of documents to return
    filters: Dict[str, Any] = {},  # Filter criteria
) -> List[Document]:               # Retrieved documents
    # Your custom logic here
    pass
```

## Implementation Examples

### 1. Basic Custom Retriever (`retriever.py`)


**How it works**: Defines a custom function that agents call instead of built-in retrieval.

```python
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge

def custom_knowledge_retriever(query: str, num_documents: int = 5) -> str:
    """Custom retrieval logic with domain-specific processing"""
    
    # 1. Preprocess query
    processed_query = preprocess_domain_query(query)
    
    # 2. Multi-source search
    vector_results = vector_db.search(processed_query, limit=num_documents//2)
    keyword_results = keyword_search(processed_query, limit=num_documents//2)
    
    # 3. Custom ranking and fusion
    ranked_results = custom_ranking_algorithm(vector_results + keyword_results)
    
    # 4. Post-process and format
    return format_results_for_agent(ranked_results[:num_documents])

# Use custom retriever with agent
agent = Agent(
    knowledge_retriever=custom_knowledge_retriever,
    search_knowledge=True,
)
```

**Key benefits**:
- Complete control over search logic
- Integration with external systems
- Domain-specific ranking and filtering
- Multi-modal search capabilities

### 2. Async Custom Retriever (`async_retriever.py`)

**How it works**: Asynchronous retrieval for concurrent processing and better scalability.

```python
import asyncio
from typing import List

async def async_custom_retriever(
    query: str, 
    num_documents: int = 5,
    filters: Dict[str, Any] = {}
) -> str:
    """Asynchronous retrieval with concurrent processing"""
    
    # Parallel search across multiple sources
    tasks = [
        vector_db.async_search(query, limit=num_documents//3),
        external_api_search(query, limit=num_documents//3),
        cached_search(query, limit=num_documents//3),
    ]
    
    results = await asyncio.gather(*tasks)
    
    # Combine and rank results
    combined_results = merge_and_rank(results)
    return format_for_agent(combined_results[:num_documents])
```

**Performance benefits**:
- Faster retrieval with parallel processing
- Better resource utilization
- Scalable for high-traffic applications