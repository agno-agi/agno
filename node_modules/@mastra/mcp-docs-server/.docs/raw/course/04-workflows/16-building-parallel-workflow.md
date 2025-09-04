# Building Parallel Workflow

Now you'll create a workflow that runs your analysis steps in parallel for maximum performance.

## Creating the Parallel Workflow

Add this workflow to your file:

```typescript
export const parallelAnalysisWorkflow = createWorkflow({
  id: "parallel-analysis-workflow",
  description: "Run multiple content analyses in parallel",
  inputSchema: z.object({
    content: z.string(),
    type: z.enum(["article", "blog", "social"]).default("article"),
  }),
  outputSchema: z.object({
    results: z.object({
      seo: z.object({
        seoScore: z.number(),
        keywords: z.array(z.string()),
      }),
      readability: z.object({
        readabilityScore: z.number(),
        gradeLevel: z.string(),
      }),
      sentiment: z.object({
        sentiment: z.enum(["positive", "neutral", "negative"]),
        confidence: z.number(),
      }),
    }),
  }),
})
  .parallel([seoAnalysisStep, readabilityStep, sentimentStep])
  .then(
    createStep({
      id: "combine-results",
      description: "Combines parallel analysis results",
      inputSchema: z.object({
        "seo-analysis": z.object({
          seoScore: z.number(),
          keywords: z.array(z.string()),
        }),
        "readability-analysis": z.object({
          readabilityScore: z.number(),
          gradeLevel: z.string(),
        }),
        "sentiment-analysis": z.object({
          sentiment: z.enum(["positive", "neutral", "negative"]),
          confidence: z.number(),
        }),
      }),
      outputSchema: z.object({
        results: z.object({
          seo: z.object({
            seoScore: z.number(),
            keywords: z.array(z.string()),
          }),
          readability: z.object({
            readabilityScore: z.number(),
            gradeLevel: z.string(),
          }),
          sentiment: z.object({
            sentiment: z.enum(["positive", "neutral", "negative"]),
            confidence: z.number(),
          }),
        }),
      }),
      execute: async ({ inputData }) => {
        console.log("🔄 Combining parallel results...");

        return {
          results: {
            seo: inputData["seo-analysis"],
            readability: inputData["readability-analysis"],
            sentiment: inputData["sentiment-analysis"],
          },
        };
      },
    }),
  )
  .commit();
```

## Understanding Parallel Data Flow

When steps run in parallel:

1. Each step receives the same input data
2. Steps execute simultaneously
3. Results are collected into an object with step IDs as keys
4. The next step receives all parallel results

## Key Points

- **`.parallel([step1, step2, step3])`**: Runs all steps simultaneously
- **Result object keys**: Use the step IDs (e.g., "seo-analysis")
- **Combine step**: Processes all parallel results together

Next, you'll test this parallel workflow and see the performance improvement!
