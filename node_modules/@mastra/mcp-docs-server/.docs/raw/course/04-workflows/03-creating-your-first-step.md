# Creating Your First Step

Let's create your first workflow step! We'll build a step that validates text content.

## Setting Up

First, create a new file for your workflow in the `src/mastra/workflows` directory. Let's name this file `content-workflow.ts`

## Creating a Validation Step

Add this code to your workflow file:

```typescript
import { createStep } from "@mastra/core/workflows";
import { z } from "zod";

const validateContentStep = createStep({
  id: "validate-content",
  description: "Validates incoming text content",
  inputSchema: z.object({
    content: z.string().min(1, "Content cannot be empty"),
    type: z.enum(["article", "blog", "social"]).default("article"),
  }),
  outputSchema: z.object({
    content: z.string(),
    type: z.string(),
    wordCount: z.number(),
    isValid: z.boolean(),
  }),
  execute: async ({ inputData }) => {
    const { content, type } = inputData;

    const wordCount = content.trim().split(/\s+/).length;
    const isValid = wordCount >= 5; // Minimum 5 words

    if (!isValid) {
      throw new Error(`Content too short: ${wordCount} words`);
    }

    return {
      content: content.trim(),
      type,
      wordCount,
      isValid,
    };
  },
});
```

## Understanding the Code

- **ID**: Unique identifier for this step
- **Input Schema**: Expects `content` (string) and optional `type`
- **Output Schema**: Returns content, type, word count, and validation status
- **Execute**: Contains the validation logic

Your first step is ready! Next, you'll test it to make sure it works correctly.
