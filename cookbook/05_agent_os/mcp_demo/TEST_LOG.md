# Test Log: mcp_demo

### enable_mcp_example.py

**Status:** PASS (2026-07-04, v2.7 8-tool surface)

**Description:** Example AgentOS app with MCP enabled, tested live end-to-end with a
Streamable HTTP FastMCP client against the served app.

**Result:** Server boots with the MCP lifespan; `GET /` returns 200 JSON (home route now
coexists with the root MCP mount). `tools/list` returns exactly the 8 built-in tools with
read-only/destructive annotations on the wire. `get_agentos_config` payload is ~400 chars.
`get_sessions` works without `db_id` (single-db default) through the sync-sqlite threadpool
path. `run_agent` executed a live Claude run: trimmed result was 158 chars total (answer +
run_id/session_id/status), no transcript/system-prompt leakage, and the client received a
progress notification. `get_session_runs` with auto-detected session type read the
conversation back. Bonus check: running without `ANTHROPIC_API_KEY` surfaced the real
provider auth error through the MCP tool error (error propagation fix).

---

### custom_mcp_tool_example.py

**Status:** PASS

**Description:** AgentOS exposing a single owner-only custom MCP tool (`ask_workspace`) routed
through an agent: built-ins disabled via `MCPServerConfig(enable_builtin_tools=False)`, `user_id`
injected into the tool (hidden from the client schema), an `authorize` owner-gate, and built-in
DNS-rebinding protection via `allowed_hosts` — no hand-written middleware classes.

**Result:** App builds successfully; the MCP server at `/mcp` exposes only `ask_workspace`, the
`user_id` arg is not in the client-facing schema, and both the transport-security and authorize
middlewares are wired (verified with an in-memory FastMCP client). A live model call requires
`OPENAI_API_KEY`.

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

**Status:** PASS (2026-07-04, updated)

**Description:** Agent operating the AgentOS over MCP (OpenAIResponses/gpt-5.5, per repo
model rules; stale docstring path and `enable_mcp` flag name fixed).

**Result:** The equivalent client flow (list tools → get_agentos_config → run_agent →
get_session_runs) was exercised end-to-end against the live server with a raw FastMCP
client and passed. The agent-driven variant in this file additionally requires
`OPENAI_API_KEY` for the operator model and was not run in this pass.

---
