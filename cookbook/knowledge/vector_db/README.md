# Vector Databases

Vector databases are the backbone of modern AI knowledge systems, storing high-dimensional embeddings that enable semantic search and similarity matching. Choosing the right vector database impacts performance, scalability, and cost.

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Vector Database** | Storage system optimized for embedding vectors and similarity search |
| **PgVector** | PostgreSQL extension for vector operations |
| **Qdrant** | Specialized vector database with high performance |
| **ChromaDB** | Open-source embedding database |
| **Collection** | Named container for storing vectors in a database |

## Getting Started

### 1. PgVector (PostgreSQL)

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

vector_db = PgVector(
    table_name="vectors", 
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
)

knowledge = Knowledge(
    name="My PG Vector Knowledge Base",
    vector_db=vector_db,
)

knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)
```

### 2. Qdrant

```python
from agno.vectordb.qdrant import Qdrant
from agno.db.postgres.postgres import PostgresDb

vector_db = Qdrant(
    collection="thai-recipes", 
    url="http://localhost:6333"
)

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)

knowledge = Knowledge(
    vector_db=vector_db,
    contents_db=contents_db,
)
```

### 3. ChromaDB

```python
from agno.vectordb.chroma import ChromaDb

knowledge = Knowledge(
    vector_db=ChromaDb(
        collection="vectors", 
        path="tmp/chromadb", 
        persistent_client=True
    ),
)

await knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)
```

### Performance & Features Matrix

| Database | Vector Dims | Metadata Filtering | Hybrid Search | Multi-Tenancy | Open Source |
|----------|-------------|-------------------|---------------|---------------|-------------|
| **PgVector** | 16,000 | ✅ Excellent | ✅ | ✅ | ✅ |
| **Pinecone** | 40,000 | ✅ Good | ✅ | ✅ | ❌ |
| **Qdrant** | 65,536 | ✅ Excellent | ✅ | ✅ | ✅ |
| **Weaviate** | 65,536 | ✅ Excellent | ✅ | ✅ | ✅ |
| **Chroma** | Unlimited | ✅ Good | ❌ | ✅ | ✅ |
| **Milvus** | 32,768 | ✅ Excellent | ✅ | ✅ | ✅ |

## Database Implementations

### 1. PgVector - PostgreSQL Extension (`pgvector/`)

**When to use**: Best overall choice for most applications, especially when you already use PostgreSQL.

**Strengths**:
- Mature, battle-tested PostgreSQL foundation
- Excellent SQL ecosystem integration
- Strong consistency and ACID transactions
- Cost-effective for small to medium scale

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType

# Basic PgVector setup
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="company_knowledge",
        db_url=db_url,
        search_type=SearchType.hybrid,  # Vector + keyword search
        dimensions=1536,  # OpenAI embedding dimensions
    )
)

# Add content with metadata
knowledge.add_content(
    path="company_docs/",
    metadata={
        "department": "engineering",
        "document_type": "technical_spec",
        "access_level": "internal"
    }
)

# Advanced PgVector configuration
advanced_vector_db = PgVector(
    table_name="advanced_knowledge",
    db_url=db_url,
    search_type=SearchType.hybrid,
    # Performance optimizations
    connection_pool_size=20,
    max_overflow=10,
    # Index configuration
    index_type="ivfflat",  # or "hnsw" for larger datasets
    lists=100,  # Number of clusters for ivfflat
    # Metadata indexing
    metadata_indexes=["department", "document_type", "created_at"]
)
```

**Best practices**:
- Use connection pooling for production
- Create indexes on frequently filtered metadata fields
- Choose appropriate index type (ivfflat vs hnsw) based on dataset size
- Monitor query performance and optimize accordingly

**Examples**:
- **[Basic PgVector](./pgvector/pgvector_db.py)** - Simple setup and usage
- **[Async PgVector](./pgvector/async_pg_vector.py)** - Asynchronous operations
- **[Hybrid Search](./pgvector/pgvector_hybrid_search.py)** - Combined vector/keyword search

### 2. Cloud Vector Databases

#### Pinecone (`pinecone_db/`)

**When to use**: Fully managed service with minimal operational overhead.

**Strengths**:
- Zero infrastructure management
- Automatic scaling and optimization
- High availability and durability
- Great developer experience

```python
from agno.vectordb.pinecone import PineconeDB

pinecone_db = PineconeDB(
    name="company-knowledge",
    dimension=1536,
    metric="cosine",
    environment="us-west1-gcp-free",  # Choose your region
    api_key="your_pinecone_api_key"
)

knowledge = Knowledge(
    vector_db=pinecone_db,
    name="Pinecone Knowledge Base"
)
```

#### Qdrant (`qdrant_db/`)

**When to use**: High-performance vector search with excellent filtering capabilities.

**Strengths**:
- Outstanding filtering and payload support
- High performance and efficiency
- Flexible deployment options (cloud or self-hosted)
- Advanced vector operations

