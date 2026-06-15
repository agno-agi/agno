# Mcp Demo Cookbook

Examples for `mcp_demo` in AgentOS.

## Files
- `enable_mcp_example.py` — Example AgentOS app with MCP enabled.
- `custom_mcp_tool_example.py` — Expose ONE custom MCP tool routed through an agent, with the built-in tools disabled (uses `MCPServerConfig`).
- `mcp_tools_advanced_example.py` — Example AgentOS app where the agent has MCPTools.
- `mcp_tools_example.py` — Example AgentOS app where the agent has MCPTools.
- `mcp_tools_existing_lifespan.py` — Example AgentOS app where the agent has MCPTools.
- `test_client.py` — First run the AgentOS with enable_mcp=True.

## Customizing the MCP server

By default `enable_mcp_server=True` registers ~19 built-in tools (config, run_agent/team/workflow,
session CRUD, memory CRUD). Pass `mcp_config=MCPServerConfig(...)` to register your own tools, scope
the built-ins, gate the server, and protect it — all with data, no middleware classes to write:

```python
from agno.os import AgentOS
from agno.os.config import MCPServerConfig

agent_os = AgentOS(
    agents=[my_agent],
    enable_mcp_server=True,
    mcp_config=MCPServerConfig(
        tools=[my_tool],            # custom tools (plain callables or Agno @tool / Function)
        enable_builtin_tools=False,  # ship ONLY your tools; or scope with:
        # include_tags={"core"},     # keep only tools tagged "core"
        # exclude_tags={"memory"},   # drop the "memory" tools
        authorize=lambda user_id: user_id in OWNER_IDS,  # 401 non-owners before the model runs
        allowed_hosts=["my-app.example.com"],            # DNS-rebinding protection (localhost is automatic)
        # middleware=[Middleware(MyMiddleware)],          # escape hatch for anything else
    ),
)
```

Built-in tools are tagged `core` (config + run_*), `session`, and `memory`. With no `mcp_config`,
all built-ins are registered (unchanged behavior). Custom tools share the same `/mcp` mount,
lifespan, and JWT middleware as the built-ins.

**Identity in custom tools.** Declare a `user_id` parameter on a custom tool and AgentOS fills it
with the authenticated caller's id (the JWT subject), hidden from the client-facing schema so it
can't be spoofed. Tools that need the full request can declare a FastMCP `Context` parameter, which
FastMCP injects natively.

**Gating.** `authorize=fn(user_id) -> bool` runs after JWT verification and returns 401 before any
tool or model runs — use it for an owner-only or allow-listed server.

**Transport security.** `allowed_hosts=[...]` turns on built-in DNS-rebinding protection: the request
Host (and Origin, when present) is validated against your list plus localhost defaults, so an
always-on local server can't be driven by a malicious web page via a rebound DNS name. You list only
your deploy/tunnel host; localhost works out of the box. `allowed_origins=[...]` is an advanced extra.

**Escape hatch.** `middleware=[...]` takes `starlette.middleware.Middleware` instances for anything
the options above don't cover.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
