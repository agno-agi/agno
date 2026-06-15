# Test Log: mcp_demo

> Tests not yet run. Run each file and update this log.

### enable_mcp_example.py

**Status:** PENDING

**Description:** Example AgentOS app with MCP enabled.

---

### custom_mcp_tool_example.py

**Status:** PASS

**Description:** AgentOS exposing a single owner-only custom MCP tool (`ask_workspace`) routed
through an agent: built-ins disabled via `MCPServerConfig(enable_builtin_tools=False)`, `user_id`
injected into the tool (hidden from the client schema), and an `authorize` owner-gate.

**Result:** App builds successfully; the MCP server at `/mcp` exposes only `ask_workspace`, the
`user_id` arg is not in the client-facing schema, and the authorize middleware is wired (verified
with an in-memory FastMCP client). A live model call requires `OPENAI_API_KEY`.

---

### mcp_tools_advanced_example.py

**Status:** PENDING

**Description:** Example AgentOS app where the agent has MCPTools.

---

### mcp_tools_example.py

**Status:** PENDING

**Description:** Example AgentOS app where the agent has MCPTools.

---

### mcp_tools_existing_lifespan.py

**Status:** PENDING

**Description:** Example AgentOS app where the agent has MCPTools.

---

### test_client.py

**Status:** PENDING

**Description:** First run the AgentOS with enable_mcp=True.

---
