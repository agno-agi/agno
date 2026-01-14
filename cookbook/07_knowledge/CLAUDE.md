# CLAUDE.md - Knowledge Cookbook

Instructions for Claude Code when testing the knowledge cookbooks.

---

## Overview

This folder contains **knowledge and RAG** examples - everything related to vector databases, embeddings, chunking, readers, and retrieval.

**Total Examples:** 204
**Subfolders:** 9

---

## Quick Reference

**Test Environment:**
```bash
.venvs/demo/bin/python
./cookbook/scripts/run_pgvector.sh  # For PgVector examples
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/08_knowledge/basic_operations/sync/01_from_path.py
```

---

## Folder Structure

| Folder | Count | Description |
|:-------|------:|:------------|
| `basic_operations/` | 33 | Add content from paths, URLs, topics |
| `chunking/` | 13 | Text chunking strategies |
| `custom_retriever/` | 4 | Custom retrieval logic |
| `embedders/` | 29 | All embedding providers |
| `filters/` | 20 | Metadata filtering |
| `readers/` | 24 | File format readers |
| `search_type/` | 4 | Hybrid, semantic search |
| `vector_db/` | 75 | All vector database backends |
| `testing_resources/` | 0 | Test data |

---

## Key Components

### Embedders (29 providers)
OpenAI, Cohere, Gemini, Mistral, Azure, AWS Bedrock, Jina, Voyage, HuggingFace, Ollama, vLLM, and more.

### Vector Databases (75 examples)
- **PgVector** - PostgreSQL extension
- **LanceDb** - Local, serverless
- **ChromaDb** - Local, embedded
- **Pinecone** - Cloud native
- **Qdrant** - High performance
- **Milvus** - Distributed
- **Weaviate** - GraphQL-based
- **MongoDB Atlas** - Document + vector

### Chunking Strategies
- Fixed size
- Recursive
- Semantic
- Markdown-aware
- Agentic (LLM-based)

### Readers
PDF, DOCX, JSON, CSV, Arxiv, YouTube, S3, GCS, and more.

---

## Testing Priorities

### No External Dependencies
- `basic_operations/sync/01_from_path.py`
- `vector_db/lancedb/` - Local, serverless
- `vector_db/chromadb/` - Local, embedded

### Common Production
- `vector_db/pgvector/` - Most common
- `embedders/openai_embedder.py`
- `filters/filtering_pgvector.py`

---

## API Keys Required

| Provider | Key |
|:---------|:----|
| OpenAI | `OPENAI_API_KEY` |
| Cohere | `CO_API_KEY` |
| Gemini | `GOOGLE_API_KEY` |
| Pinecone | `PINECONE_API_KEY` |
| Jina | `JINA_API_KEY` |
