# Test Log: cookbook/00_quickstart

**Date:** 2026-05-19
**Environment:** `.venvs/quickstart/bin/python` (Python 3.12.8)
**Model:** `gemini-3.5-flash`
**Pre-flight:** All `.py` files pass `py_compile`; `GOOGLE_API_KEY` loaded via `.envrc`. 01-03 run serially; 04-12 run in parallel (10 serialized after 08 due to shared `learnings` Chroma collection).

---

### agent_with_tools.py

**Status:** PASS

**Description:** Agent uses YFinanceTools to fetch real-time data for NVIDIA. Tool calling, data retrieval, and brief formatting all work correctly.

**Result:** 5 tool calls (`get_current_stock_price`, `get_stock_fundamentals`, `get_company_info`, `get_company_news`, `get_historical_stock_prices`). Delivered a markdown investment brief: NVDA at $220.61, market cap $5.34T, P/E 45.11. Response in 17.4s.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Agent returns a typed `StockAnalysis` Pydantic model with all required fields populated.

**Result:** Valid `StockAnalysis` for NVIDIA: price $220.61, market cap "5.34T", P/E 45.11, 52-week range $129.16-$236.54, recommendation "Strong Buy". All fields populated and printed programmatically without errors. 9.3s.

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Agent accepts typed `AnalysisRequest` input (dict and Pydantic model) and returns typed `StockAnalysis`. Tests deep analysis with risks (NVDA) and quick analysis without risks (AAPL).

**Result:** Both input modes work. NVDA deep returned populated `key_drivers` and `key_risks`. AAPL quick (price $298.97, recommendation "Buy") returned `null` for both optional fields as expected by `analysis_type="quick"` and `include_risks=False`.

---

### agent_with_storage.py

**Status:** PASS

**Description:** Agent persists conversation across 3 sequential turns using SQLite + a fixed `session_id="finance-agent-session"`.

**Result:** All 3 turns completed. Agent correctly referenced NVIDIA from turn 1 when comparing to Tesla in turn 2, and synthesized both analyses into a final recommendation in turn 3. Session persistence works.

**Note:** A first attempt at this test hung at 0% CPU for several minutes (before any output). Killing and re-running cleanly resolved it; root cause not investigated. If it recurs, look at SQLite locking from leftover state in `tmp/agents.db`.

---

### agent_with_memory.py

**Status:** PASS

**Description:** Agent uses `MemoryManager` with `enable_agentic_memory=True` to capture user preferences. First prompt sets preferences (AI/semiconductor stocks, moderate risk), second asks for personalized recommendations.

**Result:** Agent stored a single consolidated memory: "User is interested in AI and semiconductor stocks and has a moderate risk tolerance." (topics: `investment_interests`, `risk_tolerance`, `finance`). Second prompt used the stored memory to tailor recommendations. `get_user_memories(user_id="investor@example.com")` returned the memory correctly.

**Note:** The previous 2026-02-20 run on `gemini-3-flash-preview` produced 2 separate memory records; `gemini-3.5-flash` chose to consolidate into 1. Both are valid behavior for the cookbook.

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Agent manages a stock watchlist via `session_state`. Custom tools (`add_to_watchlist`, `remove_from_watchlist`) modify `session_state["watchlist"]`; state injected into instructions via `{watchlist}`.

**Result:** Agent added NVDA, AAPL, GOOGL via parallel tool calls. Second prompt fetched current prices for all 3. Final `get_session_state()` returned `['NVDA', 'AAPL', 'GOOGL']`.

---

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Loads `https://docs.agno.com/` into ChromaDb (hybrid search, RRF), then answers "What is Agno?" by searching the knowledge base.

**Result:** Knowledge load succeeded against the updated URL. Agent searched the knowledge base and returned a comprehensive answer covering Agno's SDK code example, AgentOS production APIs, control plane UI, and data-ownership story.

