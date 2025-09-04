# Running Workflows Programmatically

Learn how to execute your workflows from code, which is essential for integrating them into applications.

## Creating a Workflow Runner

Create a new file to test programmatic execution:

```typescript
// src/run-workflow.ts
import { mastra } from "./mastra";

async function runContentWorkflow() {
  console.log("🚀 Running workflow programmatically...\n");

  try {
    // Get the workflow instance
    const workflow = mastra.getWorkflow("contentWorkflow");

    if (!workflow) {
      throw new Error("Workflow not found");
    }

    // Create a run instance
    const run = workflow.createRun();

    // Execute with test data
    const result = await run.start({
      inputData: {
        content:
          "Climate change is one of the most pressing challenges of our time, requiring immediate action from governments, businesses, and individuals worldwide.",
        type: "blog",
      },
    });

    if (result.status === "success") {
      console.log("✅ Success!");
      console.log(
        "📊 Reading time:",
        result.result.metadata.readingTime,
        "minutes",
      );
      console.log("🎯 Difficulty:", result.result.metadata.difficulty);
      console.log("📅 Processed at:", result.result.metadata.processedAt);
    }
  } catch (error) {
    console.error("❌ Error:", (error as Error).message);
  }
}

// Run the workflow
runContentWorkflow();
```

## Running the Code

Execute your workflow runner:

```bash
npx tsx src/run-workflow.ts
```

## Key Methods

- **`mastra.getWorkflow(id)`**: Gets a registered workflow by ID
- **`workflow.createRun()`**: Creates a new execution instance
- **`run.start(inputData)`**: Executes the workflow with provided data

## Return Value

The `start()` method returns:

- **`success`**: Boolean indicating if workflow completed successfully
- **`result`**: The final output from the workflow
- **`executionTime`**: How long the workflow took to run

Your workflow can now be run from anywhere in your application! Next, you'll learn about error handling.
