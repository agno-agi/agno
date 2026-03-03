# Vector Databases

Agno supports **18+ vector database backends** for storing and searching knowledge embeddings. All backends share the same interface — swap one line to change storage.

**Directory:** `libs/agno/agno/vectordb/`

---

## Unified interface

Every vector DB implementation exposes the same core methods:

```python
class VectorDb:
    def insert(self, documents: list[Document]) -> None: ...
    def upsert(self, documents: list[Document]) -> None: ...
    def search(self, query: str, num_documents: int) -> list[Document]: ...
    def delete(self) -> None: ...
    def exists(self) -> bool: ...
    def drop_table(self) -> None: ...
```

Swap backends without changing agent code:

```python
# Development: embedded Chroma
from agno.vectordb.chroma import ChromaDb
vdb = ChromaDb(collection="knowledge", path="./chroma_db")

# Production: pgvector on Postgres
from agno.vectordb.pgvector import PgVector
vdb = PgVector(table_name="knowledge", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Cloud: Pinecone
from agno.vectordb.pineconedb import PineconeDb
vdb = PineconeDb(name="knowledge", dimension=1536, metric="cosine")

# Same knowledge base either way:
from agno.knowledge import Knowledge
knowledge = Knowledge(vector_db=vdb, sources=[...])
```

---

## Supported backends

### SQL-based

#### pgvector (PostgreSQL)
**Module:** `agno.vectordb.pgvector`
**Best for:** Production deployments, teams already using PostgreSQL, simple ops

```python
from agno.vectordb.pgvector import PgVector
from agno.embedder.openai import OpenAIEmbedder

vdb = PgVector(
    table_name="recipes",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    search_type="hybrid",   # "vector" | "keyword" | "hybrid"
)
```

Supported search types:
- `"vector"` — cosine / L2 similarity
- `"keyword"` — full-text search (tsvector)
- `"hybrid"` — combine both with Reciprocal Rank Fusion

---

### Dedicated vector databases

#### Qdrant
**Module:** `agno.vectordb.qdrant`
**Best for:** High throughput, on-prem or Qdrant Cloud, filterable payloads

```python
from agno.vectordb.qdrant import Qdrant

vdb = Qdrant(
    collection="knowledge",
    url="http://localhost:6333",
    # api_key="..." for Qdrant Cloud
)
```

#### Pinecone
**Module:** `agno.vectordb.pineconedb`
**Best for:** Fully managed cloud, no infra to run

```python
from agno.vectordb.pineconedb import PineconeDb

vdb = PineconeDb(
    name="my-index",
    dimension=1536,
    metric="cosine",
    spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
)
```

#### Weaviate
**Module:** `agno.vectordb.weaviate`
**Best for:** Hybrid search (vector + BM25), GraphQL API, multi-tenancy

```python
from agno.vectordb.weaviate import Weaviate

vdb = Weaviate(
    collection="Article",
    url="http://localhost:8080",
)
```

#### Chroma
**Module:** `agno.vectordb.chroma`
**Best for:** Development, embedded usage, zero infra

```python
from agno.vectordb.chroma import ChromaDb

# Embedded (in-process, no server)
vdb = ChromaDb(collection="docs", path="./chroma_db")

# Client-server mode
vdb = ChromaDb(
    collection="docs",
    host="localhost",
    port=8000,
)
```

#### Milvus
**Module:** `agno.vectordb.milvus`
**Best for:** Large-scale, billions of vectors, distributed architecture

```python
from agno.vectordb.milvus import Milvus

vdb = Milvus(
    collection="knowledge",
    uri="http://localhost:19530",
)
```

#### LanceDB
**Module:** `agno.vectordb.lancedb`
**Best for:** Embedded columnar storage, no server needed, fast scan

```python
from agno.vectordb.lancedb import LanceDb

vdb = LanceDb(
    table_name="knowledge",
    uri="./lancedb_data",   # local path or s3://bucket/path
)
```

---

### Database-embedded vector search

#### MongoDB Atlas Vector Search
**Module:** `agno.vectordb.mongodb`
**Best for:** Teams already on MongoDB Atlas

```python
from agno.vectordb.mongodb import MongoDb

vdb = MongoDb(
    collection_name="knowledge",
    db_url="mongodb+srv://...",
    database_name="agno",
    index_name="vector_index",
)
```

#### Redis Vector Search
**Module:** `agno.vectordb.redis`
**Best for:** Ultra-low latency, caching layer, existing Redis infra

```python
from agno.vectordb.redis import RedisDb

vdb = RedisDb(
    prefix="agno:knowledge",
    host="localhost",
    port=6379,
)
```

#### Cassandra
**Module:** `agno.vectordb.cassandra`
**Best for:** Multi-region, high write throughput, existing Cassandra

```python
from agno.vectordb.cassandra import Cassandra

vdb = Cassandra(
    table="knowledge",
    keyspace="agno",
)
```

#### ClickHouse
**Module:** `agno.vectordb.clickhouse`
**Best for:** Analytics + vector search in the same system

```python
from agno.vectordb.clickhouse import ClickHouseVdb

vdb = ClickHouseVdb(
    table_name="knowledge",
    host="localhost",
    port=8123,
)
```

#### Couchbase
**Module:** `agno.vectordb.couchbase`
**Best for:** Mobile-sync, existing Couchbase deployments

