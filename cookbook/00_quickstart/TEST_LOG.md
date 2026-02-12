# TEST_LOG.md - Quick Start Cookbook

Test results for `cookbook/00_quickstart/` examples.

**Test Date:** 2026-02-11 (v2.5 re-verification)
**Environment:** `.venvs/demo/bin/python` (Python 3.12)
**Model:** Gemini (agent_with_tools, knowledge, self-learning), OpenAI (all others)
**Database:** SQLite (`tmp/agents.db`), ChromaDB (`tmp/chromadb/`)
**Branch:** `cookbooks/v2.5-testing`

---

## Runtime Validation

### agent_with_tools.py

**Status:** PASS

**Description:** Finance Agent with YFinanceTools fetches real-time market data for NVIDIA.

**Result:** Exited `0`; produced investment brief with price ($191.78), market cap, P/E, 52-week range, key drivers, and risks.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Returns a typed `StockAnalysis` Pydantic model for NVIDIA via Gemini.

**Result:** Exited `0`; structured output with all fields: price, market cap, P/E, summary, key drivers (3), key risks (3), recommendation.

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Full type safety with `AnalysisRequest` input and `StockAnalysis` output schemas.

**Result:** Exited `0`; both dict input (NVDA) and Pydantic model input (AAPL) returned correctly typed responses.

---

### agent_with_storage.py

**Status:** PASS

**Description:** Finance Agent with SQLite storage persists conversation across three turns (NVDA analysis, TSLA comparison, portfolio advice).

**Result:** Exited `0`; completed three-turn conversation with correct cross-turn context retention.

---

### agent_with_memory.py

**Status:** PASS

**Description:** Agent with MemoryManager extracts and recalls user preferences (AI/semiconductor interests, moderate risk tolerance).

**Result:** Exited `0`; stored 2 memories, recalled them to personalize stock recommendations.

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Agent manages a stock watchlist via custom state-modifying tools (`add_to_watchlist`, `remove_from_watchlist`, `get_current_stock_price`).

**Result:** Exited `0`; watchlist state `['NVDA', 'AAPL', 'GOOGL']` managed correctly across 3 turns.

---

### agent_with_guardrails.py

**Status:** PASS

**Description:** Tests PII detection, prompt injection, and custom spam guardrails.

**Result:** Exited `0`; PII blocked (SSN detected), injection blocked (prompt injection detected), spam blocked (excessive exclamation), normal request processed.

---

### multi_agent_team.py

**Status:** PASS

**Description:** Bull/Bear analyst team with leader synthesis. NVIDIA and AMD comparative analysis.

**Result:** Exited `0`; both analysts provided independent perspectives with real data, leader synthesized balanced recommendation with metrics table.

---

### sequential_workflow.py

**Status:** PASS

**Description:** Three-step workflow: Data Gathering -> Analysis -> Report Writing for NVIDIA.

**Result:** Exited `0` in ~34s; all three steps completed with final investment report.

---

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Loads Agno docs into ChromaDB knowledge base with hybrid search (semantic + keyword).

**Result:** Exited `0`; knowledge base loaded and queried successfully. Agent answered questions about Agno SDK, AgentOS, and learning capabilities.

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Agent with custom `save_learning` tool saves insights to ChromaDB knowledge base.

**Result:** Exited `0`; 3 learnings saved (P/E valuation, benchmarks, org goal) and recalled correctly.

---

### human_in_the_loop.py

**Status:** SKIP

**Description:** Confirmation-required tool execution with `@tool(requires_confirmation=True)`.

**Result:** Requires interactive user input (Rich `Prompt.ask`). EOFError when run non-interactively.

---

### run.py

**Status:** PASS

**Description:** AgentOS server startup with all quickstart agents registered.

**Result:** Exited `0`; import + agent registration successful. Cosmetic tracing warning about `Agent._run` attribute (openinference compatibility with v2.5 rename).

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `agent_with_tools.py` | PASS | |
| `agent_with_structured_output.py` | PASS | |
| `agent_with_typed_input_output.py` | PASS | |
| `agent_with_storage.py` | PASS | |
| `agent_with_memory.py` | PASS | |
| `agent_with_state_management.py` | PASS | |
| `agent_with_guardrails.py` | PASS | |
| `multi_agent_team.py` | PASS | |
| `sequential_workflow.py` | PASS | |
| `agent_search_over_knowledge.py` | PASS | |
| `custom_tool_for_self_learning.py` | PASS | |
| `human_in_the_loop.py` | SKIP | Needs interactive input |
| `run.py` | PASS | |

**Overall:** 12 PASS, 0 FAIL, 1 SKIP
