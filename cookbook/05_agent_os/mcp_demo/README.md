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
session CRUD, memory CRUD). Pass `mcp_config=MCPServerConfig(...)` to register your own tools and/or
scope the built-ins:

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
    ),
)
```

Built-in tools are tagged `core` (config + run_*), `session`, and `memory`. With no `mcp_config`,
all built-ins are registered (unchanged behavior). Custom tools share the same `/mcp` mount,
lifespan, and JWT middleware as the built-ins.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
