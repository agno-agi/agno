# Understanding Steps

Steps are the building blocks of workflows. Each step is a self-contained unit that takes some input, processes it, and produces an output.

## What is a Step?

A step has three main parts:

1. **Input Schema** - what data it expects to receive
2. **Output Schema** - what data it will produce
3. **Execute Function** - the logic that transforms input to output

## Step Structure

Every step follows this pattern:

```typescript
const myStep = createStep({
  id: "unique-step-name",
  description: "What this step does",
  inputSchema: z.object({
    // Define expected input structure
  }),
  outputSchema: z.object({
    // Define output structure
  }),
  execute: async ({ inputData }) => {
    // Your logic here
    return {
      // Return data matching output schema
    };
  },
});
```

## Why Use Schemas?

Schemas provide several benefits:

- **Type Safety**: TypeScript knows exactly what data flows between steps
- **Runtime Validation**: Invalid data is caught immediately with helpful error messages
- **Documentation**: Schemas serve as living documentation of your workflow
- **Debugging**: Clear contracts make it easy to identify issues

## Key Benefits

- **Reusable**: Steps can be used in multiple workflows
- **Testable**: Each step can be tested in isolation
- **Composable**: Steps can be combined in different ways
- **Reliable**: Schemas catch data flow issues early
- **Traceable**: Every step is traced so you can see the flow of data

Next, you'll create your first step!
