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

When you run the example, you'll see output demonstrating all Valkey Search features with actual similarity scores:

```
Valkey Search Vector Database Examples
============================================================

Make sure Valkey is running with the search module loaded!
Start Valkey with: docker-compose up -d
Check health with: docker-compose ps

Valkey Search Vector Database Example
==================================================
Creating index...
INFO Created Valkey Search index 'test_collection' with result: OK
Inserting documents...
INFO Inserted 3 documents into Valkey Search index 'test_collection'
Searching for 'programming languages'...
Found 3 results:
1. Python is a high-level programming language.... (score: 0.1335)
   Metadata: {'category': 'programming', 'language': 'python'}

2. Machine learning is a subset of artificial intelli... (score: 0.2202)
   Metadata: {'category': 'AI', 'topic': 'machine learning'}

3. Vector databases store and search high-dimensional... (score: 0.2539)
   Metadata: {'category': 'database', 'type': 'vector'}

Cleaning up...
INFO Dropped Valkey Search index 'test_collection' with result: OK

Async Valkey Search Example
==================================================
Creating index...
INFO Created Valkey Search index 'async_test_collection' with result: OK
Inserting documents...
INFO Inserted 2 documents into Valkey Search index 'async_test_collection'
Searching for 'async programming'...
Found 2 results:
1. Asynchronous programming allows concurrent executi... (score: 0.0968)
   Metadata: {'category': 'programming', 'type': 'async'}

2. Event loops manage asynchronous operations efficie... (score: 0.1484)
   Metadata: {'category': 'programming', 'type': 'async'}

Cleaning up...
INFO Dropped Valkey Search index 'async_test_collection' with result: OK

Valkey Search with Knowledge System
==================================================
INFO Created Valkey Search index 'knowledge_collection' with result: OK
Adding documents to knowledge base...
INFO Adding content from AI Technology
INFO Inserted 1 documents into Valkey Search index 'knowledge_collection'
INFO Adding content from Blockchain Technology
INFO Inserted 1 documents into Valkey Search index 'knowledge_collection'
INFO Adding content from Quantum Computing
INFO Inserted 1 documents into Valkey Search index 'knowledge_collection'

Querying agent with knowledge...
Agent response: Several technologies are currently transforming industries across the globe:

1. **Artificial Intelligence (AI):** AI is significantly transforming industries by offering advanced data processing capabilities, automation, predictive analytics, and improved decision-making processes.

2. **Blockchain Technology:** Blockchain enables decentralized systems, which enhance transparency, security, and efficiency in various sectors, including finance, supply chain, and healthcare.

3. **Internet of Things (IoT):** IoT connects devices and systems, facilitating real-time data exchange and monitoring. This is transforming industries like manufacturing, healthcare, and transportation through enhanced tracking and efficiency.

And more technologies...

Cleaning up...
INFO Dropped Valkey Search index 'knowledge_collection' with result: OK

Advanced Valkey Search Example
==================================================
Creating index...
INFO Created Valkey Search index 'advanced_collection' with result: OK
Inserting documents...
INFO Inserted 4 documents into Valkey Search index 'advanced_collection'
Searching for 'technology innovation'...
Found 3 results:
1. Artificial intelligence is transforming industries... (score: 0.1542)
   Metadata: {'category': 'technology', 'topic': 'AI', 'year': 2024}

2. Blockchain technology enables decentralized system... (score: 0.2014)
   Metadata: {'category': 'technology', 'topic': 'blockchain', 'year': 2024}

3. Quantum computing promises exponential speedups.... (score: 0.2087)
   Metadata: {'category': 'science', 'topic': 'quantum', 'year': 2024}

Searching for 'quantum research'...
Found 3 results:
1. Quantum computing promises exponential speedups.... (score: 0.1473)
   Metadata: {'category': 'science', 'topic': 'quantum', 'year': 2024}

2. Climate change research requires urgent action.... (score: 0.2083)
   Metadata: {'category': 'science', 'topic': 'climate', 'year': 2024}

3. Artificial intelligence is transforming industries... (score: 0.2279)
   Metadata: {'category': 'technology', 'topic': 'AI', 'year': 2024}

Cleaning up...
INFO Dropped Valkey Search index 'advanced_collection' with result: OK
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

### Basic Vector Search
```python
from agno.vectordb.valkey import ValkeySearch
from agno.knowledge.embedder.openai import OpenAIEmbedder

# Initialize Valkey Search
valkey_db = ValkeySearch(
    collection="my_collection",
    embedder=OpenAIEmbedder(),
    host="localhost",
    port=6379
)

# Search for similar documents
results = valkey_db.search("machine learning", limit=5)
for result in results:
    print(f"Document: {result.content}")
    print(f"Score: {result.score}")
```

### Knowledge System Integration
```python
from agno import Agent
from agno.knowledge import AgentKnowledge
from agno.models.openai import OpenAIChat

# Create agent with Valkey-powered knowledge
knowledge = AgentKnowledge(
    vector_db=ValkeySearch(collection="knowledge_base"),
    num_documents=10
)

agent = Agent(
    model=OpenAIChat(id="gpt-4"),
    knowledge=knowledge
)

# Agent automatically uses Valkey Search for RAG
response = agent.run("What is quantum computing?")
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