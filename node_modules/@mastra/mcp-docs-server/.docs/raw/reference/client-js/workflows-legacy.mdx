---
title: Mastra Client Workflows (Legacy) API
description: Learn how to interact with and execute automated legacy workflows in Mastra using the client-js SDK.
---

# Workflows (Legacy) API

The Workflows (Legacy) API provides methods to interact with and execute automated legacy workflows in Mastra.

## Getting All Legacy Workflows

Retrieve a list of all available legacy workflows:

```typescript
const workflows = await mastraClient.getLegacyWorkflows();
```

## Working with a Specific Legacy Workflow

Get an instance of a specific legacy workflow:

```typescript
const workflow = mastraClient.getLegacyWorkflow("workflow-id");
```

## Legacy Workflow Methods

### Get Legacy Workflow Details

Retrieve detailed information about a legacy workflow:

```typescript
const details = await workflow.details();
```

### Start Legacy Workflow run asynchronously

Start a legacy workflow run with triggerData and await full run results:

```typescript
const { runId } = workflow.createRun();

const result = await workflow.startAsync({
  runId,
  triggerData: {
    param1: "value1",
    param2: "value2",
  },
});
```

### Resume Legacy Workflow run asynchronously

Resume a suspended legacy workflow step and await full run result:

```typescript
const { runId } = createRun({ runId: prevRunId });

const result = await workflow.resumeAsync({
  runId,
  stepId: "step-id",
  contextData: { key: "value" },
});
```

### Watch Legacy Workflow

Watch legacy workflow transitions

```typescript
try {
  // Get workflow instance
  const workflow = mastraClient.getLegacyWorkflow("workflow-id");

  // Create a workflow run
  const { runId } = workflow.createRun();

  // Watch workflow run
  workflow.watch({ runId }, (record) => {
    // Every new record is the latest transition state of the workflow run

    console.log({
      activePaths: record.activePaths,
      results: record.results,
      timestamp: record.timestamp,
      runId: record.runId,
    });
  });

  // Start workflow run
  workflow.start({
    runId,
    triggerData: {
      city: "New York",
    },
  });
} catch (e) {
  console.error(e);
}
```

### Resume Legacy Workflow

Resume legacy workflow run and watch legacy workflow step transitions

```typescript
try {
  //To resume a workflow run, when a step is suspended
  const { run } = createRun({ runId: prevRunId });

  //Watch run
  workflow.watch({ runId }, (record) => {
    // Every new record is the latest transition state of the workflow run

    console.log({
      activePaths: record.activePaths,
      results: record.results,
      timestamp: record.timestamp,
      runId: record.runId,
    });
  });

  //resume run
  workflow.resume({
    runId,
    stepId: "step-id",
    contextData: { key: "value" },
  });
} catch (e) {
  console.error(e);
}
```

### Legacy Workflow run result

A legacy workflow run result yields the following:

| Field         | Type                                                                           | Description                                                        |
| ------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `activePaths` | `Record<string, { status: string; suspendPayload?: any; stepPath: string[] }>` | Currently active paths in the workflow with their execution status |
| `results`     | `LegacyWorkflowRunResult<any, any, any>['results']`                            | Results from the workflow execution                                |
| `timestamp`   | `number`                                                                       | Unix timestamp of when this transition occurred                    |
| `runId`       | `string`                                                                       | Unique identifier for this workflow run instance                   |
