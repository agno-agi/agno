# @mastra/core

Mastra is the Typescript framework for building AI agents and assistants. It’s used by some of the largest companies in the world to build internal AI automation tooling and customer-facing agents.

This is the `core` package, which includes the main functionality of Mastra, including agents, workflows, tools, and telemetry.

## Installation

```bash
npm install @mastra/core
```

## Core Components

### Agents (`/agent`)

Mastra agents are autonomous AI entities that can understand instructions, use tools, and complete tasks. They encapsulate LLM interactions and can maintain conversation history, use provided tools, and follow specific behavioral guidelines through instructions.

```typescript
import { Agent } from '@mastra/core/agent';
import { openai } from '@ai-sdk/openai';

const agent = new Agent({
  name: 'my-agent',
  instructions: 'Your task-specific instructions',
  model: openai('gpt-4o-mini'),
  tools: {}, // Optional tools
});
```

[Agent documentation →](https://mastra.ai/docs/agents/overview)

### Workflows (`/workflows`)

Mastra workflows are a graph-based execution engine allowing you to chain, branch, and parallelize LLM calls. You can orchestrate complex AI tasks by combining multiple actions. Workflows handle state management, error recovery, and can include conditional logic.

```typescript
import { createWorkflow } from '@mastra/core/workflows';
import z from 'zod'

const workflow = createWorkflow({
  id: 'my-workflow',
  inputSchema: z.object({}),
  outputSchema: z.object({})
  steps: [
    // Workflow steps
  ],
});
```

[Workflow documentation →](https://mastra.ai/docs/workflows/overview)

### Tools (`/tools`)

Tools are functions that agents can use to interact with external systems or perform specific tasks. Each tool has a clear description and schema, making it easy for AI to understand and use them effectively.

```typescript
import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

const weatherInfo = createTool({
  id: 'Get Weather Information',
  inputSchema: z.object({
    city: z.string(),
  }),
  description: 'Fetches the current weather information for a given city',
  execute: async ({ context: { city } }) => {
    // Tool implementation
  },
});
```

[Tools documentation →](https://mastra.ai/docs/agents/adding-tools)

### Evals (`/eval`)

The evaluation system enables quantitative assessment of AI outputs. Create custom metrics to measure specific aspects of AI performance, from response quality to task completion accuracy.

```typescript
import { Agent } from '@mastra/core/agent';
import { openai } from '@ai-sdk/openai';
import { SummarizationMetric } from '@mastra/evals/llm';
import { ContentSimilarityMetric, ToneConsistencyMetric } from '@mastra/evals/nlp';

const model = openai('gpt-4o');

const agent = new Agent({
  name: 'ContentWriter',
  instructions: 'You are a content writer that creates accurate summaries',
  model,
  evals: {
    summarization: new SummarizationMetric(model),
    contentSimilarity: new ContentSimilarityMetric(),
    tone: new ToneConsistencyMetric(),
  },
});
```

[More evals documentation →](https://mastra.ai/docs/evals/overview)

### Logger (`/logger`)

The logging system provides structured, leveled logging with multiple transport options. It supports debug information, performance monitoring, and error tracking across your AI applications.

```typescript
import { LogLevel } from '@mastra/core/loggers';
import { PinoLogger } from '@mastra/loggers';

const logger = new PinoLogger({
  name: 'MyApp',
  level: LogLevel.INFO,
});
```

[More logging documentation →](https://mastra.ai/reference/observability/logging)

### Telemetry (`/telemetry`)

Telemetry provides OpenTelemetry (Otel) integration for comprehensive monitoring of your AI systems. Track latency, success rates, and system health with distributed tracing and metrics collection.

```typescript
import { Mastra } from '@mastra/core';

const mastra = new Mastra({
  telemetry: {
    serviceName: 'my-service',
    enabled: true,
    sampling: {
      type: 'ratio',
      probability: 0.5,
    },
    export: {
      type: 'otlp',
      endpoint: 'https://otel-collector.example.com/v1/traces',
    },
  },
});
```

[More Telemetry documentation →](https://mastra.ai/reference/observability/telemetry)

## Additional Resources

- [Getting Started Guide](https://mastra.ai/docs/getting-started/installation)
- [API Reference](https://mastra.ai/reference)
- [Examples](https://mastra.ai/docs/examples)
- [Deployment Guide](https://mastra.ai/docs/deployment/overview)
