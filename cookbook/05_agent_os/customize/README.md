# Customize Cookbook

Examples for `customize` in AgentOS.

## Files
- `custom_fastapi_app.py` — Example AgentOS app with a custom FastAPI app with basic routes.
- `custom_health_endpoint.py` — Example AgentOS app with a custom health endpoint.
- `custom_lifespan.py` — Example AgentOS app where the agent has a custom lifespan.
- `handle_custom_events.py` — Example for AgentOS to show how to generate custom events.
- `override_routes.py` — Example AgentOS app with a custom FastAPI app with conflicting routes.
- `pass_dependencies_to_agent.py` — Example for AgentOS to show how to pass dependencies to an agent.
- `update_from_lifespan.py` — Update From Lifespan.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
