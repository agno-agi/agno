# Configuring Semantic Recall

Let's update our agent with custom semantic recall settings:

```typescript
import { Agent } from "@mastra/core/agent";
import { Memory } from "@mastra/memory";
import { openai } from "@ai-sdk/openai";
import { LibSQLStore, LibSQLVector } from "@mastra/libsql";

// Create a memory instance with semantic recall configuration
const memory = new Memory({
  storage: new LibSQLStore({
    url: "file:../../memory.db", // relative path from the `.mastra/output` directory
  }), // Storage for message history
  vector: new LibSQLVector({
    connectionUrl: "file:../../vector.db", // relative path from the `.mastra/output` directory
  }), // Vector database for semantic search
  embedder: openai.embedding("text-embedding-3-small"), // Embedder for message embeddings
  options: {
    lastMessages: 20, // Include the last 20 messages in the context
    semanticRecall: true, // Enable semantic recall with default settings
  },
});

// Create an agent with the configured memory
export const memoryAgent = new Agent({
  name: "MemoryAgent",
  instructions: `
    You are a helpful assistant with advanced memory capabilities.
    You can remember previous conversations and user preferences.
    When a user shares information about themselves, acknowledge it and remember it for future reference.
    If asked about something mentioned earlier in the conversation, recall it accurately.
    You can also recall relevant information from older conversations when appropriate.
  `,
  model: openai("gpt-4o"),
  memory: memory,
});
```

For semantic recall to work, you need to have a **vector store** configured. You also need to have an **embedder** configured. You may use any `@ai-sdk`-compatible embedding model for this. In this example, we're using OpenAI's `text-embedding-3-small` model.
