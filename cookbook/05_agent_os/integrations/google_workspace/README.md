# Google Workspace Agent

Build agents that manage Gmail, Google Drive, Google Calendar, Sheets, Docs, and Chat using the [Google Workspace CLI](https://github.com/googleworkspace/cli) as an MCP server.

Instead of configuring individual Google toolkits with separate OAuth flows, `gws mcp` gives your agent access to all Workspace services through a single MCP connection.

## Setup

### 1. Install the Google Workspace CLI

```bash
npm install -g @googleworkspace/cli
```

### 2. Authenticate

```bash
gws auth setup
```

This walks you through creating a Google Cloud project and OAuth credentials. You only need to do this once.

### 3. Verify

```bash
# List your recent emails
gws gmail users messages list --params '{"userId": "me", "maxResults": 3}'

# List upcoming calendar events
gws calendar events list --params '{"calendarId": "primary", "maxResults": 3}'
```

## Cookbooks

| File | Description |
|------|-------------|
| `workspace_standalone.py` | Plain agent with gws tools, no server needed. Good for scripts and experiments. |
| `workspace_agent.py` | AgentOS app with Gmail + Drive + Calendar. The standard setup. |
| `workspace_full.py` | All Workspace services enabled (Gmail, Drive, Calendar, Sheets, Docs, Chat). |
| `workspace_team.py` | Team of specialist agents — one per service, with a coordinator. Avoids tool count limits. |
| `workspace_telegram.py` | Workspace agent deployed to Telegram. Manage emails and calendar from your phone. |

## How It Works

The Google Workspace CLI (`gws`) can run as an MCP server:

```bash
gws mcp -s gmail,drive,calendar
```

This exposes every API method for the selected services as MCP tools. Agno's `MCPTools` connects to this server and registers all discovered tools with your agent:

```python
from agno.agent import Agent
from agno.tools.mcp import MCPTools

agent = Agent(
    tools=[MCPTools(command="gws", args=["mcp", "-s", "gmail,drive,calendar"])],
)
```

The agent can then call any Gmail, Drive, or Calendar API method — list emails, create events, upload files — all through the MCP protocol.

## Choosing Services

More services means more tools. If you hit tool count limits, either:

1. **Select fewer services** with `-s`:
   ```python
   MCPTools(command="gws", args=["mcp", "-s", "gmail,calendar"])
   ```

2. **Use a team** (see `workspace_team.py`): each agent gets its own service, and the coordinator routes requests.

## Running

```bash
# Standalone (no server)
.venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_standalone.py

# AgentOS (with web UI at http://localhost:7777)
.venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_agent.py
```
