# AG-UI Integration for Agno

AG-UI standardizes how front-end applications connect to AI agents through an open protocol.
With this integration, you can write your Agno Agents and Teams, and get a ChatGPT-like UI automatically.

**Example: Chat with a simple agent:**

```python my_agent.py
from agno.agent.agent import Agent
from agno.app.agui.app import AGUIApp
from agno.models.openai import OpenAIChat

# Setup the Agno Agent
chat_agent = Agent(model=OpenAIChat(id="gpt-4o"))

# Setup the AG-UI App
agui_app = AGUIApp(agent=chat_agent)
agui_app.serve(app="basic:app", port=8000, reload=True)
```

That's it! Your Agent is now exposed in an AG-UI compatible way, and can be used in any AG-UI compatible front-end.


## Usage example

### Setup

Start by installing our backend dependencies:

```bash
pip install ag-ui-protocol
```

### Run your backend

Now you need to run a `AGUIApp` exposing your Agent. You can run the `cookbook/apps/agui/basic.py` example!

## Run your frontend

You can use [Dojo](https://github.com/ag-ui-protocol/ag-ui/tree/main/typescript-sdk/apps/dojo), an advanced and customizable option to use as frontend for AG-UI agents.

1. Clone the project: `git clone https://github.com/ag-ui-protocol/ag-ui.git`
2. Follow the instructions [here](https://github.com/ag-ui-protocol/ag-ui/tree/main/typescript-sdk/apps/dojo) to learn how to install the needed dependencies and run the project.
3. Remember to install the dependencies in `/ag-ui/typescript-sdk` with `pnpm install`, and to build the Agno package in `/integrations/agno` with `pnpm run build`.
4. You can now run your Dojo! It will show our Agno agent as one of the available options.


### Chat with your Agent

If you are running Dojo as your frontend, you can now go to http://localhost:3000 in your browser and chat with your Agno Agent.


## Examples

Check out these example agents and teams:

- [Chat Agent](./basic.py) - Simple conversational agent
- [Agent with Tools](./agent_with_tools.py) - An agent using tools
- [Research Team](./research_team.py) - Team of agents working together
