# Google Workspace Agent

Build agents that manage Gmail, Google Drive, Google Calendar, Sheets, and Docs using the [Google Workspace CLI](https://github.com/googleworkspace/cli) as an MCP server.

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

### 3. Export credentials for subprocess access

The gws MCP server runs as a subprocess and needs access to your credentials. Export them to a plain JSON file:

```bash
gws auth export > ~/gws-credentials.json
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=~/gws-credentials.json
```

### 4. Verify

```bash
gws gmail users messages list --params '{"userId": "me", "maxResults": 3}'
gws calendar events list --params '{"calendarId": "primary", "maxResults": 3}'
```

## Cookbooks

| File | Description |
|------|-------------|
| `workspace_standalone.py` | Plain agent with gws tools, no server needed. Good for scripts and experiments. |
| `workspace_agent.py` | AgentOS app with Gmail + Drive + Calendar. The standard setup. |
| `workspace_full.py` | All Workspace services (Gmail, Drive, Calendar, Sheets, Docs). |
| `workspace_team.py` | Team of specialist agents — one per service, with a coordinator. |

## How It Works

The Google Workspace CLI (`gws`) can run as an MCP server:

```bash
gws mcp -s gmail,drive,calendar
```

This exposes every API method for the selected services as MCP tools. Agno's `MCPTools` connects to this server and registers the tools with your agent:

```python
from agno.tools.mcp import MCPTools

workspace_tools = MCPTools(
    command="gws mcp -s gmail,drive,calendar",
    env=gws_env,
    include_tools=[
        "gmail_users_messages_list",
        "gmail_users_messages_get",
        "drive_files_list",
        "calendar_events_list",
    ],
)
```

## Important: Tool Count Limits

OpenAI models have a 128 tool limit. A single `gws mcp -s gmail,drive,calendar` exposes ~173 tools. Use `include_tools` to select only the tools you need, or split services across a team of agents (see `workspace_team.py`).

## Important: The `params` Pattern

All gws tools accept a `params` object for path and query parameters. Your agent instructions should include:

```
For Gmail: params={'userId': 'me', 'maxResults': 5}
For Calendar: params={'calendarId': 'primary'}
For message details: params={'userId': 'me', 'id': '<id>', 'format': 'metadata'}
```

Use `format='metadata'` when reading Gmail messages to avoid large payloads that blow the context window.

## Running

```bash
# Set credentials for subprocess
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=~/gws-credentials.json

# Standalone (no server)
.venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_standalone.py

# AgentOS (with web UI at http://localhost:7777)
.venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_agent.py
```
