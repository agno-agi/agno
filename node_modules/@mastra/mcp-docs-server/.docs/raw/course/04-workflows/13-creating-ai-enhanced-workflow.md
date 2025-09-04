# Creating AI-Enhanced Workflow

Now you'll create a new workflow that includes agent analysis alongside your existing content processing steps.

## Creating the Enhanced Workflow

Add this new workflow to your file:

```typescript
export const aiContentWorkflow = createWorkflow({
  id: "ai-content-workflow",
  description: "AI-enhanced content processing with analysis",
  inputSchema: z.object({
    content: z.string(),
    type: z.enum(["article", "blog", "social"]).default("article"),
  }),
  outputSchema: z.object({
    content: z.string(),
    type: z.string(),
    wordCount: z.number(),
    metadata: z.object({
      readingTime: z.number(),
      difficulty: z.enum(["easy", "medium", "hard"]),
      processedAt: z.string(),
    }),
    summary: z.string(),
    aiAnalysis: z.object({
      score: z.number(),
      feedback: z.string(),
    }),
  }),
})
  .then(validateContentStep)
  .then(enhanceContentStep)
  .then(generateSummaryStep)
  .then(aiAnalysisStep)
  .commit();
```

## Registering the New Workflow

Update your Mastra configuration to include both workflows and ensure the contentAgent has been added.

```typescript
// In src/mastra/index.ts
import {
  contentWorkflow,
  aiContentWorkflow,
} from "./workflows/content-workflow";
import { contentAgent } from "./agents/content-agent";

export const mastra = new Mastra({
  workflows: {
    contentWorkflow,
    aiContentWorkflow, // Add the AI-enhanced version
  },
  agents: { contentAgent },
  // ... rest of configuration
});
```

## Testing the Agent-Enhanced Workflow

You can now access this new Workflow inside the Mastra playground. Select this new `ai-content-workflow` workflow from the Workflows tab and run a test to validate it works as expected.

## The Complete AI Pipeline

Your AI-enhanced workflow now:

1. **Validates** content and counts words
2. **Enhances** with metadata
3. **Summarizes** the content
4. **Analyzes** with AI for quality scoring and feedback

This creates a comprehensive, AI-powered content processing system! Next, you'll learn about parallel execution.
