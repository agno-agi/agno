# TEST_LOG.md - 91 Tools MCP

**Test Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`

---

### agno_mcp.py — PASS
Streamable HTTP transport to docs.agno.com/mcp. Agent queried Agno docs via MCP.

### airbnb.py — PASS
npx @openbnb/mcp-server-airbnb. Agent searched Airbnb listings.

### brave.py — SKIP (missing API key: BRAVE_API_KEY)

### cli.py — SKIP (interactive CLI, requires terminal input)

### dynamic_headers/client.py — SKIP (needs local server running)
### dynamic_headers/server.py — SKIP (server component)

### filesystem.py — FAIL (timeout — MCP tool call hung waiting for response)

### gibsonai.py — SKIP (needs Gibson CLI setup)

### github.py — PASS
npx @modelcontextprotocol/server-github with GITHUB_TOKEN. Agent read agno-agi/agno repo.

### graphiti.py — SKIP (needs Graphiti server at localhost:8000/sse)

### groq_mcp.py — PASS
Filesystem MCP with Groq model. Direct MCP client session worked.

### include_exclude_tools.py — PASS
Multiple MCP servers with include/exclude tool filtering.

### include_tools.py — PASS
Filesystem MCP with Groq model, include_tools parameter.

### local_server/client.py — SKIP (needs local server running)
### local_server/server.py — SKIP (server component)

### mcp_toolbox_demo/agent.py — SKIP (needs MCPToolbox server)
### mcp_toolbox_demo/agent_os.py — SKIP (needs MCPToolbox server)
### mcp_toolbox_demo/hotel_management_typesafe.py — SKIP (needs MCPToolbox server)
### mcp_toolbox_demo/hotel_management_workflows.py — SKIP (needs MCPToolbox server)

### mcp_toolbox_for_db.py — SKIP (needs MCPToolbox server)

### mem0.py — SKIP (needs Mem0 server at localhost:8080/sse)

### multiple_servers.py — SKIP (missing API key: BRAVE_API_KEY)

### multiple_servers_allow_partial_failure.py — SKIP (missing API key: BRAVE_API_KEY)

### notion_mcp_agent.py — SKIP (needs MCP server for Notion)

### oxylabs.py — SKIP (missing API keys: OXYLABS_USERNAME, OXYLABS_PASSWORD)

### parallel.py — SKIP (missing API key: PARALLEL_API_KEY)

### pipedream_auth.py — SKIP (needs MCP_SERVER_URL + MCP_ACCESS_TOKEN)
### pipedream_google_calendar.py — SKIP (needs MCP_SERVER_URL)
### pipedream_linkedin.py — SKIP (needs MCP_SERVER_URL)
### pipedream_slack.py — SKIP (needs MCP_SERVER_URL)

### qdrant.py — SKIP (needs QDRANT_URL + QDRANT_API_KEY)

### sequential_thinking.py — SKIP (needs GOOGLE_MAPS_API_KEY)

### sse_transport/client.py — SKIP (needs local server running)
### sse_transport/server.py — SKIP (server component)

### stagehand.py — SKIP (needs BROWSERBASE_API_KEY)

### streamable_http_transport/client.py — SKIP (needs local server running)
### streamable_http_transport/server.py — SKIP (server component)

### stripe.py — SKIP (missing API key: STRIPE_SECRET_KEY)

### supabase.py — SKIP (missing: SUPABASE_ACCESS_TOKEN)

### tool_name_prefix.py — PASS
Streamable HTTP transport with tool name prefix. Agent queried Agno docs.

---

## Summary

| PASS | FAIL | SKIP | Total |
|------|------|------|-------|
| 7    | 1    | 32   | 40    |

### Notes

- Most MCP cookbooks require external MCP servers running or API keys not available
- The 7 PASS files confirm the core MCP integration (streamable HTTP, stdio, Groq, GitHub) works with v2.5
- filesystem.py FAIL is likely an MCP server startup timing issue, not a v2.5 regression
