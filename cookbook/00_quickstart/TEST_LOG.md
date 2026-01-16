# TEST_LOG - 00_quickstart

**Test Date:** 2026-01-16
**Environment:** `.venvs/demo/bin/python`
**Branch:** `v2.4-with-cookbooks`

---

### agent_with_tools.py

**Status:** PASS

**Description:** Basic agent with yfinance tools for stock analysis. Agent successfully fetched NVDA data and produced a comprehensive market analysis with current price, market cap, P/E ratio, key drivers and risks.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Agent with Pydantic structured output. Successfully returned typed StockAnalysis object with ticker, price, summary, and recommendation fields.

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Full type safety with typed input and output schemas. Agent processed AAPL analysis request and returned properly typed response.

---

### agent_with_storage.py

**Status:** PASS

**Description:** Conversation persistence using SQLite. Agent maintained context across multiple queries comparing NVDA vs TSLA, demonstrating session storage working correctly.

---

### agent_with_memory.py

**Status:** PASS

**Description:** MemoryManager for user preferences. Agent successfully stored and retrieved user memory about interest in AI/semiconductor stocks with moderate risk tolerance.

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Session state management with watchlist feature. Agent maintained watchlist state ['NVDA', 'AAPL', 'GOOGL'] across interactions.

---

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** RAG search over knowledge base using ChromaDb. Agent successfully searched and retrieved information about Agno framework features and provided code examples.

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Custom tools with self-learning capability. Agent stored and retrieved learnings about tech valuations, P/E ratios, and PEG benchmarks.

---

### agent_with_guardrails.py

**Status:** PASS

**Description:** Input validation guardrails. Successfully blocked PII (SSN), prompt injection attempts, and spam detection. All guardrail checks triggered correctly.

---

### human_in_the_loop.py

**Status:** SKIPPED (Interactive)

**Description:** Requires user confirmation prompts. Cannot be automated - requires manual testing.

---

### multi_agent_team.py

**Status:** PASS

**Description:** Multi-agent team coordination. Research and Finance agents collaborated to produce comprehensive NVDA vs AMD comparison with market analysis.

---

### sequential_workflow.py

**Status:** PASS

**Description:** Workflow pipeline orchestration. Three-step workflow (research -> analysis -> report) completed in 32.7s with full NVDA investment recommendation.

---

## Summary

| Test | Status |
|:-----|:-------|
| agent_with_tools.py | PASS |
| agent_with_structured_output.py | PASS |
| agent_with_typed_input_output.py | PASS |
| agent_with_storage.py | PASS |
| agent_with_memory.py | PASS |
| agent_with_state_management.py | PASS |
| agent_search_over_knowledge.py | PASS |
| custom_tool_for_self_learning.py | PASS |
| agent_with_guardrails.py | PASS |
| human_in_the_loop.py | SKIPPED |
| multi_agent_team.py | PASS |
| sequential_workflow.py | PASS |

**Total:** 11 PASS, 1 SKIPPED
