# AG-UI Bridge Quick Start Guide

Get started with the AG-UI protocol bridge between Dojo frontend and Agno backend in minutes!

## Prerequisites

- Python 3.9+
- Node.js 16+
- npm or yarn

## Quick Start

### 1. Install Dependencies

```bash
# Backend dependencies
pip install agno ag-ui httpx

# Frontend dependencies (in dojo directory)
cd dojo
npm install
```

### 2. Start the Backend

```bash
# Option 1: Run the multi-agent app (recommended)
python cookbook/apps/agui/basic.py

# Option 2: Run a single agent
python cookbook/apps/agui/single_agent.py
```

The backend will start at `http://localhost:8000`

### 3. Configure Frontend

Create `.env.local` in the `dojo` directory:

```env
NEXT_PUBLIC_AGNO_URL=http://localhost:8000
```

### 4. Start Frontend

```bash
cd dojo
npm run dev
```

The frontend will start at `http://localhost:3000`

## Test the Integration

### 1. Quick Test

Visit `http://localhost:3000` and try any of the Dojo features. Each feature connects to a different Agno agent.

### 2. Run Integration Tests

```bash
# Make sure backend is running first!
python cookbook/apps/agui/test_integration.py
```

### 3. Test with cURL

```bash
# Test AG-UI endpoint (note the camelCase field names)
curl -X POST "http://localhost:8000/agui/awp?agent=chat_agent" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"id": "1", "role": "user", "content": "Hello!"}
    ],
    "threadId": "test-thread-1",
    "runId": "test-run-1",
    "state": {},
    "tools": [],
    "context": [],
    "forwardedProps": {}
  }'
```

## Creating Your Own Agent

### Backend Agent

```python
from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.app.fastapi.app import FastAPIApp
from agno.tools import tool

# Define tools
@tool
def my_tool(param: str) -> str:
    """A custom tool"""
    return f"Processed: {param}"

# Create agent
agent = Agent(
    name="my_agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful assistant.",
    tools=[my_tool],
    markdown=True,
)

# Create app
app = FastAPIApp(agent=agent)
api = app.get_app(enable_agui=True)

if __name__ == "__main__":
    app.serve(api, host="0.0.0.0", port=8000)
```

### Frontend Integration

```typescript
// Create agent connection
import { AgnoHttpAgent } from "@/agno-http-agent";

const agent = new AgnoHttpAgent("my_agent");

// Use with CopilotKit
import { useCopilotAgent } from "@copilotkit/react-core";

function MyComponent() {
  useCopilotAgent({
    name: "myAgent",
    agent: agent,
  });
  
  // Your component code
}
```

## Agent Features

### Chat Agent
Basic conversational AI:
```bash
curl -X POST "http://localhost:8000/agui/awp?agent=chat_agent" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Tell me a joke"}],
    "threadId": "test-1",
    "runId": "run-1",
    "state": {},
    "tools": [],
    "context": [],
    "forwardedProps": {}
  }'
```

### Generative UI Agent
Creates UI components:
```bash
curl -X POST "http://localhost:8000/agui/awp?agent=generative_ui_agent" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Create a todo list"}],
    "threadId": "test-2",
    "runId": "run-2",
    "state": {},
    "tools": [],
    "context": [],
    "forwardedProps": {}
  }'
```

### Human-in-the-Loop Agent
Requires user confirmation:
```bash
curl -X POST "http://localhost:8000/agui/awp?agent=human_in_loop_agent" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Delete important file"}],
    "threadId": "test-3",
    "runId": "run-3",
    "state": {},
    "tools": [{
      "name": "confirmAction",
      "description": "Get user confirmation",
      "parameters": {
        "type": "object",
        "properties": {
          "action": {"type": "string"}
        }
      }
    }],
    "context": [],
    "forwardedProps": {}
  }'
```

## Debugging

### Enable Debug Logging

```python
# Backend
import logging
logging.basicConfig(level=logging.DEBUG)

# Or in agent
agent = Agent(
    name="my_agent",
    debug_mode=True,
    # ...
)
```

### Check Endpoints

```bash
# List agents
curl http://localhost:8000/agui/agents

# Health check
curl http://localhost:8000/agui/health

# API docs
open http://localhost:8000/docs
```

### Common Issues

1. **Connection refused**: Make sure backend is running
2. **CORS errors**: Backend should have CORS enabled by default
3. **No streaming**: Check browser console for SSE errors
4. **400 Bad Request**: Ensure all required fields are included with camelCase names

## Next Steps

1. **Explore Examples**
   - `cookbook/apps/agui/` - Various AG-UI examples
   - `dojo/src/app/feature/` - Frontend feature implementations

2. **Build Your App**
   - Create custom agents with specific tools
   - Design frontend UI with CopilotKit
   - Add authentication and state management

3. **Deploy to Production**
   - Use environment variables for configuration
   - Set up proper CORS origins
   - Add monitoring and logging

## Resources

- [AG-UI Protocol Documentation](https://ag-ui.dev)
- [Agno Documentation](https://docs.agno.ai)
- [CopilotKit Documentation](https://docs.copilotkit.ai)
- [Integration Guide](./dojo_integration_guide.md)

## Support

- GitHub Issues: [agno/issues](https://github.com/agno/agno/issues)
- Discord: [Join our community](https://discord.gg/agno)

Happy building! 🚀 