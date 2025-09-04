# Registering with Mastra

Now you'll register your workflow with the main Mastra instance so you can use it alongside agents and tools.

## Updating Your Mastra Configuration

Open your `src/mastra/index.ts` file and add your workflow:

```typescript
// Import your workflow
import { contentWorkflow } from "./workflows/content-workflow";

export const mastra = new Mastra({
  // Register your workflow here
  workflows: {
    contentWorkflow,
  },
  // ...Existing code
});
```

Note: You may already have workflows registered, in which case, this workflow should be added to the workflows object.

Your workflow is now registered with Mastra! Next, you'll learn how to use it in the playground.
