# Advanced Demo Cookbook

Examples for `advanced_demo` in AgentOS.

## Files
- `_agents.py` — Agents.
- `_teams.py` — Teams.
- `demo.py` — AgentOS Demo.
- `file_output.py` — File Output.
- `mcp_demo.py` — This example shows how to run an Agent using our MCP integration in the Agno OS.
- `multiple_knowledge_bases.py` — Multiple Knowledge Bases.
- `reasoning_demo.py` — Run `uv pip install openai exa_py ddgs yfinance pypdf sqlalchemy 'fastapi[standard]' youtube-transcript-api python-docx agno` to install dependencies.
- `reasoning_model.py` — Example showing a reasoning Agent in the AgentOS.
- `teams_demo.py` — Teams Demo.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
