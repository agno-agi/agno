# Updating the Workflow

Now you'll update your workflow to include all three steps: validate, enhance, and summarize.

## Updating the Workflow Definition

Replace your existing workflow with this updated version:

```typescript
export const contentWorkflow = createWorkflow({
  id: "content-processing-workflow",
  description: "Validates, enhances, and summarizes content",
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
  }),
})
  .then(validateContentStep)
  .then(enhanceContentStep)
  .then(generateSummaryStep)
  .commit();
```

## What Changed

- **Description**: Updated to reflect the new functionality
- **Output Schema**: Now includes the `summary` field
- **Steps**: Added the third step to the chain

## Testing the Updated Workflow

You can now test this workflow in the playground to validate it works as expected.

## The Complete Flow

Your workflow now:

1. **Validates** content and counts words
2. **Enhances** with metadata like reading time and difficulty
3. **Summarizes** the content for quick understanding

Each step builds on the previous one, creating a comprehensive content processing pipeline!

Next, you'll learn about using workflows with agents.
