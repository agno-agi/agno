# A2A Protocol & MCP (Model Context Protocol)

Agno supports two inter-agent / external communication protocols:

| Protocol | Direction | Use case |
|----------|-----------|---------|
| **A2A (Agent-to-Agent)** | Agent ↔ Agent | Distributed agent networks, cross-service agent calls |
| **MCP (Model Context Protocol)** | Tool source ↔ Agent | Connect external tool servers; expose Agno agents to any MCP client |

---

## A2A Protocol

**Directory:** `libs/agno/agno/client/a2a/`
**Cookbook:** `cookbook/92_integrations/a2a/`

A2A is an open protocol (originally by Google) for agent-to-agent communication over HTTP. It defines a standard request/response format so any A2A-compatible agent can talk to any other.

### Running an A2A server

**Cookbook:** `cookbook/92_integrations/a2a/basic_agent/`

```python
# basic_agent.py — define the agent executor
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import Part, TextPart
from a2a.utils import new_agent_text_message
from agno.agent import Agent, Message, RunOutput
from agno.models.openai import OpenAIChat
from typing_extensions import override

agent = Agent(model=OpenAIChat(id="gpt-4o"))

class BasicAgentExecutor(AgentExecutor):
    def __init__(self):
        self.agent = agent

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        # Extract text from A2A message parts
        message = Message(role="user", content="")
        for part in context.message.parts:
            if isinstance(part, Part) and isinstance(part.root, TextPart):
                message.content = part.root.text
                break

        # Run the Agno agent
        result: RunOutput = await self.agent.arun(message)

        # Return result as A2A message
        event_queue.enqueue_event(new_agent_text_message(result.content))

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("Cancel not supported")
```

```python
# __main__.py — start the A2A server
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from basic_agent import BasicAgentExecutor

handler = DefaultRequestHandler(
    agent_executor=BasicAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2AStarletteApplication(
    agent_card=AgentCard(
        name="Basic Agno Agent",
        description="A simple Agno agent exposed via A2A protocol",
        url="http://localhost:9999",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="general",
                name="General Assistant",
                description="Answer questions and help with tasks",
            )
        ],
    ),
    http_handler=handler,
)

if __name__ == "__main__":
    uvicorn.run(app.build(), host="0.0.0.0", port=9999)
```

### Calling an A2A agent

```python
# client.py — call a remote A2A agent
import asyncio
from a2a.client import A2AClient
import httpx

async def main():
    async with httpx.AsyncClient() as http_client:
        client = await A2AClient.get_client_from_agent_card_url(
            http_client,
            "http://localhost:9999/.well-known/agent.json",
        )

        response = await client.send_message(
            message={"role": "user", "content": [{"type": "text", "text": "What is the capital of France?"}]}
        )
        print(response.result.content)

asyncio.run(main())
```

### AgentOS A2A interface

`AgentOS` exposes a built-in A2A server at `/a2a/`:

```python
from agno.os import AgentOS

app = AgentOS(
    agents=[my_agent],
    a2a=True,   # enable A2A protocol endpoint
).get_app()

# Any A2A client can now call: http://localhost:7777/a2a/
```

---

## MCP (Model Context Protocol)

**Files:** `libs/agno/agno/tools/mcp/mcp.py` · `libs/agno/agno/tools/mcp/multi_mcp.py` · `libs/agno/agno/os/mcp.py`
**Cookbook:** `cookbook/05_agent_os/mcp_demo/` · `cookbook/91_tools/mcp/`

MCP is a standard protocol for connecting LLM applications to external tool servers. Agno supports it in **both directions**:

| Role | Description |
|------|-------------|
| **MCP Client** | Agno agents consume tools from external MCP servers |
| **MCP Server** | AgentOS exposes Agno agents as an MCP server for Claude Desktop, Cursor, etc. |

---

### Agno as MCP client — `MCPTools`

Connect to a single MCP server and use its tools in an agent.

#### stdio transport (local process)

```python
import asyncio
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools

async def main():
    # Start an MCP server as a subprocess
    async with MCPTools("npx -y @modelcontextprotocol/server-filesystem /tmp") as mcp:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[mcp],
            show_tool_calls=True,
        )
        await agent.aprint_response("List all files in /tmp")

asyncio.run(main())
```

#### SSE transport (remote server)

```python
async with MCPTools(url="https://mcp.example.com/sse") as mcp:
    agent = Agent(model=OpenAIChat(id="gpt-4o"), tools=[mcp])
    await agent.aprint_response("What tools are available?")
```

#### Streamable HTTP transport

