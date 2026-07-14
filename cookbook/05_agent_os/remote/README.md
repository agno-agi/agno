# Remote Cookbook

Examples for `remote` in AgentOS.

## Files
- `01_remote_agent.py` — Examples demonstrating AgentOSRunner for remote execution.
- `02_remote_team.py` — Examples demonstrating AgentOSRunner for remote execution.
- `03_remote_agno_a2a_agent.py` — Example demonstrating how to connect to a remote Agno A2A agent.
- `04_remote_adk_agent.py` — Example demonstrating how to connect to a remote Google ADK agent.
- `05_agent_os_gateway.py` — Example showing how to use an AgentOS instance as a gateway to remote agents, teams and workflows.
- `adk_server.py` — Google ADK A2A Server for Cookbook Examples.
- `agno_a2a_server.py` — Agno A2A Server for Cookbook Examples.
- `server.py` — AgentOS Server for Cookbook Client Examples.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
