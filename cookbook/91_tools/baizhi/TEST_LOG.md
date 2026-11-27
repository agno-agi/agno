# Baizhi cookbook verification

## 2026-09-20

### research.py --inspect

**Status:** PASS

**Description:** Ran the cookbook in its separate `.venvs/demo` environment with a synthetic Baizhi key. No model or MCP request was made.

**Result:** Only `websearch_search` was exposed, with query, bounded result count, freshness, summary, and domain-list parameters. The API key is not part of the function schema.

### research.py --inspect --async

**Status:** PASS

**Description:** Repeated schema inspection using Agno's async function registry.

**Result:** Same single-tool surface and schema as sync mode; no model or MCP request.

### Native toolkit, SDK and Agno approval execution

**Status:** PASS

**Description:** `libs/agno/tests/unit/tools/test_baizhi.py` covers sync and async functions using the real MCP 2.2.0 SDK against an in-memory HTTP transport. The real `Agent.run` / `Agent.arun` and continuation paths run with a local model double.

**Result:** 62 tests passed. Both agents pause before any MCP request, then make exactly one tool call after confirmation. Also covers current server schemas, domain/field mapping, disabled tools, malformed inputs, credential isolation and redaction, credential-bearing page URL rejection, bare-domain/IP validation, same-origin and cross-origin redirect containment, structured results, HTTP failures, timeout and cancellation. Malformed JSON and SSE responses reproduced key-bearing SDK exception traces before the fix; the passing regressions confirm task-scoped SDK log redaction while preserving unrelated task diagnostics and post-call logging. This is a local protocol/host test, not a live service test or a test of OpenAI model behavior.

### Broader repository checks

**Status:** PASS (format, validation and related MCP tests); full unit suite not completed.

**Description:** Ran repository `scripts/format.sh`, `scripts/validate.sh`, and the native-tool/MCP regression selection. Formatting an unrelated pre-existing Elasticsearch test was reverted from this contribution.

**Result:** Ruff, mypy and cookbook pattern checks passed. The final related selection passed 186 tests (62 Baizhi plus 124 existing MCP tests). `scripts/test.sh` collected 16,433 tests but stopped with 124 missing optional-provider dependency errors and 30 skips in the documented dev environment; that run is not reported as a passing full suite.

### Live agent run

**Status:** NOT RUN

**Description:** A real model-backed interactive cookbook run would require model credentials and user-approved billable service calls.

**Result:** No real Baizhi key or model credential was used by these local checks. Current tool definitions were supplied from separate authenticated discovery, which made zero tool calls; that is not proof of successful production execution.
