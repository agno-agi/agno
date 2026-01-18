# LightRAG with Agno 🔍

This cookbook demonstrates how to implement **Agentic RAG** (Retrieval-Augmented Generation) using [LightRAG](https://github.com/HKUDS/LightRAG) integrated with Agno. LightRAG provides a fast, graph-based RAG system that enhances document retrieval and knowledge querying capabilities.

---

## 🌟 Features

- **Agentic Search** → Agno agents can intelligently search and retrieve relevant information
- **Real-time Knowledge Updates** → Dynamic document loading and knowledge base updates
- **Multi-modal Support** → Works with various document formats (PDF, Markdown, etc.)

---

## 📖 What You'll Learn

The example demonstrates how to:

1. **Create a Knowledge Base** that connects to a hosted LightRAG Server
2. **Load Documents** from URLs or local files  
3. **Configure an Agent** with agentic search capabilities

---

## 📋 Prerequisites

Before getting started, ensure you have:

- **Python 3.8+** installed
- **Docker & Docker Compose** for infrastructure setup
- **OpenAI API key** for LLM and embedding services

---

## 🚀 Quick Start

### Step 1: Configure Environment

Edit the provided environment file:

```bash
cookbook/agent_concepts/agentic_search/lightrag/.env
```

Add your API keys as required. For detailed configuration, visit the official [LightRAG documentation](https://github.com/HKUDS/LightRAG/blob/main/lightrag/api/README.md).

> **Note:** The example uses OpenAI for both LLM and embedding provision.

**Key configurations to update:**
```env
LLM_BINDING_API_KEY=your_openai_api_key_here
EMBEDDING_BINDING_API_KEY=your_embedding_api_key_here
```

### Step 2: Deploy Infrastructure  

Deploy the LightRAG server using the provided Docker Compose file:

```bash
cd cookbook/agent_concepts/agentic_search/lightrag/
docker-compose up -d
```

✅ **Server will be available at:** `http://localhost:9621`

### Step 3: Run the Example

Execute the main example script:

```bash
python cookbook/agent_concepts/agentic_search/lightrag/agentic_rag_with_lightrag.py
```

---

## ⚠️ Important Note

**Document Processing Time:** Loading documents into the LightRAG server requires processing time. 

**Recommended workflow:**
1. Run the `knowledge_base.load()` function
2. Navigate to your LightRAG server (`http://localhost:9621`)
3. Monitor the file processing status
4. Once processing is complete, proceed with your queries

---

## 🔗 Additional Resources

- [LightRAG Official Repository](https://github.com/HKUDS/LightRAG)
- [LightRAG API Documentation](https://github.com/HKUDS/LightRAG/blob/main/lightrag/api/README.md)
- [Agno Documentation](https://agno.ai)

