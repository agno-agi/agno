# A2A (Agent-to-Agent) Interface for Agno

A2A enables programmatic agent-to-agent communication through a standardized API protocol.
With this integration, you can expose your Agno Agents and Teams via REST API endpoints for agent-to-agent interactions.

**Example: Expose an agent via A2A:**

```python my_agent.py
from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Setup the Agno Agent
chat_agent = Agent(
    name="my-agent",
    id="my_agent",
    model=OpenAIChat(id="gpt-4o")
)

# Setup AgentOS with A2A Interface
agent_os = AgentOS(
    agents=[chat_agent],
    a2a_interface=True,
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="my_agent:app", port=7777, reload=True)
```

That's it! Your Agent is now exposed via A2A protocol and can be called by other agents or systems.

## Usage example

### Setup

Start by installing the backend dependencies:

```bash
pip install agno
```

### Run your backend

Now you need to run an agent with A2A interface. You can run the [Basic Agent](./basic.py) example:

```bash
python cookbook/agent_os/interfaces/a2a/basic.py
```

### Access your agent

Once running, your agent will be available at:
- **Agent endpoint**: `http://localhost:7777/a2a/agents/{id}/message:send`
- **API documentation**: `http://localhost:7777/docs`

### Making API calls

You can interact with your agent via A2A protocol (JSON-RPC 2.0):

```bash
curl -X POST http://localhost:7777/a2a/agents/{id}/message:send \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "id": "request-1",
    "params": {
      "message": {
        "messageId": "msg-1",
        "role": "user",
        "agentId": "basic-agent",
        "parts": [
          {
            "kind": "text",
            "text": "Hello, agent!"
          }
        ]
      }
    }
  }'
```

## Examples

Check out these example agents and teams:

- **[Basic Agent](./basic.py)** - Simple agent with A2A interface
- **[Agent with Tools](./agent_with_tools.py)** - Agent with tool capabilities
- **[Research Team](./research_team.py)** - Team of agents working together
- **[Reasoning Agent](./reasoning_agent.py)** - Agent with reasoning capabilities
- **[Structured Output](./structured_output.py)** - Agent with structured response formats

## Key Features

- **REST API**: Standard HTTP endpoints for agent interaction
- **Streaming Support**: Real-time streaming responses
- **Team Support**: Expose entire teams of agents
- **Tool Integration**: Agents can use tools and expose their capabilities
- **OpenAPI Docs**: Auto-generated API documentation at `/docs`

## Environment Variables

- `OPENAI_API_KEY=your_key` - Required for OpenAI models


## API Endpoints

When you enable A2A interface, the following endpoints are automatically created:

- `POST /a2a/agents/{id}/message:send` - Send a message to an agent or team (standard A2A protocol)
- `POST /a2a/agents/{id}/message:stream` - Stream messages to/from an agent or team (standard A2A protocol)
- `GET /agents/{id}/.well-known/agent-card.json` - Get Agent Card (standard A2A protocol)
- `GET /docs` - OpenAPI documentation
- `GET /config` - View AgentOS configuration

