# Vector Databases

Vector databases store embeddings and enable similarity search for knowledge retrieval. This guide covers the vector databases supported by Agno.

## Agent Integration

All vector databases work seamlessly with Agno agents. Simply add the knowledge base to your agent for enhanced responses:

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,  # Your knowledge base
    search_knowledge=True,
)

agent.print_response("Ask anything about your knowledge base")
```

This pattern works with all vector databases shown below - just replace `knowledge` with your configured knowledge base.

## Database Implementations

### 1. PgVector - PostgreSQL Extension (`pgvector/`)

**Strengths**:
- Uses PostgreSQL database you may already have
- Good SQL ecosystem integration
- ACID transactions
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
    index_type="ivfflat",  # or "hnsw" for larger datasets
    lists=100,
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

**Strengths**:
- Fully managed service
- Automatic scaling
- High availability

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

**Strengths**:
- Good filtering and payload support
- High performance
- Cloud or self-hosted options

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

**Strengths**:
- Multi-modal search (text, images, audio)
- Built-in ML models
- GraphQL API

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

**Strengths**:
- Large scale (billions of vectors)
- Good performance optimization
- Multiple index types
- Kubernetes deployment

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

**Strengths**:
- Easy setup
- Good for development and prototyping
- Local file storage

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

**Strengths**:
- Fast local storage
- Columnar format for analytics
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

### LightRAG Integration (`lightrag/`)

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lightrag import LightRag

vector_db = LightRag(
    api_key="your_lightrag_api_key",
)

knowledge = Knowledge(
    name="LightRAG Knowledge Base",
    vector_db=vector_db,
)

knowledge.add_content(
    path="your_document.pdf",
    metadata={"doc_type": "manual"}
)
```