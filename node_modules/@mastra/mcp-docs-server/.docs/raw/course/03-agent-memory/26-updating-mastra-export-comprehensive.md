# Updating Your Mastra Export

Make sure to update your `src/mastra/index.ts` file to include your new comprehensive memory agent:

```typescript
import { Mastra } from "@mastra/core";
import { memoryMasterAgent } from "./agents/memory-agent";

export const mastra: Mastra = new Mastra({
  agents: {
    memoryMasterAgent,
  },
});
```

This step is essential for making your comprehensive memory agent available in the Mastra playground. The `mastra` export is the main entry point for your Mastra application, and it needs to include all the agents you want to use.

By adding your `memoryMasterAgent` to the `agents` object in the Mastra configuration, you're registering it with the Mastra system, making it available for use in the playground and other parts of your application.

If you have multiple agents, you can include them all in the `agents` object:

```typescript
export const mastra: Mastra = new Mastra({
  agents: {
    memoryMasterAgent,
    learningAssistantAgent,
    // Other agents...
  },
});
```

This allows you to switch between different agents in the playground, each with its own specialized memory configuration and capabilities.
