# Storage Configuration

Conversation history relies on a storage adapter to persist messages. By default, Mastra uses a LibSQL store that saves messages to a local database. You can configure this or use other storage options:

```typescript
import { Memory } from "@mastra/memory";
import { LibSQLStore } from "@mastra/libsql";

const memory = new Memory({
  // Configure storage
  storage: new LibSQLStore({
    config: {
      url: "file:../../memory.db", // Local database. Relative to the output folder
    },
  }),
  options: {
    lastMessages: 20,
  },
});
```

Mastra supports several storage options, including:

- LibSQL (default, local SQLite)
- PostgreSQL
- Upstash (Redis)

The storage adapter is responsible for persisting memory data, including conversation history and working memory. This allows your agent to remember conversations even after your application restarts.

For development and testing, the default LibSQL store is usually sufficient. For production applications, you might want to use a more robust storage option like PostgreSQL or a cloud-based solution like Upstash.