```python
from agno.vectordb.couchbase import CouchbaseSearch

vdb = CouchbaseSearch(
    bucket_name="agno",
    scope_name="_default",
    collection_name="knowledge",
    index_name="vector_search_index",
    connection_string="couchbase://localhost",
)
```

#### SingleStore
**Module:** `agno.vectordb.singlestore`
**Best for:** Mixed SQL + vector workloads, real-time analytics

```python
from agno.vectordb.singlestore import S2VectorDb

vdb = S2VectorDb(
    collection="knowledge",
    db_url="mysql+pymysql://user:pass@host:3306/agno",
)
```

#### SurrealDB
**Module:** `agno.vectordb.surrealdb`
**Best for:** Multi-model (graph + document + vector), modern stack

```python
from agno.vectordb.surrealdb import SurrealDb

vdb = SurrealDb(
    collection="knowledge",
    url="http://localhost:8000",
)
```

#### Upstash Vector
**Module:** `agno.vectordb.upstashdb`
**Best for:** Serverless, edge deployments, zero-ops

```python
from agno.vectordb.upstashdb import UpstashVector

vdb = UpstashVector(
    index_url="https://...-vector.upstash.io",
    index_token="...",
)
```

---

### Adapter backends (integrate existing libraries)

#### LlamaIndex VectorStore
**Module:** `agno.vectordb.llamaindex`
Use any LlamaIndex `VectorStore` implementation directly:

```python
from agno.vectordb.llamaindex import LlamaIndexVectorStore
from llama_index.vector_stores.faiss import FaissVectorStore

vdb = LlamaIndexVectorStore(vector_store=FaissVectorStore(...))
```

#### LangChain VectorStore
**Module:** `agno.vectordb.langchaindb`
Use any LangChain `VectorStore` implementation directly:

```python
from agno.vectordb.langchaindb import LangChainVectorStore
from langchain_community.vectorstores import FAISS

vdb = LangChainVectorStore(vectorstore=FAISS(...))
```

#### LightRAG
**Module:** `agno.vectordb.lightrag`
Graph + vector hybrid retrieval:

```python
from agno.vectordb.lightrag import LightRag

vdb = LightRag(working_dir="./lightrag_data")
```

---

## Embedders

Vector DBs work with **embedder providers** to convert text to vectors:

| Embedder | Import |
|----------|--------|
| OpenAI | `agno.embedder.openai.OpenAIEmbedder` |
| Cohere | `agno.embedder.cohere.CohereEmbedder` |
| Google | `agno.embedder.google.GeminiEmbedder` |
| Mistral | `agno.embedder.mistral.MistralEmbedder` |
| Ollama | `agno.embedder.ollama.OllamaEmbedder` |
| HuggingFace | `agno.embedder.huggingface.HuggingfaceCustomEmbedder` |
| Sentence Transformers | `agno.embedder.sentence_transformer.SentenceTransformerEmbedder` |
| Jina | `agno.embedder.jina.JinaEmbedder` |
| VoyageAI | `agno.embedder.voyageai.VoyageAIEmbedder` |
| AWS Bedrock | `agno.embedder.aws_bedrock.AwsBedrockEmbedder` |
| Azure OpenAI | `agno.embedder.azure_openai.AzureOpenAIEmbedder` |
| Together | `agno.embedder.together.TogetherEmbedder` |
| Fireworks | `agno.embedder.fireworks.FireworksEmbedder` |

```python
from agno.embedder.openai import OpenAIEmbedder
from agno.vectordb.pgvector import PgVector

vdb = PgVector(
    table_name="knowledge",
    db_url="postgresql+psycopg://...",
    embedder=OpenAIEmbedder(
        id="text-embedding-3-small",
        dimensions=1536,
    ),
)
```

---

## Distance metrics

```python
from agno.vectordb.distance import Distance

# Available for most backends
Distance.cosine    # Normalised dot product — default for most use cases
Distance.l2        # Euclidean distance
Distance.max_inner_product  # Raw dot product — use when vectors are normalised
```

---

## Search types

```python
from agno.vectordb.search import SearchType

SearchType.vector   # Pure semantic similarity
SearchType.keyword  # BM25 / full-text (where supported)
SearchType.hybrid   # Combined semantic + keyword (best recall)
```

---

## Namespace / table isolation

Multiple agents or knowledge bases can share one vector DB instance using different table names or collection names:

```python
product_kb  = PgVector(table_name="product_knowledge", db_url=DB_URL)
support_kb  = PgVector(table_name="support_knowledge", db_url=DB_URL)
internal_kb = PgVector(table_name="internal_docs",    db_url=DB_URL)
```

---

## Selection guide

| Need | Recommended backend |
|------|---------------------|
| Already on PostgreSQL | `pgvector` |
| Fully managed cloud, simple ops | Pinecone or Qdrant Cloud |
| Development / prototyping | Chroma (embedded) or LanceDB |
| Massive scale (billions of vectors) | Milvus |
| Need hybrid search out of the box | Weaviate or pgvector (`hybrid` mode) |
| Already on MongoDB Atlas | MongoDB |
| Serverless / edge | Upstash |
| Need graph + vector | LightRAG |
| Zero-infra, file-based | LanceDB |
