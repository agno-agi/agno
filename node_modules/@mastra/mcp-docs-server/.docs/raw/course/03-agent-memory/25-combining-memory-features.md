# Building a Complete Memory-Enhanced Agent

In this final step, we'll bring together all the memory features we've explored to create a complete memory-enhanced agent. We'll also create a practical example that demonstrates how these features work together.

## Combining All Memory Features

Let's create a comprehensive agent that utilizes conversation history, semantic recall, and working memory:

```typescript
// src/mastra/agents/memory-agent.ts
import { Agent } from "@mastra/core/agent";
import { Memory } from "@mastra/memory";
import { openai } from "@ai-sdk/openai";
import { LibSQLStore, LibSQLVector } from "@mastra/libsql";

// Create a comprehensive memory configuration
const memory = new Memory({
  storage: new LibSQLStore({
    url: "file:../../memory.db", // relative path from the `.mastra/output` directory
  }),
  vector: new LibSQLVector({
    connectionUrl: "file:../../vector.db", // relative path from the `.mastra/output` directory
  }),
  embedder: openai.embedding("text-embedding-3-small"),
  options: {
    // Conversation history configuration
    lastMessages: 20, // Include the last 20 messages in the context

    // Semantic recall configuration
    semanticRecall: {
      topK: 3, // Retrieve 3 most similar messages
      messageRange: {
        before: 2, // Include 2 messages before each match
        after: 1, // Include 1 message after each match
      },
    },

    // Working memory configuration
    workingMemory: {
      enabled: true,
      template: `
# User Profile

## Personal Info
- Name:
- Location:
- Timezone:
- Occupation:

## Preferences
- Communication Style:
- Topics of Interest:
- Learning Goals:

## Project Information
- Current Projects:
  - [Project 1]:
    - Deadline:
    - Status:
  - [Project 2]:
    - Deadline:
    - Status:

## Session State
- Current Topic:
- Open Questions:
- Action Items:
`,
    },
  },
});
```

This comprehensive memory configuration combines all three memory features we've explored:

1. **Conversation history** with the `lastMessages` option
2. **Semantic recall** with the `semanticRecall` option
3. **Working memory** with the `workingMemory` option

Each feature serves a different purpose in enhancing your agent's memory capabilities, and together they create a powerful memory system that can maintain context across conversations and provide personalized responses.