```python
async with MCPTools(
    url="https://mcp.example.com/mcp",
    transport="streamable-http",
    headers={"Authorization": "Bearer my-token"},
) as mcp:
    agent = Agent(model=OpenAIChat(id="gpt-4o"), tools=[mcp])
```

#### Tool filtering

Include or exclude specific tools from the MCP server:

```python
async with MCPTools(
    "npx -y @modelcontextprotocol/server-github",
    include_tools=["list_repos", "create_issue", "get_pull_request"],
    # exclude_tools=["delete_repo"],  # alternatively, exclude specific tools
) as mcp:
    agent = Agent(model=OpenAIChat(id="gpt-4o"), tools=[mcp])
```

#### `MCPTools` parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `command` | `str` | Shell command for stdio transport |
| `url` | `str` | Server URL for SSE/HTTP transport |
| `transport` | `str` | `"stdio"`, `"sse"`, `"streamable-http"` |
| `headers` | `dict` | Auth headers for HTTP transport |
| `include_tools` | `list[str]` | Only use these tools |
| `exclude_tools` | `list[str]` | Exclude these tools |
| `timeout` | `int` | Connection timeout in seconds |
| `refresh_on_run` | `bool` | Re-discover tools on each run |

---

### Multiple MCP servers — `MultiMCPTools`

Connect to several MCP servers simultaneously:

```python
from agno.tools.mcp import MultiMCPTools

async with MultiMCPTools(
    commands=[
        "npx -y @modelcontextprotocol/server-filesystem /workspace",
        "npx -y @modelcontextprotocol/server-github",
        "npx -y @modelcontextprotocol/server-postgres postgresql://localhost/mydb",
    ]
) as mcp:
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[mcp],
        instructions="You can read files, interact with GitHub, and query the database.",
    )
    await agent.aprint_response(
        "Find all Python files in /workspace that make database queries, "
        "then create a GitHub issue listing them."
    )
```

---

### MCP Toolbox for Databases

**File:** `libs/agno/agno/tools/mcp_toolbox.py`

The MCP Toolbox provides structured database access with predefined toolsets:

```python
from agno.tools.mcp_toolbox import MCPToolbox

toolbox = MCPToolbox(
    url="http://localhost:5000",
    toolset_name="hotel_toolset",   # predefined set of DB operations
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[toolbox],
)
agent.print_response("Show me all available rooms for next weekend")
```

---

### Agno as MCP server

**File:** `libs/agno/agno/os/mcp.py`

`AgentOS` can expose Agno agents as an MCP server using `FastMCP`. Any MCP client (Claude Desktop, Cursor IDE, etc.) can then call your Agno agents as tools.

```python
from agno.os import AgentOS

app = AgentOS(
    agents=[customer_support_agent, data_analyst_agent],
    mcp=True,           # expose agents as MCP tools
    mcp_port=8765,      # MCP server port
).get_app()
```

Claude Desktop configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "my-agno-agents": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8765/mcp"]
    }
  }
}
```

Exposed MCP tools:
- `run_agent_{agent_id}` — run a specific agent
- `stream_agent_{agent_id}` — stream agent response
- `get_agent_sessions` — list sessions
- `search_memory` — query agent memory
- `search_knowledge` — query agent knowledge

---

### Common MCP server examples

```python
# File system
async with MCPTools("npx -y @modelcontextprotocol/server-filesystem /workspace") as mcp: ...

# GitHub
async with MCPTools("npx -y @modelcontextprotocol/server-github") as mcp: ...

# PostgreSQL
async with MCPTools("npx -y @modelcontextprotocol/server-postgres postgresql://...") as mcp: ...

# SQLite
async with MCPTools("npx -y @modelcontextprotocol/server-sqlite ./my.db") as mcp: ...

# Brave Search
async with MCPTools("npx -y @modelcontextprotocol/server-brave-search") as mcp: ...

# Google Maps
async with MCPTools("npx -y @modelcontextprotocol/server-google-maps") as mcp: ...

# Slack
async with MCPTools("npx -y @modelcontextprotocol/server-slack") as mcp: ...

# Any custom MCP server
async with MCPTools("python my_mcp_server.py") as mcp: ...
```

---

## A2A vs MCP — when to use which

| Scenario | Use |
|----------|-----|
| Call another Agno agent (or any A2A-compatible agent) as a service | **A2A** |
| Give your agent access to external tools (files, databases, APIs) | **MCP Client** |
| Allow Claude Desktop or Cursor to use your agents | **MCP Server** |
| Build a network of specialised agents that call each other | **A2A** |
| Access GitHub, PostgreSQL, or Slack via a standard tool server | **MCP Client** |
