# Configuring Conversation History

By default, the `Memory` instance includes the last 10 messages from the current memory thread in each new request. You can customize this by configuring the `lastMessages` option:

```typescript
import { Agent } from "@mastra/core/agent";
import { Memory } from "@mastra/memory";
import { openai } from "@ai-sdk/openai";
import { LibSQLStore } from "@mastra/libsql";

// Create a memory instance with custom conversation history settings
const memory = new Memory({
  storage: new LibSQLStore({
    url: "file:../../memory.db",
  }),
  options: {
    lastMessages: 20, // Include the last 20 messages in the context instead of the default 10
  },
});

// Create an agent with the configured memory
export const memoryAgent = new Agent({
  name: "MemoryAgent",
  instructions: `
    You are a helpful assistant with memory capabilities.
    You can remember previous conversations and user preferences.
    When a user shares information about themselves, acknowledge it and remember it for future reference.
    If asked about something mentioned earlier in the conversation, recall it accurately.
  `,
  model: openai("gpt-4o"),
  memory: memory,
});
```

The `lastMessages` option controls how many of the most recent messages are included in the agent's context window. This is important because language models have a limited context window size, and including too many messages can push out other important information.

You'll want to balance between having enough context for the agent to understand the conversation and not overwhelming the context window with too much history.
