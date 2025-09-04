# Creating a Basic Memory Agent

Now, let's create a simple agent with memory capabilities. We'll start with the basics and add more advanced features in the following steps.

Create or update your `src/mastra/agents/index.ts` file:

```typescript
import { Agent } from "@mastra/core/agent";
import { Memory } from "@mastra/memory";
import { LibSQLStore } from "@mastra/libsql";
import { openai } from "@ai-sdk/openai";

// Create a basic memory instance
const memory = new Memory({
  storage: new LibSQLStore({
    url: "file:../../memory.db", // relative path from the `.mastra/output` directory
  }),
});

// Create an agent with memory
export const memoryAgent = new Agent({
  name: "MemoryAgent",
  instructions: `
    You are a helpful assistant with memory capabilities.
    You can remember previous conversations and user preferences.
    When a user shares information about themselves, acknowledge it and remember it for future reference.
    If asked about something mentioned earlier in the conversation, recall it accurately.
  `,
  model: openai("gpt-4o"), // You can use "gpt-3.5-turbo" if you prefer
  memory: memory,
});
```

In this example, we're creating a basic `Memory` instance without any special configuration. This default configuration will still provide your agent with the ability to remember previous messages in the conversation.

The key part is adding the `memory` property to your agent configuration, which connects the memory instance to your agent.
