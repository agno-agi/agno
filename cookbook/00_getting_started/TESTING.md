# Getting Started Cookbook Testing Log

Testing all cookbooks in `cookbook/00_getting_started/` to verify they work as expected.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- API Key: `GOOGLE_API_KEY` (Gemini)
- Date: 2026-01-11

---

## Basic Agent Tests

### agent_with_tools.py

**Status:** PASS

**Description:** Basic agent with YFinanceTools for fetching stock data.

**Result:** Agent fetched NVIDIA stock data (price $184.86, market cap $4.50T, P/E 45.64) and provided comprehensive investment brief with key drivers, risks, and analyst sentiment.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Agent returns typed Pydantic objects.

**Result:** Agent returned structured StockAnalysis object with all typed fields (ticker, company_name, current_price, market_cap, pe_ratio, summary, key_drivers, key_risks, recommendation).

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Full type safety on input and output schemas.

**Result:** Agent accepted typed StockQuery input and returned typed StockAnalysis output for Apple (AAPL).

---

### agent_with_guardrails.py

**Status:** PASS

**Description:** Input validation with PII detection, prompt injection blocking, and custom spam detection.

**Result:**
- Normal query (P/E ratio): Processed successfully with detailed response
- PII (SSN 123-45-6789): BLOCKED - "Potential PII detected"
- Prompt injection ("Ignore previous instructions"): BLOCKED - "Potential jailbreaking or prompt injection detected"
- Spam (excessive exclamations): BLOCKED - "Input appears to be spam"

---

## Storage Tests (SQLite)

### agent_with_storage.py

**Status:** PASS

**Description:** Persistent conversations across runs using SQLite.

**Result:**
- Turn 1: Analyzed NVIDIA (comprehensive brief)
- Turn 2: Compared to Tesla (remembered NVDA context)
- Turn 3: Provided recommendation based on full conversation (NVIDIA recommended for fundamentals, Tesla for speculative)

---

### agent_with_memory.py

**Status:** PASS

**Description:** MemoryManager for user preferences.

**Result:**
- Agent learned user preferences (AI/semiconductor stocks, moderate risk)
- Recommendations tailored to preferences (MSFT, AVGO, TSM, ASML suggested as lower-volatility options)
- Memory stored: "The user is interested in AI and semiconductor stocks and has a moderate risk tolerance."

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Session state management for tracking structured data.

**Result:**
- Added NVDA, AAPL, GOOGL to watchlist via state management
- Agent queried prices for all watched stocks
- Final state: `Watchlist: ['NVDA', 'AAPL', 'GOOGL']`

---

## Knowledge Tests (ChromaDb)

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Knowledge base with hybrid search.

**Result:**
- Loaded Agno documentation into ChromaDb
- Searched knowledge base for "What is Agno?"
- Provided comprehensive answer about Agno's three pillars (Framework, AgentOS Runtime, Control Plane)

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Custom tools for saving and searching learnings.

**Result:**
- Agent proposed learning about P/E benchmarks
- User confirmed "yes" to save
- Learning saved: "Tech Sector P/E Benchmarks"
- Successfully retrieved learning when asked "What learnings do we have saved?"

---

## Multi-Agent Tests

### multi_agent_team.py

**Status:** PASS

**Description:** Multi-agent team with Bull and Bear analysts.

**Result:**
- Bull Analyst provided optimistic case for NVIDIA
- Bear Analyst provided cautionary perspective
- Team synthesized both views with comparison table (NVDA vs AMD)
- Final recommendation: "NVIDIA is a bet on dominance; AMD is a bet on market expansion"

---

### sequential_workflow.py

**Status:** PASS

**Description:** Sequential workflow pipeline with 3 steps.

**Result:**
- Step 1 (Data Collection): Fetched NVIDIA fundamentals
- Step 2 (Analysis): Deep-dive on strengths/weaknesses
- Step 3 (Report Writing): Final recommendation with metrics table
- Completed in 31.5s

**Note:** Debug warnings "Failed to broadcast through manager: no running event loop" appeared but did not affect execution.

---

## Interactive Tests

### human_in_the_loop.py

**Status:** NOT TESTED (Interactive)

**Description:** Requires user confirmation before executing tools.

**Note:** This test requires interactive input - cannot be fully automated.

---

## Other Tests

### readme_examples.py

**Status:** NOT TESTED

**Description:** Examples from the README - uses OpenAI instead of Gemini.

**Note:** Requires `OPENAI_API_KEY` instead of `GOOGLE_API_KEY`.

---

### run.py

**Status:** NOT TESTED

**Description:** Agent OS entrypoint for web interface.

**Note:** This starts a server - test by checking if it starts without errors.

---

## TESTING SUMMARY

**Summary:**
- Total cookbooks: 14
- Tested: 11/14
- Passed: 11/11
- Skipped: 3 (interactive/special requirements)

**Phases Completed:**
- Phase 1 (Basic): 4/4 passed
- Phase 2 (Storage): 3/3 passed
- Phase 3 (Knowledge): 2/2 passed
- Phase 4 (Multi-agent): 2/2 passed

**Skipped Tests:**
- `human_in_the_loop.py` - Requires interactive input
- `readme_examples.py` - Requires OpenAI API key
- `run.py` - Server startup test

**Notes:**
- All Gemini-based tests passing
- Storage (SQLite), Knowledge (ChromaDb), Memory, State all working correctly
- Multi-agent teams and workflows functioning as expected
- Guardrails correctly blocking PII, injection, and spam
