# TEST_LOG.md - Quick Start Cookbook

Test results for `cookbook/00_quickstart/` cookbooks.

**Test Date:** 2026-02-07  
**Environment:** `direnv exec . .venvs/demo/bin/python`  
**Model:** Gemini (`gemini-3-flash-preview`)

---

## Summary

| Phase | Test | Status |
|:------|:-----|:-------|
| Phase 1: Basic | agent_with_tools.py | PASS |
| Phase 1: Basic | agent_with_structured_output.py | PASS |
| Phase 1: Basic | agent_with_typed_input_output.py | PASS |
| Phase 2: Persistence | agent_with_storage.py | PASS |
| Phase 2: Persistence | agent_with_memory.py | PASS |
| Phase 2: Persistence | agent_with_state_management.py | PASS |
| Phase 3: Knowledge | agent_search_over_knowledge.py | PASS |
| Phase 3: Knowledge | custom_tool_for_self_learning.py | PASS |
| Phase 4: Safety | agent_with_guardrails.py | PASS |
| Phase 4: Safety | human_in_the_loop.py | PASS |
| Phase 5: Multi-Agent | multi_agent_team.py | PASS |
| Phase 5: Multi-Agent | sequential_workflow.py | PASS |
| Phase 6: AgentOS | run.py | PASS (startup validated) |

**Overall: 13 PASS**

---

## Structure Validation

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Verified cookbook Python structure against `cookbook/STYLE_GUIDE.md` rules.

**Result:** Ran `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart` and got `Violations: 0`.

---

## Phase 1: Basic

### agent_with_tools.py

**Status:** PASS

**Description:** Finance agent with YFinance tools for live market analysis.

**Result:** Agent called finance tools and produced an investment brief for NVDA, including valuation, drivers, risks, and recommendation.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Agent returning typed `StockAnalysis` output schema.

**Result:** Run completed with structured analysis output populated with expected fields (ticker/company/price/summary/drivers/risks/recommendation).

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Agent with both typed input schema and typed output schema.

**Result:** Completed both example analyses (`NVDA` and `AAPL`) and returned typed outputs with valid recommendations.

---

## Phase 2: Persistence

### agent_with_storage.py

**Status:** PASS

**Description:** Agent session persistence via SQLite storage.

**Result:** Multi-turn session completed and preserved conversational context across follow-up prompts within the same `session_id`.

---

### agent_with_memory.py

**Status:** PASS

**Description:** Agent memory extraction and retrieval with `MemoryManager`.

**Result:** Captured user preference/risk memories and successfully retrieved saved memories for `investor@example.com`.

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Agent-managed session state using custom watchlist tools.

**Result:** Added symbols to watchlist, reported performance, and showed persisted state with `['NVDA', 'AAPL', 'GOOGL']`.

---

## Phase 3: Knowledge

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Agentic knowledge-base search with Chroma hybrid retrieval.

**Result:** Inserted Agno documentation URL into KB and answered "What is Agno?" using retrieved knowledge.

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Self-learning agent with custom `save_learning` tool.

**Result:** Saved a reusable valuation learning and later retrieved it from the knowledge base.

---

## Phase 4: Safety

### agent_with_guardrails.py

**Status:** PASS

**Description:** Built-in and custom guardrails (PII, prompt injection, spam).

**Result:** Normal prompt processed; PII, injection, and spam prompts were blocked as expected by guardrails.

---

### human_in_the_loop.py

**Status:** PASS

**Description:** Confirmation-required tool flow with manual approval checkpoint.

**Result:** Confirmation prompt appeared for `save_learning`; automated test approved (`y`) and run resumed via `continue_run`, then saved the learning.

---

## Phase 5: Multi-Agent

### multi_agent_team.py

**Status:** PASS

**Description:** Team collaboration between bull analyst, bear analyst, and lead analyst.

**Result:** Team delegated analysis, synthesized opposing views, and handled follow-up comparison (`AMD`) successfully.

---

### sequential_workflow.py

**Status:** PASS

**Description:** Three-step workflow (Data Gathering -> Analysis -> Report Writing).

**Result:** All three steps completed in order with final report output; run completed in ~33s.

---

## Phase 6: AgentOS

### run.py

**Status:** PASS (startup validated)

**Description:** AgentOS server bootstrap for all quickstart agents/teams/workflows.

**Result:** Server started successfully (`Uvicorn running on http://localhost:7777`, `Application startup complete`). Process was intentionally timeout-stopped after startup validation.

---

## Notes

1. Test logs captured in `.context/quickstart_run_20260207_195859/`.
2. `run.py` is long-running by design; startup-only validation was performed.
3. Output and metrics vary by market data/API responses and run time.
