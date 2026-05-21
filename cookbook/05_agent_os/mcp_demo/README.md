# Mcp Demo Cookbook

Examples for `mcp_demo` in AgentOS.

## Files
- `enable_mcp_example.py` — Example AgentOS app with MCP enabled.
- `mcp_tools_advanced_example.py` — Example AgentOS app where the agent has MCPTools.
- `mcp_tools_example.py` — Example AgentOS app where the agent has MCPTools.
- `mcp_tools_existing_lifespan.py` — Example AgentOS app where the agent has MCPTools.
- `test_client.py` — First run the AgentOS with enable_mcp=True.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
