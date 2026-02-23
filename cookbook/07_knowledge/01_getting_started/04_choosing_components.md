# Choosing Components

A quick guide to selecting the right vector database, embedder, and chunking strategy.

## Vector Database

| Scenario | Choice | Install |
|----------|--------|---------|
| Production | Qdrant | `./cookbook/scripts/run_qdrant.sh` |
| Quick prototype | LanceDB | `pip install lancedb tantivy` |
| In-memory testing | ChromaDB | `pip install chromadb` |
| Managed cloud | Pinecone or PgVector | See provider docs |

**Start with Qdrant** unless you have a specific reason not to. It handles vector search, keyword search, hybrid search, and reranking out of the box.

## Embedder

| Scenario | Choice |
|----------|--------|
| General purpose | `OpenAIEmbedder(id="text-embedding-3-small")` |
| High quality | `OpenAIEmbedder(id="text-embedding-3-large")` |
| Multilingual | `SentenceTransformerEmbedder(id="paraphrase-multilingual-MiniLM-L12-v2")` |
| Local/private | `OllamaEmbedder(id="nomic-embed-text")` |

**Start with OpenAI text-embedding-3-small.** It's fast, cheap, and works well for most content.

## Chunking Strategy

| Content Type | Strategy |
|-------------|----------|
| General text | `RecursiveChunking(chunk_size=500)` |
| Source code | `CodeChunking()` |
| Markdown docs | `MarkdownChunking()` |
| Mixed-topic docs | `SemanticChunking()` |
| Simple/fast | `FixedSizeChunking(chunk_size=500)` |

**Start with Recursive Chunking.** It respects natural text boundaries and works for most content types.

## Search Type

| Need | Choice |
|------|--------|
| Best results | `SearchType.hybrid` (vector + keyword) |
| Fast, semantic | `SearchType.vector` |
| Exact matching | `SearchType.keyword` |

**Start with Hybrid Search.** It combines semantic understanding with exact matching.

## Full Example

```python
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.qdrant import Qdrant, SearchType

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="my_knowledge",
        url="http://localhost:6333",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)
```

For detailed comparisons, see the [reference guides](../reference/).
