# Understanding Parallel Execution

Learn how to run multiple workflow steps simultaneously to improve performance when steps don't depend on each other.

## When to Use Parallel Execution

Use parallel execution when you have steps that:

- **Don't depend on each other**: Can run independently
- **Take time**: Network requests, AI calls, or heavy computations
- **Process the same input**: Multiple analyses of the same data

## Example Scenario

Imagine you want to analyze content in three different ways:

1. SEO analysis
2. Readability analysis
3. Sentiment analysis

These can all run at the same time since they don't depend on each other!

## Creating Parallel Steps

The .parallel() method on a workflow executes multiple steps in parallel.

```typescript
workflow.parallel([stepOne, stepTwo]);
```

## Performance Benefits

Running steps in parallel:

- **Faster execution**: Steps run simultaneously instead of waiting
- **Improved user experience**: Shorter wait times

Next, you'll create the other parallel steps and see how to combine them!
