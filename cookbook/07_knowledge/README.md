# Knowledge: RAG for Agents

Give agents access to your documents, databases, and APIs through Retrieval-Augmented Generation.

## Overview

Knowledge is Agno's RAG framework. It handles the full pipeline: reading documents, chunking them, embedding chunks, storing them in a vector database, and retrieving relevant content when agents need it.

| Component | What It Does | Options |
|-----------|-------------|---------|
| **Readers** | Extract text from files | PDF, DOCX, CSV, JSON, Web, YouTube, ArXiv |
| **Chunking** | Split text into searchable pieces | Fixed, Recursive, Semantic, Code, Markdown, Agentic |
| **Embedders** | Convert text to vectors | OpenAI, Cohere, Bedrock, Ollama, 14+ more |
| **Vector DBs** | Store and search vectors | Qdrant, LanceDB, ChromaDB, Pinecone, 14+ more |
| **Rerankers** | Re-score results for quality | Cohere, SentenceTransformer, Bedrock, Infinity |

## Quick Start

```python
from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant, SearchType

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="my_docs",
        url="http://localhost:6333",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

knowledge.insert(url="https://example.com/document.pdf")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

agent.print_response("What does the document say about X?")
```

## Cookbook Structure

```
cookbook/07_knowledge/
|-- 01_getting_started/        Start here
|   |-- 01_basic_rag.py            Traditional RAG with context injection
|   |-- 02_agentic_rag.py          Agent-driven search decisions
|   |-- 03_loading_content.py      All source types: file, URL, text, topics
|   +-- 04_choosing_components.md  Decision guide
|
|-- 02_building_blocks/        Core components
|   |-- 01_chunking_strategies.py  Side-by-side comparison
|   |-- 02_hybrid_search.py        Vector + keyword + hybrid
|   |-- 03_reranking.py            Two-stage retrieval
|   |-- 04_filtering.py            Dict + FilterExpr
|   |-- 05_agentic_filtering.py    Agent-driven filters
|   +-- 06_embedders.py            Embedder comparison
|
|-- 03_production/             Real-world patterns
|   |-- 01_multi_source_rag.py     Multiple content types
|   |-- 02_knowledge_lifecycle.py  Insert, update, remove, track
|   |-- 03_multi_tenant.py         Per-tenant isolation
|   +-- 04_error_handling.py       Robust ingestion
|
|-- 04_advanced/               Power user patterns
|   |-- 01_custom_retriever.py     Custom retrieval function
|   |-- 02_custom_chunking.py      Custom chunking strategy
|   |-- 03_graph_rag.py            LightRAG integration
|   |-- 04_knowledge_tools.py      Think/search/analyze tools
|   +-- 05_knowledge_protocol.py   Custom KnowledgeProtocol
|
|-- 05_integrations/           Specific providers
|   |-- readers/                   PDF, CSV, JSON, Web, etc.
|   |-- cloud/                     S3, Azure, GCS
|   +-- vector_dbs/                Qdrant, ChromaDB, Pinecone, etc.
|
+-- reference/                 Decision guides
    |-- vector_db_comparison.md
    |-- embedder_comparison.md
    +-- chunking_decision_guide.md
```

## Running the Cookbooks

### 1. Start Qdrant

```bash
./cookbook/scripts/run_qdrant.sh
```

### 2. Set API Keys

```bash
export OPENAI_API_KEY=your-key
```

### 3. Run Examples

```bash
# Start with basic RAG
.venvs/demo/bin/python cookbook/07_knowledge/01_getting_started/01_basic_rag.py

# Try agentic RAG
.venvs/demo/bin/python cookbook/07_knowledge/01_getting_started/02_agentic_rag.py

# Explore building blocks
.venvs/demo/bin/python cookbook/07_knowledge/02_building_blocks/01_chunking_strategies.py
```

## Two RAG Modes

| Mode | Parameter | How It Works |
|------|-----------|-------------|
| **Basic RAG** | `add_knowledge_to_context=True` | Context auto-injected into prompt |
| **Agentic RAG** | `search_knowledge=True` | Agent gets search tool, decides when to use it |

Agentic RAG is the default and recommended for most use cases.
