# Enhancing Memory Configuration

Finally, let's enhance our memory configuration to make our agent even more helpful:

```typescript
import { LibSQLStore, LibSQLVector } from "@mastra/libsql";

const memory = new Memory({
  storage: new LibSQLStore({
    url: "file:../../memory.db",
  }),
  vector: new LibSQLVector({
    connectionUrl: "file:../../memory.db",
  }),
  embedder: openai.embedding("text-embedding-3-small"),
  options: {
    // Keep last 20 messages in context
    lastMessages: 20,
    // Enable semantic search to find relevant past conversations
    semanticRecall: {
      topK: 3,
      messageRange: {
        before: 2,
        after: 1,
      },
    },
    // Enable working memory to remember user information
    workingMemory: {
      enabled: true,
      template: `
      <user>
         <first_name></first_name>
         <username></username>
         <preferences></preferences>
         <interests></interests>
         <conversation_style></conversation_style>
       </user>`,
    },
  },
});
```

And update the agent instructions to use this enhanced memory:

```typescript
export const personalAssistantAgent = new Agent({
  name: "Personal Assistant",
  instructions: `
    // ... existing instructions ...
    
    You have access to conversation memory and can remember details about users.
    When you learn something about a user, update their working memory using the appropriate tool.
    This includes:
    - Their interests
    - Their preferences
    - Their conversation style (formal, casual, etc.)
    - Any other relevant information that would help personalize the conversation

    Always maintain a helpful and professional tone.
    Use the stored information to provide more personalized responses.
  `,
  model: openai("gpt-4o"),
  tools: { ...mcpTools },
  memory,
});
```

This enhanced memory configuration gives your agent more sophisticated memory capabilities:

1. **Conversation History**: The `lastMessages` option keeps the last 20 messages in context, allowing your agent to reference recent conversations.

2. **Semantic Recall**: The `semanticRecall` option enables your agent to find relevant past conversations using semantic search, even if they happened a long time ago. For `semanticRecall` to work, you need to have a vector store and an embedder configured

3. **Working Memory**: The `workingMemory` option allows your agent to remember specific information about users, such as their preferences and interests, and use that information to provide more personalized responses.

By updating your agent's instructions to include information about these memory capabilities, you're helping it understand how to use them effectively to provide a better user experience.
