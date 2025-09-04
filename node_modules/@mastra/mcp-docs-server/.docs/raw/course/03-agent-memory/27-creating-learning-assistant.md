# Creating a Practical Example: Personal Learning Assistant

Let's create a practical example of a memory-enhanced agent: a Personal Learning Assistant that helps users learn new skills and tracks their progress.

```typescript
// src/mastra/agents/learning-assistant.ts
import { Agent } from "@mastra/core/agent";
import { Memory } from "@mastra/memory";
import { openai } from "@ai-sdk/openai";
import { LibSQLStore, LibSQLVector } from "@mastra/libsql";

// Create a specialized memory configuration for the learning assistant
const learningMemory = new Memory({
  storage: new LibSQLStore({
    url: "file:../../memory.db", // relative path from the `.mastra/output` directory
  }),
  vector: new LibSQLVector({
    connectionUrl: "file:../../vector.db", // relative path from the `.mastra/output` directory
  }),
  embedder: openai.embedding("text-embedding-3-small"),
  options: {
    lastMessages: 20,
    semanticRecall: {
      topK: 3,
      messageRange: {
        before: 2,
        after: 1,
      },
    },
    workingMemory: {
      enabled: true,
      template: `
# Learner Profile

## Personal Info
- Name:
- Learning Style: [Visual, Auditory, Reading/Writing, Kinesthetic]

## Learning Journey
- Current Topics:
  - [Topic 1]:
    - Skill Level: [Beginner, Intermediate, Advanced]
    - Started: [Date]
    - Goals:
    - Resources:
    - Progress Notes:
  - [Topic 2]:
    - Skill Level: [Beginner, Intermediate, Advanced]
    - Started: [Date]
    - Goals:
    - Resources:
    - Progress Notes:

## Session State
- Current Focus:
- Questions to Revisit:
- Recommended Next Steps:
`,
    },
  },
});

// Create the learning assistant agent
export const learningAssistantAgent = new Agent({
  name: "Learning Assistant",
  instructions: `
    You are a personal learning assistant that helps users learn new skills and tracks their progress.
    
    ## Your Capabilities
    
    - You help users set learning goals and track their progress
    - You provide explanations and resources tailored to their skill level
    - You remember what topics they're learning and their progress in each
    - You adapt your teaching style to match their learning preferences
    
    ## Guidelines for Using Memory
    
    - When the user shares information about their learning style or preferences,
      update your working memory.
    
    - When the user asks about a topic they've mentioned before, use your semantic
      recall to provide continuity in your teaching.
    
    - When explaining concepts, check your working memory to understand their
      current skill level and provide an explanation at the appropriate depth.
    
    Always be encouraging and supportive. Focus on building the user's confidence
    and celebrating their progress.
  `,
  model: openai("gpt-4o"),
  memory: learningMemory,
});

// Don't forget to export this agent in your src/mastra/index.ts file
```

This example demonstrates how to create a specialized agent with a memory configuration tailored to a specific use case. The Learning Assistant uses:

1. A custom working memory template designed to track learning progress
2. Specialized instructions that guide the agent on how to use memory for educational purposes
3. All three memory features (conversation history, semantic recall, and working memory) working together

This type of specialized agent can provide a much more personalized and effective learning experience compared to a generic chatbot without memory capabilities.
