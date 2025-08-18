# Embedding Models & Providers

Embedders convert text into vector representations that capture semantic meaning for similarity search and knowledge retrieval. Choosing the right embedder significantly impacts your agent's understanding and retrieval quality.

Embeddings are the foundation of semantic search because they:
- **Capture semantic meaning** beyond keyword matching
- **Enable similarity search** across different phrasings
- **Support multilingual** understanding
- **Power vector databases** for efficient retrieval

## Setup

Choose your preferred provider and install dependencies:

```bash
# OpenAI (Recommended for most use cases)
pip install agno openai
export OPENAI_API_KEY=your_api_key

# Local models with Ollama
pip install agno ollama
# Install Ollama: https://ollama.ai

# HuggingFace models
pip install agno transformers torch

# Cloud providers
pip install agno cohere anthropic google-generativeai
```

## Core Concepts

### Embedding Dimensions and Performance

```python
# Higher dimensions = more nuanced understanding, larger storage
embedder_comparison = {
    'text-embedding-3-small': {'dimensions': 1536, 'speed': 'fast', 'quality': 'good'},
    'text-embedding-3-large': {'dimensions': 3072, 'speed': 'medium', 'quality': 'excellent'},
    'cohere-embed-english-v3.0': {'dimensions': 1024, 'speed': 'fast', 'quality': 'excellent'},
}
```

## Embedding Providers

### 1. OpenAI Embedders (`openai_embedder.py`)

**When to use**: Best overall choice for most applications.

**Models available**:
- `text-embedding-3-small`: Fast, cost-effective, good quality
- `text-embedding-3-large`: Higher quality, more expensive
- `text-embedding-ada-002`: Legacy model, still reliable

```python
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Default model (text-embedding-3-small)
knowledge = Knowledge(
    vector_db=PgVector(
        embedder=OpenAIEmbedder(),
        table_name="openai_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)

# High-quality model for better accuracy
knowledge_premium = Knowledge(
    vector_db=PgVector(
        embedder=OpenAIEmbedder(model="text-embedding-3-large"),
        table_name="premium_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
```

**Best practices**:
- Use `text-embedding-3-small` for most applications
- Use `text-embedding-3-large` for nuanced understanding requirements
- Monitor usage costs in high-volume applications

### 2. Local Models (`ollama_embedder.py`, `sentence_transformer_embedder.py`)

**When to use**: Privacy requirements, cost control, offline deployment.

```python
# Ollama - Easy local deployment
from agno.knowledge.embedder.ollama import OllamaEmbedder

ollama_embedder = OllamaEmbedder(
    model="nomic-embed-text",  # Recommended local model
    host="http://localhost:11434"
)

# SentenceTransformers - Direct model loading
from agno.knowledge.embedder.sentence_transformer import SentenceTransformerEmbedder

st_embedder = SentenceTransformerEmbedder(
    model_name="all-MiniLM-L6-v2"  # Fast, good quality
)
```

**Popular local models**:
- `nomic-embed-text`: High quality, good speed
- `all-MiniLM-L6-v2`: Fast, lightweight
- `all-mpnet-base-v2`: Better quality, slower
- `multilingual-e5-base`: Multilingual support

### 3. Cloud Providers

#### Cohere (`cohere_embedder.py`)
**Strengths**: Excellent multilingual support, enterprise features

```python
from agno.knowledge.embedder.cohere import CohereEmbedder

cohere_embedder = CohereEmbedder(
    model="embed-english-v3.0",  # or embed-multilingual-v3.0
    api_key="your_cohere_api_key"
)
```

#### Azure OpenAI (`azure_embedder.py`)
**Strengths**: Enterprise compliance, regional data residency

```python
from agno.knowledge.embedder.azure import AzureEmbedder

azure_embedder = AzureEmbedder(
    model="text-embedding-3-small",
    api_key="your_azure_key",
    base_url="https://your-resource.openai.azure.com/"
)
```

#### Google Gemini (`gemini_embedder.py`)
**Strengths**: Integration with Google Cloud, competitive pricing

```python
from agno.knowledge.embedder.gemini import GeminiEmbedder

gemini_embedder = GeminiEmbedder(
    model="text-embedding-004",
    api_key="your_google_api_key"
)
```

### 4. Specialized Providers

#### VoyageAI (`voyageai_embedder.py`)
**Strengths**: Domain-specific models, high performance

```python
from agno.knowledge.embedder.voyageai import VoyageAIEmbedder

voyage_embedder = VoyageAIEmbedder(
    model="voyage-2",  # General purpose
    # model="voyage-code-2",  # Code-specific
    # model="voyage-law-2",   # Legal documents
)
```

#### AWS Bedrock (`aws_bedrock_embedder.py`)
**Strengths**: AWS ecosystem integration, multiple model choices

```python
from agno.knowledge.embedder.aws_bedrock import AWSBedrockEmbedder

bedrock_embedder = AWSBedrockEmbedder(
    model="amazon.titan-embed-text-v1",
    region="us-east-1"
)
```

## Common Issues and Solutions

**Problem**: High embedding costs
**Solutions**: Use local models, batch processing, caching, smaller models

**Problem**: Poor retrieval quality
**Solutions**: Try higher-quality models, domain-specific embedders, better chunking

**Problem**: Slow embedding speed
**Solutions**: Use local models, batch processing, async processing

**Problem**: Multilingual support needed
**Solutions**: Use Cohere multilingual, mBERT variants, or Google models

**Problem**: Privacy/compliance requirements
**Solutions**: Use local models (Ollama, SentenceTransformers), on-premise deployment
