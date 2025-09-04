# Understanding Conditional Branching

Learn how to create workflows that take different paths based on data conditions, making your workflows more intelligent and adaptive.

## What is Conditional Branching?

Conditional branching allows workflows to:

- **Make decisions**: Choose different processing paths based on data
- **Handle variations**: Process different content types differently
- **Optimize performance**: Skip unnecessary steps for certain inputs
- **Customize behavior**: Provide different experiences based on conditions

## Real-World Example

Imagine a content processing workflow that:

- **Short content** (< 50 words): Gets quick processing
- **Medium content** (50-200 words): Gets standard processing
- **Long content** (> 200 words): Gets detailed processing with extra analysis

## Basic Branching Syntax

```typescript
.branch([
  [condition1, step1],
  [condition2, step2],
  [condition3, step3]
])
```

Where:

- **condition**: An async function that returns `true` or `false`
- **step**: The step to execute if the condition is `true`

## Condition Functions

Conditions are functions that examine the input data:

```typescript
// Example condition function
async ({ inputData }) => {
  return inputData.wordCount < 50;
};
```

## Multiple Paths

- If multiple conditions are `true`, **all matching steps run in parallel**
- If no conditions are `true`, the workflow continues without executing any branch steps
- Conditions are evaluated in order, but matching steps run simultaneously

## Benefits

- **Smart routing**: Send data down the most appropriate path
- **Performance**: Skip expensive operations when not needed
- **Flexibility**: Handle different scenarios in one workflow
- **Maintainability**: Clear logic for different processing paths

Next, you'll create a workflow with conditional branches!
