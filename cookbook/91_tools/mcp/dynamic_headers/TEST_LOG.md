# Test Log: Dynamic MCP Headers

### server.py + client.py

**Status:** PASS (2026-07-24)

**Test mode:** CONSTRUCTION_SMOKE

**Description:** Started the sibling FastMCP server on an unused test port,
constructed the AgentOS client app against it, and entered the application
lifespan. Queried `GET /health` and `GET /config`, then exercised
`header_provider` with a concrete `RunContext`.

**Result:** `/health` returned 200. `/config` returned 200 and listed
`dynamic-header-agent`. AgentOS connected `MCPTools` during startup, discovered
the `greet` tool, and closed the MCP session during shutdown. The provider
produced the expected user, session, run, tenant, and agent headers. The
recursive cookbook pattern checker inspected both Python files with zero
violations. No OpenAI model call was attempted, so the final MCP tool request
was not exercised with a live `OPENAI_API_KEY`.

---
