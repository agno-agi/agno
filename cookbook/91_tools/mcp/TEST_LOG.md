# Test Log

### swarmmemo.py (2026-10-02)

**Status:** PASS (focused offline tests and public MCP smoke checks only)

**Description:** Tested at Agno revision `150a4e4123221e709151f6784717ca196f64f0ff`
with Python 3.12.14, MCP 2.2.0, and FastMCP 4.0.10.

**Result:** Six offline cookbook tests passed. They exercise Agno's real agent/tool
loop with a scripted model: explicit read-only tool discovery, a bounded search,
empty/error/untrusted result preservation, and cleanup after model failure or
cancellation. They do not prove real-model prompt-injection resistance or citation
accuracy. The MCP regression suites also passed (130 tests total):

```bash
.venv/bin/pytest -q libs/agno/tests/unit/tools/test_swarmmemo_cookbook.py \
  libs/agno/tests/unit/tools/test_mcp.py \
  libs/agno/tests/unit/tools/test_mcp_pagination.py
```

A live connection using the cookbook's `_mcp_tools()` registered exactly four
allowlisted tools. `find_work(kind="open", limit=3)` returned `ok=true`, zero
requests, and `has_more=false`. `read_thread(limit=1)` returned one public message.
Calling `read_work` and `read_work_history(limit=1)` on that non-work thread
returned `ok=false` / `not_found`, as expected. No work, identity, posting, signing,
inference, or payment mutation was performed. No model API was called.
The test host required the optional `socksio` dependency for its SOCKS proxy.

Changed Python files passed Ruff format/check and compilation; `git diff --check`
passed. `./scripts/format.sh` ran successfully; unrelated formatting changes were
excluded from this contribution.

**Repository-wide validation: FAIL.** `./scripts/validate.sh` found six mypy errors
in five untouched files: `agno/os/public/_limits.py:132`,
`agno/db/sql/authz.py:199,661`, `agno/db/sqlite/async_sqlite.py:2486`,
`agno/db/postgres/async_postgres.py:2197`, and
`agno/db/mysql/async_mysql.py:2097` (paths relative to `libs/agno`).
Other validation stages passed. The complete repository test suite was not run.

**Live model end-to-end: NOT RUN.** No OpenAI credential or spending authorization
was available. Successful work-detail/history reads could not be exercised with
an open request because discovery was empty. This does not establish merge or
bounty acceptance readiness.

---

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
