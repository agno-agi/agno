# Middleware Cookbook

Examples for `middleware` in AgentOS.

## Files
- `agent_os_with_custom_middleware.py` — This example demonstrates how to add custom middleware to your AgentOS application.
- `agent_os_with_jwt_middleware.py` — This example demonstrates how to use our JWT middleware with AgentOS.
- `agent_os_with_jwt_middleware_cookies.py` — This example demonstrates how to use JWT middleware with cookies instead of Authorization headers.
- `custom_fastapi_app_with_jwt_middleware.py` — This example demonstrates how to use our JWT middleware with your custom FastAPI app.
- `extract_content_middleware.py` — Example for AgentOS to show how to extract content from a response and send it to a notification service.
- `guardrails_demo.py` — Example demonstrating how to use guardrails with an Agno Agent.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
