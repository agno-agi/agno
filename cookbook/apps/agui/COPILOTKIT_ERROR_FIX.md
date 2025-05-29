# CopilotKit filterAdjacentAgentStateMessages Error Fix

## Issue
User was getting the following error when using the Dojo frontend with CopilotKit:
```
Uncaught (in promise) TypeError: Cannot read properties of undefined (reading 'forEach')
    at filterAdjacentAgentStateMessages (chunk-P2AUSQOK.mjs:85:12)
```

## Root Cause
CopilotKit was expecting an array of messages that included `AgentStateMessageOutput` entries, but the AG-UI route was not providing these. The `filterAdjacentAgentStateMessages` function was trying to iterate over messages that might be undefined or not include the expected agent state messages.

## Solution
Updated `dojo/src/app/api/copilotkit/route.ts` to:

1. **Send initial messages snapshot**: Added a messages snapshot event after the header to establish the messages array structure that CopilotKit expects.

2. **Send initial agent state message**: Added an initial `AgentStateMessageOutput` to establish the agent state.

3. **Handle state events**: Added support for converting AG-UI `STATE_SNAPSHOT` and `STATE_DELTA` events to `AgentStateMessageOutput` format.

## Changes Made

### 1. Added Messages Snapshot
```typescript
// Send initial messages snapshot to establish the messages array
const messagesSnapshot = {
  data: {
    generateCopilotResponse: {
      messages: (messages || []).map((msg: any) => ({
        __typename: "TextMessageOutput",
        id: msg.id,
        createdAt: new Date().toISOString(),
        content: msg.content || "",
        role: msg.role || "user",
        status: { code: "success", __typename: "SuccessMessageStatus" }
      }))
    }
  }
};
sendJSON(messagesSnapshot);
```

### 2. Added Initial Agent State
```typescript
// Send initial agent state
const initialAgentState = {
  data: {
    generateCopilotResponse: {
      messages: [{
        __typename: "AgentStateMessageOutput",
        threadId: agentInput.threadId,
        state: agentInput.state || {},
        running: false,
        agentName: agentName,
        nodeName: "main",
        runId: agentInput.runId,
        active: true,
        role: "assistant"
      }]
    }
  }
};
sendJSON(initialAgentState);
```

### 3. Added State Event Handling
```typescript
} else if (event.type === EventType.STATE_SNAPSHOT || event.type === EventType.STATE_DELTA) {
  console.log(`[CopilotKit Route] State event received: ${event.type}`);
  const stateEvent = event as any;
  
  // For state events, send an AgentStateMessageOutput
  graphqlEvent = {
    data: {
      generateCopilotResponse: {
        messages: [{
          __typename: "AgentStateMessageOutput",
          threadId: agentInput.threadId,
          state: event.type === EventType.STATE_SNAPSHOT ? stateEvent.snapshot : agentInput.state,
          running: true,
          agentName: agentName,
          nodeName: "main",
          runId: agentInput.runId,
          active: true,
          role: "assistant"
        }]
      }
    }
  };
}
```

## Testing
Created `test_copilotkit_fix.py` to verify the fix:
- Confirms that agent state messages are being sent
- Verifies the streaming response format
- Shows the complete event flow

## Result
The error is now fixed. CopilotKit receives the expected agent state messages and can properly filter them without throwing the TypeError. 