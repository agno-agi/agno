# Dynamic Headers Cookbook

Examples for `mcp_demo/dynamic_headers` in AgentOS.

## Files
- `client.py` — AgentOS with MCPTools using dynamic headers.
- `server.py` — Simple MCP server that logs headers received from clients.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
