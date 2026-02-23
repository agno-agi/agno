# Test Log: cookbook/00_quickstart

**Date:** 2026-02-20
**Environment:** `.venvs/demo/bin/python` (Python 3.12)
**Model:** `gemini-3-flash-preview`
**Pre-flight:** Structure checker 0 violations, all API keys set

---

### agent_with_tools.py

**Status:** PASS

**Description:** Agent uses YFinanceTools to fetch real-time stock data for NVIDIA. Tool calling works correctly, agent retrieves current price ($187.90) and produces a formatted investment brief with key drivers and risks.

**Result:** Agent called `get_current_stock_price(symbol=NVDA)`, received price data, and delivered a concise markdown-formatted brief in 15.3s.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Agent returns a typed `StockAnalysis` Pydantic model with all required fields populated. The structured output includes ticker, company name, price, market cap, P/E ratio, 52-week range, key drivers, key risks, and recommendation.

**Result:** Returned valid `StockAnalysis` object for NVIDIA: price $187.90, market cap 4.6T, P/E 45.5, recommendation "Buy". All fields populated correctly, printed programmatically without errors.

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Agent accepts typed `AnalysisRequest` input (as both dict and Pydantic model) and returns typed `StockAnalysis` output. Tests deep analysis with risks (NVDA) and quick analysis without risks (AAPL).

**Result:** Both input modes work correctly. NVDA deep analysis returned key_drivers and key_risks; AAPL quick analysis returned null for both optional fields as expected. Session history preserved across runs.

---

### agent_with_storage.py

**Status:** PASS

**Description:** Agent persists conversation history across multiple runs using SQLite storage and a fixed `session_id`. Three sequential prompts test: (1) initial analysis, (2) comparison referencing prior context, (3) recommendation based on full conversation.

**Result:** All 3 turns completed successfully. Agent correctly referenced NVIDIA from turn 1 when comparing to Tesla in turn 2, and synthesized both analyses in turn 3. Session persistence via `session_id="finance-agent-session"` works correctly.

---

### agent_with_memory.py

**Status:** PASS

**Description:** Agent uses MemoryManager with `enable_agentic_memory=True` to store user preferences. First prompt sets preferences (AI/semiconductor stocks, moderate risk), second prompt asks for personalized recommendations.

**Result:** Agent stored 2 memories via `add_memory` tool calls: (1) "User is interested in investing in AI and semiconductor stocks" (2) "User has a moderate risk tolerance for investments". Second prompt successfully used stored memories to tailor recommendations (MSFT, GOOGL, TSM, AVGO). `get_user_memories()` returned both memories correctly.

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Agent manages a stock watchlist via session state. Custom tools (`add_to_watchlist`, `remove_from_watchlist`) modify `session_state["watchlist"]`. State is injected into instructions via `{watchlist}` template.

**Result:** Agent added NVDA, AAPL, GOOGL to watchlist using parallel tool calls. Second prompt fetched current prices for all 3 watched stocks. Final `get_session_state()` confirmed watchlist state: `['NVDA', 'AAPL', 'GOOGL']`.

---

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Agent loads Agno documentation from URL into a ChromaDb knowledge base with hybrid search (RRF), then answers questions by searching the knowledge base.

**Result:** Successfully loaded `https://docs.agno.com/introduction.md` into ChromaDb. Agent searched knowledge base with `search_knowledge_base(query=Agno framework)`, found 1 document, and produced a comprehensive answer about Agno's three-layer architecture (SDK, Engine, AgentOS).

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Agent uses a custom `save_learning` tool to persist insights to a knowledge base. Three-turn flow: (1) ask about P/E ratios, (2) approve proposed learning, (3) query saved learnings.

**Result:** Agent proposed a learning about tech stock P/E benchmarks, saved it to ChromaDb after user approval, then successfully retrieved it via knowledge base search. All 3 turns completed correctly.

---

### agent_with_guardrails.py

**Status:** PASS

**Description:** Agent has three guardrails: PIIDetectionGuardrail, PromptInjectionGuardrail, and a custom SpamDetectionGuardrail. Four test cases validate normal input, PII detection, prompt injection detection, and spam detection.

**Result:** All 4 test cases behaved correctly:
- Normal ("P/E ratio for tech stocks?"): Processed successfully with full response
- PII ("My SSN is 123-45-6789"): Blocked with `CheckTrigger.PII_DETECTED`
- Injection ("Ignore previous instructions"): Blocked with `CheckTrigger.PROMPT_INJECTION`
- Spam ("URGENT!!! BUY NOW!!!!"): Blocked with `CheckTrigger.INPUT_NOT_ALLOWED`

**Note:** Guardrail blocks are handled internally by `print_response` (logged as ERROR, no response generated) rather than raising `InputCheckError` to the caller. The `except InputCheckError` path in the demo code does not fire. The guardrails function correctly but the error-handling demonstration is cosmetic only.

---

### human_in_the_loop.py

**Status:** PASS

**Description:** Agent uses `@tool(requires_confirmation=True)` on `save_learning` to require user approval before executing. The flow pauses for confirmation, then resumes with `agent.continue_run()`.

**Result:** Agent paused execution when `save_learning` was called, displayed confirmation prompt with tool name and args, accepted "y" input, executed the tool successfully, and saved "Healthy P/E Ratios for Tech Stocks" to the knowledge base. The `continue_run` flow works correctly.

---

### multi_agent_team.py

**Status:** PASS

**Description:** Team of 3 agents: Bull Analyst, Bear Analyst, and Lead Analyst (team leader). Two prompts: (1) analyze NVDA, (2) compare to AMD. Both analysts produce independent analyses, leader synthesizes.

**Result:** Both prompts completed successfully. For NVDA: bull/bear agents independently fetched data and produced opposing arguments, leader synthesized into balanced recommendation with metrics table. For AMD comparison: leader delegated to both analysts in parallel, produced comprehensive comparison with bull case, bear case, synthesis, recommendation, and metrics table. Total run time ~97s for the AMD comparison (expected given 3-agent coordination).

---

### sequential_workflow.py

**Status:** PASS

**Description:** Three-step workflow pipeline: Data Gatherer (fetches raw data) -> Analyst (interprets metrics) -> Report Writer (produces investment brief). Each step builds on the previous output.

**Result:** All 3 steps completed in sequence. Data Gatherer fetched NVDA price and market data. Analyst produced detailed interpretation of P/E (45-50x), P/S (30-35x), strengths, weaknesses, and benchmark comparisons. Report Writer synthesized into a concise "HOLD" recommendation with key metrics table. Total workflow time: 68.1s.

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
