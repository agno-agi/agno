# Nested Workflows (Legacy)

Mastra allows you to use workflows as steps within other workflows, enabling you to create modular and reusable workflow components. This feature helps in organizing complex workflows into smaller, manageable pieces and promotes code reuse.

It is also visually easier to understand the flow of a workflow when you can see the nested workflows as steps in the parent workflow.

## Basic Usage

You can use a workflow as a step directly in another workflow using the `step()` method:

```typescript
import { LegacyStep, LegacyWorkflow } from "@mastra/core/workflows/legacy";

// Create a nested workflow
const nestedWorkflow = new LegacyWorkflow({ name: "nested-workflow" })
  .step(stepA)
  .then(stepB)
  .commit();

// Use the nested workflow in a parent workflow
const parentWorkflow = new LegacyWorkflow({ name: "parent-workflow" })
  .step(nestedWorkflow, {
    variables: {
      city: {
        step: "trigger",
        path: "myTriggerInput",
      },
    },
  })
  .then(stepC)
  .commit();
```

When a workflow is used as a step:

- It is automatically converted to a step using the workflow's name as the step ID
- The workflow's results are available in the parent workflow's context
- The nested workflow's steps are executed in their defined order

## Accessing Results

Results from a nested workflow are available in the parent workflow's context under the nested workflow's name. The results include all step outputs from the nested workflow:

```typescript
const { results } = await parentWorkflow.start();
// Access nested workflow results
const nestedWorkflowResult = results["nested-workflow"];
if (nestedWorkflowResult.status === "success") {
  const nestedResults = nestedWorkflowResult.output.results;
}
```

## Control Flow with Nested Workflows

Nested workflows support all the control flow features available to regular steps:

### Parallel Execution

Multiple nested workflows can be executed in parallel:

```typescript
parentWorkflow
  .step(nestedWorkflowA)
  .step(nestedWorkflowB)
  .after([nestedWorkflowA, nestedWorkflowB])
  .step(finalStep);
```

Or using `step()` with an array of workflows:

```typescript
parentWorkflow.step([nestedWorkflowA, nestedWorkflowB]).then(finalStep);
```

In this case, `then()` will implicitly wait for all the workflows to finish before executing the final step.

### If-Else Branching

Nested workflows can be used in if-else branches using the new syntax that accepts both branches as arguments:

```typescript
// Create nested workflows for different paths
const workflowA = new LegacyWorkflow({ name: "workflow-a" })
  .step(stepA1)
  .then(stepA2)
  .commit();

const workflowB = new LegacyWorkflow({ name: "workflow-b" })
  .step(stepB1)
  .then(stepB2)
  .commit();

// Use the new if-else syntax with nested workflows
parentWorkflow
  .step(initialStep)
  .if(
    async ({ context }) => {
      // Your condition here
      return someCondition;
    },
    workflowA, // if branch
    workflowB, // else branch
  )
  .then(finalStep)
  .commit();
```

The new syntax is more concise and clearer when working with nested workflows. When the condition is:

- `true`: The first workflow (if branch) is executed
- `false`: The second workflow (else branch) is executed

The skipped workflow will have a status of `skipped` in the results:

The `.then(finalStep)` call following the if-else block will merge the if and else branches back into a single execution path.

### Looping

Nested workflows can use `.until()` and `.while()` loops same as any other step. One interesting new pattern is to pass a workflow directly as the loop-back argument to keep executing that nested workflow until something is true about its results:

```typescript
parentWorkflow
  .step(firstStep)
  .while(
    ({ context }) =>
      context.getStepResult("nested-workflow").output.results.someField ===
      "someValue",
    nestedWorkflow,
  )
  .step(finalStep)
  .commit();
```

## Watching Nested Workflows

You can watch the state changes of nested workflows using the `watch` method on the parent workflow. This is useful for monitoring the progress and state transitions of complex workflows:

```typescript
const parentWorkflow = new LegacyWorkflow({ name: "parent-workflow" })
  .step([nestedWorkflowA, nestedWorkflowB])
  .then(finalStep)
  .commit();

const run = parentWorkflow.createRun();
const unwatch = parentWorkflow.watch((state) => {
  console.log("Current state:", state.value);
  // Access nested workflow states in state.context
});

await run.start();
unwatch(); // Stop watching when done
```

## Suspending and Resuming

Nested workflows support suspension and resumption, allowing you to pause and continue workflow execution at specific points. You can suspend either the entire nested workflow or specific steps within it:

