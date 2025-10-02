# Vector Databases

Vector databases store embeddings and enable similarity search for knowledge retrieval. Agno supports multiple vector database implementations to fit different deployment needs - from local embedded databases to cloud-hosted solutions.

## Basic Integration

Vector databases integrate with Agno through the Knowledge system:

```python
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

vector_db = PgVector(
    table_name="vectors", 
    db_url=db_url
)


knowledge = Knowledge(
    name="My Knowledge Base",
    vector_db=vector_db
)

agent = Agent(
    knowledge=knowledge, 
    search_knowledge=True
)
```

## Supported Vector Databases

- **[Cassandra](./cassandra_db/)** - Distributed database with vector search
- **[ChromaDB](./chroma_db/)** - Embedded vector database
- **[ClickHouse](./clickhouse_db/)** - Columnar database with vector functions
- **[Couchbase](./couchbase_db/)** - NoSQL database with vector search
- **[LanceDB](./lance_db/)** - Fast columnar vector database
- **[LangChain](./langchain/)** - Use any LangChain vector store
- **[LightRAG](./lightrag/)** - Graph-based RAG system
- **[LlamaIndex](./llamaindex_db/)** - Use LlamaIndex vector stores
- **[Milvus](./milvus_db/)** - Scalable vector database
- **[MongoDB](./mongo_db/)** - Document database with vector search
- **[PgVector](./pgvector/)** - PostgreSQL with vector similarity search
- **[Pinecone](./pinecone_db/)** - Managed vector database
- **[Qdrant](./qdrant_db/)** - Vector search engine
- **[SingleStore](./singlestore_db/)** - Distributed database with vector capabilities
- **[SurrealDB](./surrealdb/)** - Multi-model database with vector capabilities
- **[Upstash](./upstash_db/)** - Serverless vector database
- **[Weaviate](./weaviate_db/)** - Multi-modal vector database