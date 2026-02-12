# Client A2A Cookbook

Examples for `client_a2a` in AgentOS.

## Files
- `01_basic_messaging.py` — Basic A2A Messaging with A2AClient.
- `02_streaming.py` — Streaming A2A Messages with A2AClient.
- `03_multi_turn.py` — Multi-Turn Conversations with A2AClient.
- `04_error_handling.py` — Error Handling with A2AClient.
- `05_connect_to_google_adk.py` — Connect Agno A2AClient to Google ADK A2A Server.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
