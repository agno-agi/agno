# Dojo Frontend + Agno Backend Integration Guide

This guide explains how to connect the Dojo frontend to Agno backend agents using the AG-UI protocol bridge.

## Overview

The integration enables:
- Real-time streaming of agent responses
- Frontend-defined tool execution
- Human-in-the-loop workflows
- State synchronization between frontend and backend
- Multi-agent routing based on features

## Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  Dojo Frontend  │ ──AG-UI→│  Agno Backend   │ ──LLM──→│  AI Models      │
│  (CopilotKit)   │ ←Events─│  (FastAPI)      │ ←──────│  (GPT-4, etc)   │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

## Quick Start

### 1. Start the Agno Backend

```bash
# Install dependencies
pip install agno ag-ui

# Run the multi-agent backend
python cookbook/examples/agui_bridge/dojo_multi_agent_router.py
```

The backend will start on `http://localhost:8000` with AG-UI endpoints for each agent.

### 2. Configure the Frontend

Create a `.env.local` file in the `dojo` directory:

```env
NEXT_PUBLIC_AGNO_URL=http://localhost:8000
```

### 3. Run the Dojo Frontend

```bash
cd dojo
npm install
npm run dev
```

The frontend will start on `http://localhost:3000`.

## How It Works

### Frontend (Dojo)

The frontend uses CopilotKit with custom HTTP agents that connect to Agno:

```typescript
// agno-http-agent.ts
export class AgnoHttpAgent extends HttpAgent {
  constructor(agentName: string) {
    super({
      url: `${AGNO_URL}/agui/awp?agent=${agentName}`,
      headers: { "Content-Type": "application/json" }
    });
  }
}
```

### Backend (Agno)

The backend exposes AG-UI compatible endpoints for each agent:

```python
# Enable AG-UI in FastAPI app
app = FastAPIApp(agent=agent)
api = app.get_app(enable_agui=True)
```

### Agent Routing

Different features in Dojo connect to different agents:

| Dojo Feature | Agent Name | Endpoint |
|--------------|------------|----------|
| Agentic Chat | `chat_agent` | `/agui/awp?agent=chat_agent` |
| Generative UI | `generative_ui_agent` | `/agui/awp?agent=generative_ui_agent` |
| Human-in-the-Loop | `human_in_loop_agent` | `/agui/awp?agent=human_in_loop_agent` |
| Predictive State | `predictive_state_agent` | `/agui/awp?agent=predictive_state_agent` |
| Shared State | `shared_state_agent` | `/agui/awp?agent=shared_state_agent` |
| Tool-based UI | `tool_ui_agent` | `/agui/awp?agent=tool_ui_agent` |

## Frontend Tool Execution

The AG-UI bridge enables agents to call frontend-defined tools:

### Frontend Tool Definition (CopilotKit)

```typescript
useCopilotAction({
  name: "confirmAction",
  description: "Get user confirmation",
  parameters: [
    { name: "action", type: "string", description: "Action to confirm" }
  ],
  handler: async ({ action }) => {
    return await getUserConfirmation(action);
  }
});
```

### Backend Tool Usage (Agno)

When the agent calls a frontend tool:

```python
# The agent can call frontend tools
await agent.call_tool("confirmAction", {"action": "Delete file"})
```

The AG-UI bridge will:
1. Suspend agent execution
2. Send a `ToolCallStartEvent` to the frontend
3. Wait for the frontend to execute the tool
4. Resume execution with the tool result

## Event Streaming

All agent activities are streamed as AG-UI events:

```typescript
// Frontend receives events
agent.run(input).subscribe({
  next: (event) => {
    switch (event.type) {
      case EventType.TEXT_MESSAGE_CONTENT:
        // Update UI with streaming text
        break;
      case EventType.TOOL_CALL_START:
        // Handle tool execution
        break;
      case EventType.STATE_SNAPSHOT:
        // Update application state
        break;
    }
  }
});
```

## Examples

### 1. Human-in-the-Loop Workflow

```python
# Backend agent
@agent.tool
def confirm_action(action: str, reason: str) -> bool:
    """Get user confirmation for an action"""
    # This is a frontend tool - execution will be suspended
    pass

# Agent can use it naturally
result = confirm_action(
    action="Delete user data",
    reason="User requested account deletion"
)
```

### 2. State Synchronization

```python
# Backend updates state
@agent.tool
def update_recipe(skill_level: str, cooking_time: str):
    """Update recipe parameters"""
    return {"skill_level": skill_level, "cooking_time": cooking_time}

# Frontend receives state updates via STATE_SNAPSHOT events
```

### 3. Generative UI

```python
# Backend generates UI steps
@agent.tool
def update_steps(steps: list[dict]):
    """Update task steps in the UI"""
    return {"steps": steps, "total": len(steps)}
```

## Testing

Test the integration:

```bash
# Test AG-UI endpoint
curl -X POST http://localhost:8000/agui/awp?agent=chat_agent \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

## Troubleshooting

### Connection Issues

1. Check backend is running: `http://localhost:8000/docs`
2. Verify CORS settings in backend
3. Check frontend environment variables

### Event Streaming Issues

1. Ensure AG-UI is enabled: `enable_agui=True`
2. Check browser console for WebSocket/SSE errors
3. Verify event encoder is working properly

### Tool Execution Issues

1. Ensure tool names match between frontend and backend
2. Check tool parameter types match
3. Verify frontend tool handlers are registered

## Advanced Topics

### Custom Event Handling

Extend the AG-UI bridge for custom events:

```python
class CustomBridge(AGUIBridge):
    async def emit_custom_event(self, data: dict):
        event = BaseEvent(
            type="custom.event",
            data=data
        )
        await self.emit_event(event)
```

### Multi-Agent Coordination

Use the router pattern for complex multi-agent scenarios:

```python
router = MultiAgentRouter()
router.add_agent("research", research_agent)
router.add_agent("writer", writer_agent)
router.add_agent("reviewer", reviewer_agent)
```

## Next Steps

1. Explore each Dojo feature with the connected backend
2. Customize agents for your specific use cases
3. Add more sophisticated tools and state management
4. Implement authentication and authorization
5. Deploy to production with proper scaling 