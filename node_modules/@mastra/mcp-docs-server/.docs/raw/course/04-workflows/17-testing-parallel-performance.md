# Testing Parallel Workflow

Let's test your parallel workflow.

## Registering the New Workflow

Update your Mastra configuration to include your new workflow workflows:

```typescript
// In src/mastra/index.ts
import {
  contentWorkflow,
  aiContentWorkflow,
  parallelAnalysisWorkflow,
} from "./workflows/content-workflow";

export const mastra = new Mastra({
  workflows: {
    contentWorkflow,
    aiContentWorkflow,
    parallelAnalysisWorkflow, // Add the parallel workflow
  },
  // ... rest of configuration
});
```

## Testing the Parallel Workflow

You can now test this new workflow in the Playground. You will notice that it processes the three analysis steps in parallel speeding up execution time.

## When to Use Parallel Execution

Use parallel execution when:

- Steps don't depend on each other's outputs
- Steps involve I/O operations (API calls, database queries)
- You want to maximize performance
- Steps process the same input data

Register your parallel workflow with Mastra to use it in the playground! Next, you'll learn about conditional branching.