```typescript
// Define a step that may need to suspend
const suspendableStep = new LegacyStep({
  id: "other",
  description: "Step that may need to suspend",
  execute: async ({ context, suspend }) => {
    if (!wasSuspended) {
      wasSuspended = true;
      await suspend();
    }
    return { other: 26 };
  },
});

// Create a nested workflow with suspendable steps
const nestedWorkflow = new LegacyWorkflow({ name: "nested-workflow-a" })
  .step(startStep)
  .then(suspendableStep)
  .then(finalStep)
  .commit();

// Use in parent workflow
const parentWorkflow = new LegacyWorkflow({ name: "parent-workflow" })
  .step(beginStep)
  .then(nestedWorkflow)
  .then(lastStep)
  .commit();

// Start the workflow
const run = parentWorkflow.createRun();
const { runId, results } = await run.start({ triggerData: { startValue: 1 } });

// Check if a specific step in the nested workflow is suspended
if (results["nested-workflow-a"].output.results.other.status === "suspended") {
  // Resume the specific suspended step using dot notation
  const resumedResults = await run.resume({
    stepId: "nested-workflow-a.other",
    context: { startValue: 1 },
  });

  // The resumed results will contain the completed nested workflow
  expect(resumedResults.results["nested-workflow-a"].output.results).toEqual({
    start: { output: { newValue: 1 }, status: "success" },
    other: { output: { other: 26 }, status: "success" },
    final: { output: { finalValue: 27 }, status: "success" },
  });
}
```

When resuming a nested workflow:

- Use the nested workflow's name as the `stepId` when calling `resume()` to resume the entire workflow
- Use dot notation (`nested-workflow.step-name`) to resume a specific step within the nested workflow
- The nested workflow will continue from the suspended step with the provided context
- You can check the status of specific steps in the nested workflow's results using `results["nested-workflow"].output.results`

## Result Schemas and Mapping

Nested workflows can define their result schema and mapping, which helps in type safety and data transformation. This is particularly useful when you want to ensure the nested workflow's output matches a specific structure or when you need to transform the results before they're used in the parent workflow.

```typescript
// Create a nested workflow with result schema and mapping
const nestedWorkflow = new LegacyWorkflow({
  name: "nested-workflow",
  result: {
    schema: z.object({
      total: z.number(),
      items: z.array(
        z.object({
          id: z.string(),
          value: z.number(),
        }),
      ),
    }),
    mapping: {
      // Map values from step results using variables syntax
      total: { step: "step-a", path: "count" },
      items: { step: "step-b", path: "items" },
    },
  },
})
  .step(stepA)
  .then(stepB)
  .commit();

// Use in parent workflow with type-safe results
const parentWorkflow = new LegacyWorkflow({ name: "parent-workflow" })
  .step(nestedWorkflow)
  .then(async ({ context }) => {
    const result = context.getStepResult("nested-workflow");
    // TypeScript knows the structure of result
    console.log(result.total); // number
    console.log(result.items); // Array<{ id: string, value: number }>
    return { success: true };
  })
  .commit();
```

## Best Practices

1. **Modularity**: Use nested workflows to encapsulate related steps and create reusable workflow components.
2. **Naming**: Give nested workflows descriptive names as they will be used as step IDs in the parent workflow.
3. **Error Handling**: Nested workflows propagate their errors to the parent workflow, so handle errors appropriately.
4. **State Management**: Each nested workflow maintains its own state but can access the parent workflow's context.
5. **Suspension**: When using suspension in nested workflows, consider the entire workflow's state and handle resumption appropriately.

## Example

Here's a complete example showing various features of nested workflows:

```typescript
const workflowA = new LegacyWorkflow({
  name: "workflow-a",
  result: {
    schema: z.object({
      activities: z.string(),
    }),
    mapping: {
      activities: {
        step: planActivities,
        path: "activities",
      },
    },
  },
})
  .step(fetchWeather)
  .then(planActivities)
  .commit();

const workflowB = new LegacyWorkflow({
  name: "workflow-b",
  result: {
    schema: z.object({
      activities: z.string(),
    }),
    mapping: {
      activities: {
        step: planActivities,
        path: "activities",
      },
    },
  },
})
  .step(fetchWeather)
  .then(planActivities)
  .commit();

const weatherWorkflow = new LegacyWorkflow({
  name: "weather-workflow",
  triggerSchema: z.object({
    cityA: z.string().describe("The city to get the weather for"),
    cityB: z.string().describe("The city to get the weather for"),
  }),
  result: {
    schema: z.object({
      activitiesA: z.string(),
      activitiesB: z.string(),
    }),
    mapping: {
      activitiesA: {
        step: workflowA,
        path: "result.activities",
      },
      activitiesB: {
        step: workflowB,
        path: "result.activities",
      },
    },
  },
})
  .step(workflowA, {
    variables: {
      city: {
        step: "trigger",
        path: "cityA",
      },
    },
  })
  .step(workflowB, {
    variables: {
      city: {
        step: "trigger",
        path: "cityB",
      },
    },
  });

weatherWorkflow.commit();
```

In this example:

1. We define schemas for type safety across all workflows
2. Each step has proper input and output schemas
3. The nested workflows have their own trigger schemas and result mappings
4. Data is passed through using variables syntax in the `.step()` calls
5. The main workflow combines data from both nested workflows
