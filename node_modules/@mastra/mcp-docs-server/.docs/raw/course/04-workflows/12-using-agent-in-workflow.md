# Using Agent in Workflow

Now you'll create a workflow step that uses your AI agent to provide intelligent content analysis.

In each step, in the execute function, you have access to the `mastra` class which provides you the ability to access Agents, Tools, and even other Workflows. In this case, we use the `mastra` class to get our agent and call that agent's `generate()` function.

## Creating an AI Analysis Step

Add this step to your workflow file:

```typescript
const aiAnalysisStep = createStep({
  id: "ai-analysis",
  description: "AI-powered content analysis",
  inputSchema: z.object({
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
  execute: async ({ inputData, mastra }) => {
    const { content, type, wordCount, metadata, summary } = inputData;

    // Create prompt for the AI agent
    const prompt = `
Analyze this ${type} content:

Content: "${content}"
Word count: ${wordCount}
Reading time: ${metadata.readingTime} minutes
Difficulty: ${metadata.difficulty}

Please provide:
1. A quality score from 1-10
2. Brief feedback on strengths and areas for improvement

Format as JSON: {"score": number, "feedback": "your feedback here"}
    `;

    // Get the contentAgent from the mastra instance.
    const contentAgent = mastra.getAgent("contentAgent");
    const { text } = await contentAgent.generate([
      { role: "user", content: prompt },
    ]);

    // Parse AI response (with fallback)
    let aiAnalysis;
    try {
      aiAnalysis = JSON.parse(text);
    } catch {
      aiAnalysis = {
        score: 7,
        feedback: "AI analysis completed. " + text,
      };
    }

    console.log(`🤖 AI Score: ${aiAnalysis.score}/10`);

    return {
      content,
      type,
      wordCount,
      metadata,
      summary,
      aiAnalysis,
    };
  },
});
```

Your agent-powered step is ready! Next, you'll add it to your workflow for complete AI-enhanced content processing.