```python
from agno.vectordb.qdrant import Qdrant

# Qdrant Cloud
qdrant_cloud = Qdrant(
    collection="company_knowledge",
    url="https://your-cluster.qdrant.io:6333",
    api_key="your_qdrant_api_key",
    distance="Cosine"
)

# Self-hosted Qdrant
qdrant_local = Qdrant(
    collection="local_knowledge",
    url="http://localhost:6333",
    distance="Cosine",
    # Advanced configuration
    vector_size=1536,
    on_disk_payload=True,  # Store large payloads on disk
    replication_factor=2,   # For high availability
)
```

### 3. Enterprise Solutions

#### Weaviate (`weaviate_db/`)

**When to use**: Complex multi-modal applications with advanced AI capabilities.

**Strengths**:
- Multi-modal vector search (text, images, audio)
- Built-in ML models and transformers
- GraphQL API
- Advanced schema and data modeling

```python
from agno.vectordb.weaviate import Weaviate

weaviate_db = Weaviate(
    url="http://localhost:8080",
    # For Weaviate Cloud
    # url="https://your-cluster.weaviate.network",
    # api_key="your_weaviate_api_key",
    
    class_name="CompanyKnowledge",
    schema={
        "class": "CompanyKnowledge",
        "vectorizer": "text2vec-openai",
        "properties": [
            {"name": "content", "dataType": ["text"]},
            {"name": "department", "dataType": ["string"]},
            {"name": "document_type", "dataType": ["string"]},
            {"name": "created_at", "dataType": ["date"]}
        ]
    }
)
```

#### Milvus (`milvus_db/`)

**When to use**: Large-scale applications requiring horizontal scaling and high throughput.

**Strengths**:
- Massive scale (billions of vectors)
- Excellent performance optimization
- Multiple index types and metrics
- Kubernetes-native deployment

```python
from agno.vectordb.milvus import Milvus

milvus_db = Milvus(
    collection_name="enterprise_knowledge",
    host="localhost",
    port="19530",
    # For production clusters
    # uri="https://your-milvus-cluster.com:443",
    # token="your_access_token",
    
    # Schema configuration
    dimension=1536,
    index_type="IVF_FLAT",
    metric_type="L2",
    
    # Performance settings
    nlist=1024,  # Number of clusters
    m=8,         # Number of sub-quantizers for PQ
)
```

### 4. Embedded Databases

#### ChromaDB (`chroma_db/`)

**When to use**: Development, prototyping, and small-scale applications.

**Strengths**:
- Easy setup and deployment
- Good developer experience
- Suitable for experimentation
- Local file-based storage

```python
from agno.vectordb.chroma import ChromaDB

# Persistent ChromaDB
chroma_db = ChromaDB(
    collection_name="dev_knowledge",
    persistent_client_path="./chroma_data",  # Local storage
    # Optional: Custom embedding function
    embedding_function=None  # Uses default
)

# In-memory ChromaDB (for testing)
chroma_memory = ChromaDB(
    collection_name="temp_knowledge",
    persistent_client_path=None  # In-memory only
)
```

#### LanceDB (`lance_db/`)

**When to use**: Fast local development and applications requiring columnar analytics.

**Strengths**:
- Fast local storage
- Columnar format for analytics
- TypeScript/Rust performance
- Good for time-series data

```python
from agno.vectordb.lancedb import LanceDb

lance_db = LanceDb(
    table_name="analytics_knowledge",
    uri="./lance_data",  # Local directory
    # Advanced configuration
    vector_column_name="embedding",
    text_column_name="content",
    batch_size=1000,
)
```

## Framework Integrations

### LangChain Integration (`langchain/`)

**When to use**: Existing LangChain applications or preference for LangChain ecosystem.

```python
from agno.vectordb.langchain import LangChainVectorDB
from langchain_community.vectorstores import Chroma

# Use any LangChain vector store
langchain_chroma = Chroma(
    persist_directory="./langchain_chroma",
    embedding_function=OpenAIEmbeddings()
)

# Wrap for Agno compatibility
agno_langchain_db = LangChainVectorDB(
    langchain_vectorstore=langchain_chroma
)

knowledge = Knowledge(vector_db=agno_langchain_db)
```

### LlamaIndex Integration (`llamaindex_db/`)

**When to use**: Leveraging LlamaIndex's advanced indexing and retrieval strategies.

```python
from agno.vectordb.llamaindex import LlamaIndexVectorDB
from llama_index.vector_stores.chroma import ChromaVectorStore

# Create LlamaIndex vector store
llama_chroma = ChromaVectorStore(
    chroma_collection=chroma_collection
)

# Wrap for Agno
agno_llama_db = LlamaIndexVectorDB(
    llamaindex_vectorstore=llama_chroma
)
```

## Common Issues and Solutions

**Problem**: Slow vector search performance
**Solutions**: Optimize indexes, increase resources, use approximate search, implement caching

**Problem**: High memory usage with large embeddings
**Solutions**: Use disk-based storage, implement compression, consider lower-dimensional embeddings

**Problem**: Inconsistent search results
**Solutions**: Ensure consistent embedding models, validate data integrity, check index configuration

**Problem**: Database connection issues in production
**Solutions**: Implement connection pooling, retry logic, health checks, and monitoring

**Problem**: Scaling challenges with growing data
**Solutions**: Implement sharding, use distributed databases, optimize data partitioning strategies
