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

Now you need to run a `AGUIApp` exposing your Agent. You can run this example file:
```python
from agno.agent.agent import Agent
from agno.app.agui.app import AGUIApp
from agno.models.openai import OpenAIChat

# Setup the Agno Agent
chat_agent = Agent(model=OpenAIChat(id="gpt-4o"))

# Setup the AG-UI App
agui_app = AGUIApp(agent=chat_agent)
agui_app.serve(app="basic:app", port=8000, reload=True)
```

## Run your frontend

You can run [Dojo](https://github.com/ag-ui-protocol/ag-ui/tree/main/typescript-sdk/apps/dojo), an advanced and customizable option to use as frontend for AG-UI agents.
You can learn more on how to run it [here](https://github.com/ag-ui-protocol/ag-ui/tree/main/typescript-sdk/apps/dojo).


### Chat with your Agent

If you are running Dojo as your frontend, you can now go to http://localhost:3000 in your browser and select your agent from the available integrations.


## Examples

Check out these example agents and teams:

- [Chat Agent](./basic.py) - Simple conversational agent
- [Research Team](./research_team.py) - Team of agents working together
