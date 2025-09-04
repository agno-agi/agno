# Building Conditional Workflow

Now you'll create a workflow that uses conditional branching to route content through two different processing paths.

## Creating the Conditional Workflow

Add this workflow to your file:

```typescript
export const conditionalWorkflow = createWorkflow({
  id: "conditional-workflow",
  description: "Content processing with conditional branching",
  inputSchema: z.object({
    content: z.string(),
    type: z.enum(["article", "blog", "social"]).default("article"),
  }),
  outputSchema: z.object({
    processedContent: z.string(),
    processingType: z.string(),
    recommendations: z.array(z.string()),
  }),
})
  .then(assessContentStep)
  .branch([
    // Branch 1: Short and simple content
    [
      async ({ inputData }) =>
        inputData.category === "short" && inputData.complexity === "simple",
      quickProcessingStep,
    ],
    // Branch 2: Everything else
    [
      async ({ inputData }) =>
        !(inputData.category === "short" && inputData.complexity === "simple"),
      generalProcessingStep,
    ],
  ])
  .commit();
```

## Understanding the Conditions

1. **Short + Simple**: Quick processing with minimal recommendations
2. **Everything Else**: General processing with more suggestions

## Multiple Conditions

You can combine conditions using logical operators:

- **`&&`**: AND - both conditions must be true
- **`||`**: OR - either condition can be true
- **`!`**: NOT - condition must be false

## Condition Evaluation

- Conditions are checked in order
- Multiple conditions can be true (steps run in parallel)
- If no conditions match, the branch is skipped

Next, you'll test this conditional workflow with different types of content!