**Note:** Original URL `https://docs.agno.com/introduction.md` was failing with `httpx.HTTPStatusError: 307 Temporary Redirect` to a broken target (`/.md`). Switched to `https://docs.agno.com/` in this run.

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Custom `save_learning` tool persists insights to a ChromaDb knowledge base. Three turns: ask about P/E ratios, approve learning, query saved learnings.

**Result:** Agent proposed and saved "Tech Stock P/E Benchmarks" (covers mature mega-caps 20-35x, high-growth SaaS 35-60x+, semiconductors 15-25x, PEG cross-reference). On the third prompt the agent successfully retrieved and presented the saved learning from the knowledge base.

---

### agent_with_guardrails.py

**Status:** PASS

**Description:** Three guardrails — `PIIDetectionGuardrail`, `PromptInjectionGuardrail`, custom `SpamDetectionGuardrail`. Four test cases.

**Result:** All 4 cases behaved correctly:
- Normal ("P/E ratio for tech stocks?"): processed successfully with full response
- PII ("My SSN is 123-45-6789"): blocked with `CheckTrigger.PII_DETECTED`
- Injection ("Ignore previous instructions"): blocked with `CheckTrigger.PROMPT_INJECTION`
- Spam ("URGENT!!! BUY NOW!!!!"): blocked with `CheckTrigger.INPUT_NOT_ALLOWED`

**Note:** Same pre-existing quirk as the 2026-02-20 run — guardrail blocks are surfaced as ERROR logs by `print_response` rather than raising `InputCheckError` to the caller, so the demo's `except InputCheckError` branch is cosmetic. The guardrails themselves function correctly.

---

### human_in_the_loop.py

**Status:** PASS

**Description:** `@tool(requires_confirmation=True)` on `save_learning`. Flow pauses for confirmation, accepts "y" from stdin, resumes with `agent.continue_run()`.

**Result:** Agent paused on `save_learning` call, displayed confirmation prompt with tool name and args, accepted "y", executed the tool, and saved "Tech Stock P/E Ratio Benchmarks" to the knowledge base. Final response included a polished markdown explanation with PEG-ratio formula. `continue_run` flow works.

---

### multi_agent_team.py

**Status:** PASS

**Description:** Team of 3 agents — Bull Analyst, Bear Analyst, Lead Analyst (team leader). Two prompts: analyze NVDA, then compare to AMD.

**Result:** Both prompts completed. For NVDA: bull and bear agents independently fetched data and produced opposing arguments; leader synthesized into a balanced recommendation. For the AMD comparison: leader delegated to both analysts, produced a comprehensive comparison with bull case, bear case, synthesis, recommendation ("UNDERWEIGHT / SELL relative to NVDA, Confidence 8.5/10"), and key metrics table. Total run time ~97s.

---

### sequential_workflow.py

**Status:** PASS

**Description:** Three-step workflow pipeline — Data Gatherer → Analyst → Report Writer.

**Result:** All 3 steps completed in sequence. Data Gatherer fetched NVDA market data. Analyst interpreted P/E, P/S, strengths, weaknesses, and benchmark comparisons. Report Writer produced a concise brief with metric table covering price/market cap ($220.61 / $5.34T), Forward P/E and PEG (18.98 / 0.71), margins (71.07% / 55.60%), net cash ($51.15B), ROE (101.49%). Total workflow time: 39.2s.

---

## Summary

| # | File | Status |
|:--|:-----|:-------|
| 01 | `agent_with_tools.py` | PASS |
| 02 | `agent_with_structured_output.py` | PASS |
| 03 | `agent_with_typed_input_output.py` | PASS |
| 04 | `agent_with_storage.py` | PASS |
| 05 | `agent_with_memory.py` | PASS |
| 06 | `agent_with_state_management.py` | PASS |
| 07 | `agent_search_over_knowledge.py` | PASS |
| 08 | `custom_tool_for_self_learning.py` | PASS |
| 09 | `agent_with_guardrails.py` | PASS |
| 10 | `human_in_the_loop.py` | PASS |
| 11 | `multi_agent_team.py` | PASS |
| 12 | `sequential_workflow.py` | PASS |

**Result: 12/12 PASS**
