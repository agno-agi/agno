# Test Log — mcp_demo/

### enable_mcp_example.py

**Status:** PASS

**Description:** AgentOS with `enable_mcp_server=True` to expose an MCP endpoint at `/mcp`. Uses Claude model and WebSearchTools.

**Result:** Imports OK. AgentOS app with MCP server constructed. Requires `fastmcp` package.

---

### mcp_tools_example.py

**Status:** PASS

**Description:** Agent with MCPTools connected to an external MCP server (streamable-http transport). AgentOS manages MCPTools lifespan internally.

**Result:** Imports OK. MCPTools configured. AgentOS app constructed.

---

### mcp_tools_advanced_example.py

**Status:** SKIP

**Description:** Agent with multiple MCPTools (Agno docs MCP + Brave Search MCP). Demonstrates both streamable-http and stdio transports.

**Result:** Pydantic validation error: `BRAVE_API_KEY` env var is None, which StdioServerParameters rejects. Needs BRAVE_API_KEY set.

---

### mcp_tools_existing_lifespan.py

**Status:** PASS

**Description:** Same as mcp_tools_example but with a custom `lifespan` context manager passed to AgentOS. Shows how to run setup/teardown alongside MCP lifespan.

**Result:** Imports OK. Custom lifespan registered. AgentOS app constructed.

---

### test_client.py

**Status:** SKIP

**Description:** Client that connects to an MCP-enabled AgentOS instance. Requires the server (enable_mcp_example.py) to be running first.

**Result:** Syntax and imports validated. Runtime requires running server at localhost:7777/mcp.

---

### dynamic_headers/server.py

**Status:** PASS

**Description:** FastMCP server that logs headers received from clients. Uses `get_http_request()` to access custom headers.

**Result:** Imports OK. FastMCP server configured.

---

### dynamic_headers/client.py

**Status:** PASS

**Description:** AgentOS with MCPTools using `header_provider` to dynamically generate headers from RunContext. Shows user_id, session_id, agent/team names forwarded to MCP server.

**Result:** Imports OK. Header provider configured. AgentOS app constructed with agent and team.

---
