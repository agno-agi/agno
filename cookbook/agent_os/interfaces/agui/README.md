# AG-UI Integration for Agno

AG-UI standardizes how front-end applications connect to AI agents through an open protocol.
With this integration, you can write your Agno Agents and Teams, and get a ChatGPT-like UI automatically.

**Example: Chat with a simple agent:**

```python my_agent.py
from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# Setup the Agno Agent
chat_agent = Agent(model=OpenAIChat(id="gpt-4o"))

# Setup AgentOS with AG-UI Interface
agent_os = AgentOS(
    agents=[chat_agent],
    interfaces=[AGUI(agent=chat_agent)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="my_agent:app", port=9001, reload=True)
```

That's it! Your Agent is now exposed in an AG-UI compatible way, and can be used in any AG-UI compatible front-end.


## Usage example

### Setup

Start by installing our backend dependencies:

```bash
pip install ag-ui-protocol
```

### Run your backend

Now you need to run an agent with AGUI interface. You can run the [Basic Chat Agent](./basic.py) example!

## Run your frontend

You can use [Dojo](https://github.com/ag-ui-protocol/ag-ui/tree/main/typescript-sdk/apps/dojo), an advanced and customizable option to use as frontend for AG-UI agents.

1. Clone the project: `git clone https://github.com/ag-ui-protocol/ag-ui.git`
2. Follow the instructions [here](https://github.com/ag-ui-protocol/ag-ui/tree/main/typescript-sdk/apps/dojo) to learn how to install the needed dependencies and run the project.
3. Remember to install the dependencies in `/ag-ui/typescript-sdk` with `pnpm install`, and to build the Agno package in `/integrations/
4. Set the environment variable: `AGNO_URL=http://localhost:9001`
agno` with `pnpm run build`.
5. You can now run your Dojo! It will show our Agno agent as one of the available options.
### Chat with your Agent

If you are running Dojo as your frontend, you can now go to http://localhost:3000 in your browser and chat with your Agno Agent.


## Examples

Check out these example agents and teams:

- **[Basic Chat Agent](./basic.py)** - Simple conversational agent
- **[Agent with Tools](./agent_with_tools.py)** - Agent with both agent and frontend tools
- **[Research Team](./research_team.py)** - Team of agents working together
- **[Reasoning Agent](./reasoning_agent.py)** - Agent with reasoning capabilities
- **[Structured Output](./structured_output.py)** - Agent with structured response formats

**Environment Variables:**
- `AGNO_URL=http://localhost:9001` - Point Dojo to your agent
- `OPENAI_API_KEY=your_key` - Required for OpenAI models
