# LightRAG with Agno 🔍

This cookbook demonstrates how to implement **Agentic RAG** (Retrieval-Augmented Generation) using [LightRAG](https://github.com/HKUDS/LightRAG) integrated with Agno. LightRAG provides a fast, graph-based RAG system that enhances document retrieval and knowledge querying capabilities.

## 🌟 Features

- **Graph-based Knowledge Storage**: Leverages Neo4j for storing document relationships
- **Storage Backend**: Supports MongoDB
- **Agentic Search**: Agno agents can intelligently search and retrieve relevant information
- **Real-time Knowledge Updates**: Dynamic document loading and knowledge base updates
- **Multi-modal Support**: Works with various document formats (PDF, Markdown, etc.)

## 📋 Prerequisites

- Python 3.8+
- Docker and Docker Compose (for infrastructure)
- OpenAI API key
- Anthropic API key

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install anthropic
```

### 2. Setup Infrastructure

Deploy the required databases:

#### Neo4j (Graph Database)
```bash
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/testpassword \
  neo4j:latest
```

#### MongoDB (Document Storage)
```bash
docker run -d \
  --name mongodb \
  -p 27017:27017 \
  -e MONGO_INITDB_ROOT_USERNAME=mongoadmin \
  -e MONGO_INITDB_ROOT_PASSWORD=secret \
  mongo:latest
```

### 3. Configure Environment

You will need to clone LightRAG repo in order to run your LightRAG server.
```bash
git clone https://github.com/HKUDS/lightrag.git
```

Copy the example environment file and configure your settings:

```bash
cp .lightrag.env.example .env
```

Key configurations to update:
- `LLM_BINDING_API_KEY`: Your OpenAI API key
- `EMBEDDING_BINDING_API_KEY`: Your embedding model API key
- `NEO4J_PASSWORD`: Neo4j password (default: `testpassword`)
- `MONGO_URI`: MongoDB connection string

### 4. Start LightRAG Server

```bash
cd {lightrag_repo_location}/lightrag
docker-compose up -d
```

The server will be available at `http://localhost:9621`

### 5. Run the Example

```bash
export ANTHROPIC_API_KEY=your_api_key_here
python agentic_rag_with_lightrag.py
```

## 📖 Usage

The example demonstrates how to:

1. **Create a Knowledge Base** that connects to a hosted LightRAG Server
2. **Load Documents** from URLs or local files
3. **Configure an Agent** with agentic search capabilities