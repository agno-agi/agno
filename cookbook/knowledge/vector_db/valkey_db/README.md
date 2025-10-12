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

- **PDF Content Loading**: Load and process PDF documents from URLs
- **Vector Search Integration**: Automatic embeddings and indexing with Valkey Search
- **Knowledge System Integration**: AI agents with searchable knowledge base
- **Retrieval-Augmented Generation (RAG)**: Agent searches knowledge base to answer questions

## Technical Implementation

- **Embeddings**: OpenAI text-embedding-ada-002 (automatic configuration)
- **Vector Database**: Valkey Search with HNSW indexing
- **Content Processing**: PDF parsing and document chunking
- **Agent Integration**: Knowledge-based question answering

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

This example demonstrates the core functionality: loading a PDF document from a URL into Valkey Search and using an AI agent to answer questions based on the content.

## What This Example Shows

- **Simple Setup**: Minimal code to get started with Valkey Search
- **URL-based Content**: Load documents directly from web URLs
- **Automatic Processing**: Agno handles PDF parsing and vectorization
- **AI Integration**: Agent automatically searches knowledge base for answers

## Next Steps

To extend this example, you could:
1. Add more PDF documents from different URLs
2. Use local files instead of URLs
3. Add different types of content (text, web pages, etc.)
4. Customize the agent's instructions and behavior
5. Implement custom embeddings or search parameters

## Getting Started

1. Follow the setup instructions above
2. Run `python valkey_db.py` to see the example in action
3. Try changing the URL to load different PDF documents
4. Modify the agent's question to test different queries

This example shows how easy it is to create a knowledge-powered AI agent using Valkey Search as the vector database backend.