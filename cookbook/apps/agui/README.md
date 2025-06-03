# AG-UI Integration for Agno

AG-UI lets you create AI agents and teams that users can interact with through a modern web interface. Write your agent or team in Python, and get a ChatGPT-like UI automatically.

**Example: A simple chat agent in 10 lines of code:**

```python
from agno import Agent
from agno.app.agui.app import AGUIApp
from agno.models.openai import OpenAIChat

agent = Agent(
    name="chat_agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful AI assistant.",
)
```

That's it! Your agents and teams are now accessible through a beautiful web interface.


## Quick Start

### Setup

```bash
pip install ag-ui-protocol
```

## Connecting to Dojo (Advanced UI)

Dojo[https://github.com/ag-ui-protocol/ag-ui/tree/main/typescript-sdk/apps/dojo] is an advanced, customizable frontend for AG-UI agents. Follow these steps to connect your Agno agent to Dojo:

### 1. Clone and Setup Dojo

```bash
# Clone the Dojo repository
git clone https://github.com/ag-ui-protocol/ag-ui/tree/main/typescript-sdk/apps/dojo
cd dojo
```

Follow the readme for setup instructions

### 2. Configure Your Agent Integration

Edit `integrations.ts` in the Dojo project to add your Agno agent:

```typescript
export const integrations = [
  {
    id: "my-agno-agent",
    name: "My Assistant",
    description: "Your agent description",
    poweredBy: "agno",
    icon: "🤖",
    endpoint: "http://localhost:8000/agui/awp",
    headers: {
      // Add any custom headers if needed
    },
    capabilities: {
      chat: true,
      voice: false,
      attachments: true,
    }
  }
];
```

### 3. Start Both Services

First, start your Agno agent:
```bash
python my_agent.py
```

Then, in another terminal, start Dojo:
```bash
cd dojo
npm run dev
```

### 4. Access Your Agent

Open http://localhost:3000 in your browser and select your agent from the available integrations.

## Examples

Check out these example agents and teams:

- [Chat Agent](./basic.py) - Simple conversational agent
- [Research Team](./research_team.py) - Team of agents working together
