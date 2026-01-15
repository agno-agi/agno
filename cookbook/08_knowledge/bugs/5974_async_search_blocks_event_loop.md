# Bug Report: #5974 - async_search() Blocks Event Loop

## Summary

The `async_search()` methods in multiple VectorDB adapters block the event loop by calling synchronous `embedder.get_embedding()` or by directly calling synchronous `search()` methods. This blocks ALL concurrent users for 200-1200ms per embedding request.

## Status: CONFIRMED

## Impact: HIGH

Affects all concurrent users of `agent.arun()` with Knowledge base. Event loop blocking prevents any other async operations during embedding requests.

## Affected VectorDB Adapters

### Type 1: No Async Wrapper (Direct sync call)

| Adapter | Location | Code |
|---------|----------|------|
| **lancedb** | `lance_db.py:504` | `return self.search(...)` |
| **singlestore** | `singlestore.py:683` | `return self.search(...)` |
| **langchaindb** | `langchaindb.py:123` | `return self.search(...)` |
| **llamaindexdb** | `llamaindexdb.py:110` | `return self.search(...)` |
| **mongodb** | `mongodb.py:711` | `return self.search(...)` |

### Type 2: Async Client but Sync Embedding

| Adapter | Location | Code |
|---------|----------|------|
| **qdrant** | `qdrant.py:637` | `dense_embedding = self.embedder.get_embedding(query)` |
| **weaviate** | `weaviate.py:503,662` | `query_embedding = self.embedder.get_embedding(query)` |

### Correctly Implemented (for reference)

| Adapter | Location | Code |
|---------|----------|------|
| **pgvector** | `pgvector.py:759` | `await asyncio.to_thread(self.search, ...)` |
| **chromadb** | `chromadb.py:1066` | `await asyncio.to_thread(self.search, ...)` |
| **cassandra** | `cassandra.py:221` | `await asyncio.to_thread(self.search, ...)` |
| **redis** | `redisdb.py:408` | `await asyncio.to_thread(self.search, ...)` |
| **pinecone** | `pineconedb.py:535` | `await asyncio.to_thread(self.search, ...)` |

## Reproduction

```python
"""
uv add agno openai lancedb pandas pyleak
Need to set OPENAI_API_KEY environment variable
"""
import asyncio
import tempfile

from agno.agent import Agent
from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb
from pyleak import EventLoopBlockError, no_event_loop_blocking


async def main():
    with tempfile.TemporaryDirectory() as tmp_dir:
        vector_db = LanceDb(
            uri=tmp_dir,
            table_name="test",
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        )
        vector_db.create()
        vector_db.insert("hash", [Document(content="The name of the cat is Tom.")])

        agent = Agent(
            model=OpenAIChat(id="gpt-4o-mini"),
            knowledge=Knowledge(vector_db=vector_db),
            add_knowledge_to_context=True,
        )

        async with no_event_loop_blocking(action="raise"):
            await agent.arun("What is the name of the cat?")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except EventLoopBlockError as e:
        print(f"BLOCKED: {e}")
```

## Call Chain

```
agent.arun()
  → agno/agent/agent.py: aget_relevant_docs_from_knowledge()
  → agno/knowledge/knowledge.py:2452: async_search()
  → agno/vectordb/lancedb/lance_db.py:504: async_search()
      return self.search(...)  # ← calls sync!
  → agno/vectordb/lancedb/lance_db.py:509: vector_search()
      query_embedding = self.embedder.get_embedding(query)  # ← sync HTTP!
  → agno/knowledge/embedder/openai.py:78
      return self.client.embeddings.create(...)  # ← blocking!
```

## Proposed Fixes

### Fix 1: Wrap sync search in asyncio.to_thread (Quick Fix)

For Type 1 adapters (lancedb, singlestore, etc.):

```python
# BEFORE (buggy)
async def async_search(self, query, limit, filters):
    return self.search(query, limit, filters)

# AFTER (fixed)
async def async_search(self, query, limit, filters):
    return await asyncio.to_thread(self.search, query, limit, filters)
```

### Fix 2: Add async_get_embedding to Embedder (Proper Fix)

For Type 2 adapters (qdrant, weaviate), need to add async embedding:

```python
# In embedder base class
async def async_get_embedding(self, text: str) -> List[float]:
    """Async version using async HTTP client."""
    # Use aiohttp or async openai client
    pass

# In qdrant async search
async def _run_vector_search_async(self, query, limit, filters):
    dense_embedding = await self.embedder.async_get_embedding(query)  # ← Now async!
    call = await self.async_client.query_points(...)
```

### Fix 3: Use asyncio.to_thread for embedding (Middle Ground)

```python
async def _run_vector_search_async(self, query, limit, filters):
    dense_embedding = await asyncio.to_thread(self.embedder.get_embedding, query)
    call = await self.async_client.query_points(...)
```

## Files to Modify

### Quick Fix (Type 1 - add asyncio.to_thread wrapper)
- `libs/agno/agno/vectordb/lancedb/lance_db.py` - Line 504
- `libs/agno/agno/vectordb/singlestore/singlestore.py` - Line 683
- `libs/agno/agno/vectordb/langchaindb/langchaindb.py` - Line 123
- `libs/agno/agno/vectordb/llamaindex/llamaindexdb.py` - Line 110
- `libs/agno/agno/vectordb/mongodb/mongodb.py` - Line 711

### Proper Fix (Type 2 - wrap embedding call)
- `libs/agno/agno/vectordb/qdrant/qdrant.py` - Lines 637, 686
- `libs/agno/agno/vectordb/weaviate/weaviate.py` - Lines 503, 662

## References

- GitHub Issue: https://github.com/agno-agi/agno/issues/5974
- Reporter: @deepankarm
- Tool for detection: [pyleak](https://github.com/deepankarm/pyleak)
