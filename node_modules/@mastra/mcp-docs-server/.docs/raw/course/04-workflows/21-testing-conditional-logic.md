# Testing Conditional Logic

Let's test your conditional workflow with different types of content to see how it routes to different processing paths.

## Registering the New Workflow

Update your Mastra configuration to include your new workflow workflows:

```typescript
// In src/mastra/index.ts
import {
  contentWorkflow,
  aiContentWorkflow,
  parallelAnalysisWorkflow,
  conditionalWorkflow,
} from "./workflows/content-workflow";

export const mastra = new Mastra({
  workflows: {
    contentWorkflow,
    aiContentWorkflow,
    parallelAnalysisWorkflow,
    conditionalWorkflow, // Add the conditional workflow
  },
  // ... rest of configuration
});
```

## Testing the conditional workflow

You can now test this new conditional workflow in the playground. Be sure to test different content lengths and content types.

## Understanding the Flow

1. **Assessment step** analyzes content and determines category/complexity
2. **Branch conditions** are evaluated against the assessment results
3. **Matching step** executes based on which condition(s) are true
4. **Results** show which processing path was taken

## Debugging Conditions

If a condition isn't working as expected:

- Check the assessment step output
- Verify condition logic matches your expectations
- Test individual conditions in isolation
- Add console.log statements to track condition evaluation

## Branch Benefits

Conditional workflows provide:

- **Intelligent routing**: Right processing for right content
- **Performance optimization**: Skip heavy processing for simple content
- **Customized experience**: Different handling for different scenarios
- **Scalable logic**: Easy to add new conditions and processing paths

Next, you'll learn about streaming workflow results for better user experience!
