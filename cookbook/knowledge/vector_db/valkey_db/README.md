# Valkey Search Vector Database Integration

This demonstrates Valkey Search integration with the Agno framework. Valkey Search is a high-performance vector database that supports similarity search using HNSW algorithm.

## Setup

### 1. Install UV
Install UV package manager (required for development setup):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Run Development Setup
From the root agno directory:
```bash
./scripts/dev_setup.sh
```

### 3. Activate Environment
```bash
source .venv/bin/activate  # On macOS/Linux
# OR
.venv\Scripts\activate     # On Windows
```

### 4. Set OpenAI API Key
```bash
export OPENAI_API_KEY="your-api-key-here"
```

### 5. Start Valkey Server
Run Valkey with the search module using Docker Compose:

```bash
# Navigate to the valkey_db directory
cd cookbook/knowledge/vector_db/valkey_db/

# Start Valkey server with search module
docker-compose up -d

# Verify it's running
docker-compose ps
```

### 6. Run the Example
```bash
python valkey_db.py
```

## Results

When you run the example, you'll see output demonstrating Valkey Search loading PDF content from a URL and answering questions:

```
python valkey_db.py
INFO Embedder not provided, using OpenAIEmbedder as default.
INFO Created Valkey Search index 'vectors' with result: OK
INFO Loading content: b9d61209-73e8-5072-8d39-84263a15b9d6
INFO Adding content from URL https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf
INFO Reading: Recipes
INFO Inserted 187 documents into Valkey Search index 'vectors'
WARNING  Contents DB not found for knowledge base: Valkey Knowledge Base
INFO Setting default model to OpenAI Chat
┏━ Message ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                                                                                                      ┃
┃ List down the ingredients to make Massaman Gai                                                                                                       ┃
┃                                                                                                                                                      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┏━ Tool Calls ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                                                                                                      ┃
┃ • search_knowledge_base(query=Massaman Gai ingredients)                                                                                              ┃
┃                                                                                                                                                      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┏━ Response (4.2s) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                                                                                                      ┃
┃ Here are the ingredients to make Massaman Gai (Massaman Curry with Chicken and Potatoes) for two servings:                                           ┃
┃                                                                                                                                                      ┃
┃  • 300 grams of chicken rump                                                                                                                         ┃
┃  • 80 grams of Massaman curry paste                                                                                                                  ┃
┃  • 100 grams of coconut                                                                                                                              ┃
┃                                                                                                                                                      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

## Key Features Demonstrated

- **Vector Similarity Search**: HNSW algorithm with cosine similarity
- **Binary Vector Storage**: Efficient 1536-dimensional embeddings (6144 bytes)
- **Async/Sync Operations**: Full support for both paradigms
- **Knowledge System Integration**: AI agents with searchable knowledge base
- **Metadata Filtering**: TAG field indexing for efficient queries
- **Automatic Fallbacks**: Robust error handling

## Technical Implementation

- **Vector Format**: Binary-packed float32 arrays using `struct.pack`
- **Search Schema**: HNSW index with cosine distance metric
- **Embeddings**: OpenAI text-embedding-ada-002 (1536 dimensions)
- **Storage**: Valkey HASH with vector and metadata fields
- **Query Processing**: KNN search with similarity scoring

## Architecture Overview

The Valkey Search integration provides a complete vector database solution within the Agno framework:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Agno Agent    │───▶│  Knowledge Base  │───▶│ Valkey Search   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Query Processing│    │   Embeddings     │    │ Vector Storage  │
│ & Response      │    │ (OpenAI/Custom)  │    │ & Search Index  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Integration Examples

### Loading PDF from URL (Main Example)
```python
from agno.vectordb.valkey import ValkeySearch
from agno.knowledge.knowledge import Knowledge
from agno.agent import Agent
import asyncio

# Create Knowledge with Valkey Search
knowledge = Knowledge(
    name="Valkey Knowledge Base",
    description="Agno Knowledge Implementation with Valkey Search",
    vector_db=ValkeySearch(
        collection="vectors",
        host="localhost",
        port=6379,
    ),
)

# Add PDF content from URL
asyncio.run(
    knowledge.add_content_async(
        name="Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"doc_type": "recipe_book"},
    )
)

# Create and use the agent
agent = Agent(knowledge=knowledge)
agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)
```

### Basic Vector Search
```python
from agno.vectordb.valkey import ValkeySearch

# Initialize Valkey Search
valkey_db = ValkeySearch(
    collection="my_collection",
    host="localhost",
    port=6379
)

# Search for similar documents
results = valkey_db.search("machine learning", limit=5)
for result in results:
    print(f"Document: {result.content}")
    print(f"Score: {result.score}")
```

## Performance Benefits

- **High-Speed Vector Search**: HNSW algorithm provides sub-linear search complexity
- **Memory Efficiency**: Binary vector encoding reduces storage overhead by 50%
- **Concurrent Operations**: Full async/await support for high-throughput applications
- **Automatic Scaling**: Valkey's clustering capabilities for distributed deployments
- **Real-time Updates**: Live index updates without rebuild requirements

## Use Cases

1. **Retrieval-Augmented Generation (RAG)**: Enhance AI agents with searchable knowledge bases
2. **Semantic Search**: Find documents based on meaning rather than keywords
3. **Recommendation Systems**: Content-based recommendations using vector similarity
4. **Duplicate Detection**: Identify similar content across large document collections
5. **Clustering Analysis**: Group similar documents for organization and analysis

## Getting Started

The Valkey Search integration is part of the Agno framework's vector database ecosystem. To get started:

1. Follow the setup instructions above
2. Explore the cookbook examples in `cookbook/knowledge/vector_db/valkey_db/`
3. Check out the comprehensive tests in the test suite
4. Review the API documentation for advanced configuration options

For production deployments, consider Valkey's clustering capabilities and monitoring tools to ensure optimal performance at scale.