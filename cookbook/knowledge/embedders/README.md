# Embedding Models

Embedders convert text into vector representations for semantic search and knowledge retrieval. Agno supports multiple embedding providers to fit different deployment needs.

## Setup

Choose your preferred provider and install dependencies:

```bash
# OpenAI (default)
pip install agno openai
export OPENAI_API_KEY=your_api_key

# Local models with Ollama
pip install agno ollama

# HuggingFace models
pip install agno transformers torch

# Cloud providers
pip install agno cohere google-generativeai
```

## Embedding Dimensions

Different models produce different vector dimensions. Higher dimensions can capture more nuanced meaning but require more storage:

```python
# Example dimension sizes
embedder_dimensions = {
    'text-embedding-3-small': 1536,
    'text-embedding-3-large': 3072,
    'cohere-embed-english-v3.0': 1024,
    'all-MiniLM-L6-v2': 384,
}
```

## Basic Integration

Embedders integrate with vector databases through the Knowledge system:

```python
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.vectordb.pgvector import PgVector

knowledge = Knowledge(
    vector_db=PgVector(
        embedder=OpenAIEmbedder(),
        table_name="knowledge",
        db_url="your_db_url"
    )
)
```

## Supported Embedding Providers

- **[AWS Bedrock](./aws_bedrock_embedder.py)** - AWS models
- **[Azure OpenAI](./azure_embedder.py)** - OpenAI models via Azure
- **[Cohere](./cohere_embedder.py)** - Multilingual embedding models
- **[Fireworks](./fireworks_embedder.py)** - Fast inference embedding models
- **[Google Gemini](./gemini_embedder.py)** - Google's embedding models
- **[HuggingFace](./huggingface_embedder.py)** - Transformers library models
- **[Jina](./jina_embedder.py)** - Jina AI embedding models
- **[LangDB](./langdb_embedder.py)** - LangDB embedding service
- **[Mistral](./mistral_embedder.py)** - Mistral AI embedding models
- **[Nebius](./nebius_embedder.py)** - Nebius embedding service
- **[Ollama](./ollama_embedder.py)** - Local models via Ollama
- **[OpenAI](./openai_embedder.py)** - OpenAI embedding models (default)
- **[Qdrant FastEmbed](./qdrant_fastembed.py)** - Fast local embeddings
- **[SentenceTransformers](./sentence_transformer_embedder.py)** - Local transformer models
- **[Together](./together_embedder.py)** - Together AI embedding models
- **[VoyageAI](./voyageai_embedder.py)** - VoyageAI embedding models
