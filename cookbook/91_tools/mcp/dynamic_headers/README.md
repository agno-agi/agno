# Dynamic MCP Headers

This pair shows how an MCP client can derive request headers from Agno's
`RunContext`. The AgentOS app owns the `MCPTools` connection lifecycle, so the
tool client connects during application startup and closes cleanly during
shutdown.

## Files

| File | Description |
|---|---|
| `server.py` | Local FastMCP server that logs the identity headers it receives. |
| `client.py` | AgentOS app whose MCPTools header provider forwards run, user, session, tenant, and agent identity. |

## Prerequisites

- `OPENAI_API_KEY` for the model-backed run
- The demo environment, which includes `fastmcp`

## Run

Start the MCP server:

```bash
.venvs/demo/bin/python cookbook/91_tools/mcp/dynamic_headers/server.py
```

In another terminal, start AgentOS:

```bash
.venvs/demo/bin/python cookbook/91_tools/mcp/dynamic_headers/client.py
```

Then create a run:

```bash
curl -X POST http://localhost:7777/agents/dynamic-header-agent/runs \
  -F 'message=Use the greet tool to greet Ada.' \
  -F 'user_id=ada' \
  -F 'session_id=discord-demo' \
  -F 'stream=false'
```

The MCP server log shows the forwarded user and agent identity. A
`tenant_id` supplied through run metadata is also forwarded; without one, the
example uses `no-tenant`.
