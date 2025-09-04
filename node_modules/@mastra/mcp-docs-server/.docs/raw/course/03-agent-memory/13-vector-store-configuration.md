# Vector Store Configuration

In addition to the memory storage adapters, Mastra also provides vector store adapters useful for storing and retrieving vector embeddings. One of these is the `LibSQLVector` adapter, which provides a simple interface for storing and retrieving vector embeddings in a LibSQL vector database.

```typescript
import { Memory } from "@mastra/memory";
import { LibSQLStore, LibSQLVector } from "@mastra/libsql";

const memory = new Memory({
  storage: new LibSQLStore({
    url: "file:../../memory.db", // relative path from the `.mastra/output` directory
  }),
  vector: new LibSQLVector({
    connectionUrl: "file:../../vector.db", // relative path from the `.mastra/output` directory
  }),
});
```

Mastra supports several vector store options, including:

- LibSQL
- Chroma
- Pinecone
- Qdrant
- Postgres (with pgvector)

The vector store is responsible for storing and retrieving the vector embeddings used for semantic search.
