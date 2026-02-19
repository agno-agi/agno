# TEST_LOG.md - Quick Start Cookbook

Test results for `cookbook/00_quickstart/` examples.

**Test Date:** 2026-02-10 (re-validated)
**Environment:** `.venvs/demo/bin/python` with `direnv` exports loaded
**Model:** `gemini-3-flash-preview` (Google Gemini)
**Database:** SQLite (`tmp/agents.db`) and ChromaDB (`tmp/chromadb/`)

---

## Structure Validation

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Validates cookbook structure and formatting pattern for quickstart examples.

**Result:** `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart` reported `Checked 13 file(s) ... Violations: 0`.

---

### style_guide_compliance_scan

**Status:** PASS

**Description:** Validates module docstring with `=====` underline, section banners, import placement, `if __name__ == "__main__":` gate, and no emoji characters.

**Result:** All 13 runnable files comply with `cookbook/STYLE_GUIDE.md`. No emoji characters found.

---

## Runtime Validation

### agent_with_tools.py

**Status:** PASS

**Description:** Finance Agent with YFinanceTools fetches real-time market data for NVIDIA.

**Result:** Exited `0`; produced investment brief with price ($190.04), market cap ($4.63T), P/E, 52-week range, key drivers, and risks.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Returns a typed `StockAnalysis` Pydantic model for NVIDIA.

**Result:** Exited `0`; structured output parsed correctly with all fields (ticker, company_name, current_price, market_cap, pe_ratio, 52-week range, key_drivers, key_risks, recommendation).

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Full type safety with `AnalysisRequest` input and `StockAnalysis` output schemas. Tests both dict and Pydantic model input.

**Result:** Exited `0`; both dict input (NVDA deep analysis) and Pydantic model input (AAPL quick analysis) returned correctly typed `StockAnalysis` responses.

---

### agent_with_storage.py

**Status:** PASS

**Description:** Finance Agent with SQLite storage persists conversation across three turns.

**Result:** Exited `0`; completed three-turn conversation (NVDA brief, TSLA comparison, investment recommendation). Agent correctly referenced prior turns.

---

### agent_with_memory.py

**Status:** PASS

**Description:** Agent with MemoryManager extracts and recalls user preferences.

**Result:** Exited `0`; agent stored two memories ("interested in AI and semiconductor stocks", "moderate risk tolerance") and used them to personalize stock recommendations.

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Agent manages a stock watchlist via custom state-modifying tools.

**Result:** Exited `0`; added NVDA, AAPL, GOOGL to watchlist, fetched prices for watched stocks, and confirmed session state `['NVDA', 'AAPL', 'GOOGL']`.

---

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Loads Agno introduction docs into ChromaDB knowledge base with hybrid search and answers questions.

**Result:** Exited `0`; loaded knowledge from `https://docs.agno.com/introduction.md`, searched and synthesized answer about Agno features and components.

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Agent with custom `save_learning` tool saves insights to a ChromaDB knowledge base and recalls them.

**Result:** Exited `0`; agent proposed and saved a learning about tech P/E benchmarks, then recalled it from the knowledge base.

---

### agent_with_guardrails.py

**Status:** PASS

**Description:** Tests PII detection, prompt injection, and custom spam guardrails.

**Result:** Exited `0`; four test cases executed: normal request processed, PII (SSN) blocked, prompt injection blocked, spam (excessive exclamation marks) blocked.

---

### human_in_the_loop.py

**Status:** PASS

**Description:** Confirmation-required tool execution with `@tool(requires_confirmation=True)`.

**Result:** Exited `0`; agent proposed saving a learning, confirmation was approved via stdin `y`, tool executed and saved the learning.

---

### multi_agent_team.py

**Status:** PASS

**Description:** Bull/Bear analyst team with leader synthesis for NVIDIA and AMD comparison.

**Result:** Exited `0`; both analysts provided independent perspectives, leader synthesized into balanced recommendation with comparison table.

---

### sequential_workflow.py

**Status:** PASS

**Description:** Three-step workflow: Data Gathering, Analysis, Report Writing for NVIDIA.

**Result:** Exited `0` in ~30.8s; all three steps completed, final report included recommendation (BUY), key metrics table, and rationale.

---

### run.py

**Status:** PASS

**Description:** Startup-only validation for long-running AgentOS server.

**Result:** Server started successfully on `http://localhost:7777` with all 10 agents, 1 team, and 1 workflow registered. Uvicorn startup complete. Process terminated cleanly after 15s.

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `agent_with_tools.py` | PASS | Produced NVDA investment brief with real market data |
| `agent_with_structured_output.py` | PASS | Typed `StockAnalysis` returned with all fields |
| `agent_with_typed_input_output.py` | PASS | Both dict and Pydantic model inputs handled correctly |
| `agent_with_storage.py` | PASS | Three-turn persisted conversation completed |
| `agent_with_memory.py` | PASS | Memories stored and recalled for personalization |
| `agent_with_state_management.py` | PASS | Watchlist state managed across turns |
| `agent_search_over_knowledge.py` | PASS | Knowledge loaded, hybrid search, and answer generated |
| `custom_tool_for_self_learning.py` | PASS | Custom tool saved and recalled learning |
| `agent_with_guardrails.py` | PASS | All 4 guardrail test cases passed (normal, PII, injection, spam) |
| `human_in_the_loop.py` | PASS | Confirmation flow exercised with stdin approval |
| `multi_agent_team.py` | PASS | Bull/Bear team collaboration completed |
| `sequential_workflow.py` | PASS | Three-step workflow completed in ~33.6s |
| `run.py` | PASS | AgentOS server startup validated |

**Overall:** 13 PASS, 0 FAIL
