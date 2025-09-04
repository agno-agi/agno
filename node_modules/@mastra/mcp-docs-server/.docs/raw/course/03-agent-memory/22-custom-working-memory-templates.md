# Custom Working Memory Templates

Templates guide the agent on what information to track and update in working memory. While a default template is used if none is provided, you'll typically want to define a custom template tailored to your agent's specific use case.

Let's update our agent with a custom working memory template:

```typescript
import { Agent } from "@mastra/core/agent";
import { Memory } from "@mastra/memory";
import { openai } from "@ai-sdk/openai";

// Create a memory instance with a custom working memory template
const memory = new Memory({
  storage: new LibSQLStore({
    url: "file:../../memory.db", // relative path from the `.mastra/output` directory
  }), // Storage for message history
  vector: new LibSQLVector({
    connectionUrl: "file:../../vector.db", // relative path from the `.mastra/output` directory
  }), // Vector database for semantic search
  embedder: openai.embedding("text-embedding-3-small"), // Embedder for message embeddings
  options: {
    semanticRecall: {
      topK: 3,
      messageRange: {
        before: 2,
        after: 1,
      },
    },
    workingMemory: {
      enabled: true,
    },
    workingMemory: {
      enabled: true,
      template: `
# User Profile

## Personal Info

- Name:
- Location:
- Timezone:

## Preferences

- Communication Style: [e.g., Formal, Casual]
- Interests:
- Favorite Topics:

## Session State

- Current Topic:
- Open Questions:
  - [Question 1]
  - [Question 2]
`,
    },
  },
});

// Create an agent with the configured memory
export const memoryAgent = new Agent({
  name: "MemoryAgent",
  instructions: `
    You are a helpful assistant with advanced memory capabilities.
    You can remember previous conversations and user preferences.
    
    IMPORTANT: You have access to working memory to store persistent information about the user.
    When you learn something important about the user, update your working memory according to the template.
    
    Always refer to your working memory before asking for information the user has already provided.
    Use the information in your working memory to provide personalized responses.
    
    When the user shares personal information such as their name, location, or preferences,
    acknowledge it and update your working memory accordingly.
  `,
  model: openai("gpt-4o"),
  memory: memory,
});
```

The template is a Markdown document that defines the structure of the working memory. It includes sections for different types of information, such as personal info, preferences, and session state.

The template serves several important purposes:

1. It guides the agent on what information to track and how to organize it
2. It provides a consistent structure for the working memory across conversations
3. It makes it easier for the agent to find and update specific pieces of information

You should design your template based on the specific needs of your agent and the type of information it needs to remember about users or tasks.
