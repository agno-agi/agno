# Test Log

### magic_hour.py

**Status:** PASS

**Description:** Connects to Magic Hour's production Streamable HTTP MCP endpoint through Agno's `MCPTools` with bearer authentication and discovers the available media-generation and project workflow tools. The check uses an invalid test token so it cannot create a billable project.

**Result:** MCP initialization completed, Agno discovered 44 tools, and `ping` returned `pong`. The authenticated `account_retrieve` tool rejected the invalid token with HTTP 401, so the check could not create a billable project. The example also passes Python compilation, Ruff formatting, and Ruff lint checks. A paid end-to-end generation remains intentionally untested until a reviewer credential is provided securely.

---

### peer_cash.py

**Status:** PASS

**Description:** Uses Agno 2.9.0 `MCPTools` to launch `peer-cash-mcp@0.1.2` over stdio with the same command as the cookbook, completes MCP initialization, and calls the live production capabilities tool.

**Result:** Agno discovered all nine tools and `peer_cash_capabilities` returned the Base 8453 USDC destination plus the live payout catalog. A regression check also parsed all nine MCP tools with the cookbook's structured output enabled and confirmed that `peer_cash_prepare` is no longer marked strict, avoiding OpenAI's incompatible strict-schema rewrite. The example passes Python compilation and Ruff checks.

---

### structured_content.py

**Status:** PASS

**Description:** Connects to the hosted DeepWiki MCP server (public, no auth) and asks
about facebook/react. Verifies the agent answers from the tool's `structuredContent`
and that `structured_content_hook` reads the typed object from
`ToolResult.metadata["structured_content"]`.

**Result:** `ask_question` returned successfully (with `timeout_seconds=60` for DeepWiki's
slower analysis), the hook printed the `structured_content` payload read from metadata, and
the agent produced a grounded one-sentence answer about the repository.

---

### Pending

**Status:** NOT RUN

**Description:** Tests for this cookbook directory have not been executed yet in this workspace.

**Result:** Add individual run results after executing examples.

---
