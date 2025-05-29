# AG-UI Protocol Bridge for Agno

This module provides a bridge between the AG-UI (Agent-User Interaction) protocol and Agno agents, enabling frontend-defined tools, real-time streaming, and human-in-the-loop workflows.

## Overview

The AG-UI bridge allows Agno agents to:
- Accept frontend-defined tools
- Stream responses in real-time using AG-UI events
- Suspend execution when frontend interaction is needed
- Resume processing with tool results from the frontend
- Maintain proper state synchronization

## Key Features

### 1. Frontend Tool Execution
Frontend applications can define tools that the agent can use. When the agent calls these tools, execution is suspended until the frontend provides results.

### 2. Event Streaming
All agent responses are streamed as AG-UI events, providing real-time feedback to the frontend.

### 3. Protocol Compatibility
The bridge translates between Agno's message format and AG-UI's event-driven protocol.

## Architecture

```
Frontend (AG-UI Client) <-> AG-UI Bridge <-> Agno Agent
                               |
                               ├── Event Translation
                               ├── Tool Suspension
                               └── State Management
```

## Usage

### Basic Setup

```python
from agno import Agent, Model
from agno.app.fastapi import FastAPIApp

# Create an Agno agent
agent = Agent(
    name="My AG-UI Agent",
    model=Model(id="gpt-4o"),
    instructions="You are a helpful assistant."
)

# Create FastAPI app with AG-UI support
app = FastAPIApp(agent=agent)
api = app.get_app(enable_agui=True)

# Serve the API
app.serve(api, host="0.0.0.0", port=8000)
```

### Frontend Connection

```typescript
import { HttpAgent } from "@ag-ui/client";

const agent = new HttpAgent({
  url: "http://localhost:8000/agui/awp",
  headers: { "Content-Type": "application/json" }
});

// Define frontend tools
const tools = [{
  name: "confirmAction",
  description: "Get user confirmation",
  parameters: {
    type: "object",
    properties: {
      action: { type: "string" }
    }
  }
}];

// Run agent with tools
agent.runAgent({ tools }).subscribe({
  next: (event) => {
    // Handle events
  }
});
```

## Implementation Details

### Event Flow

1. **RUN_STARTED**: Signals the beginning of agent execution
2. **TEXT_MESSAGE_START/CONTENT/END**: Streams text responses
3. **TOOL_CALL_START/ARGS/END**: Requests frontend tool execution
4. **STATE_SNAPSHOT/DELTA**: Synchronizes state
5. **RUN_FINISHED**: Marks completion

### Tool Execution Suspension

When a frontend tool is called:
1. The bridge emits TOOL_CALL events
2. Agent execution is suspended via asyncio.Future
3. Frontend executes the tool and sends results
4. Agent resumes with the tool result

### Current Limitations

1. **Continuation Support**: Full execution continuation after tool calls requires further Agno modifications
2. **Team Support**: Only individual agents are supported, not teams
3. **State Management**: Complex state synchronization is still in development

## Examples

See `cookbook/examples/agui_bridge/` for complete examples:
- `frontend_tools_example.py`: Basic frontend tool execution
- `human_in_the_loop_example.py`: Complete human-in-the-loop workflow

## Future Enhancements

1. **WebSocket Support**: For true bidirectional communication
2. **Team Support**: Enable AG-UI for Agno teams
3. **Advanced State Sync**: Full JSON Patch support for state deltas
4. **Tool Result Injection**: Direct message injection for tool results 