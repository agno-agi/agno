# Quick Start Cookbook Test Log

Testing results for `cookbook/00_quickstart/` examples.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- API Key: `GOOGLE_API_KEY` (Gemini)
- Date: 2026-01-14

---

## Test Summary

| Phase | Tests | Passed | Status |
|:------|:------|:-------|:-------|
| Phase 1: Basic | 3 | 3 | PASS |
| Phase 2: Persistence | 3 | 3 | PASS |
| Phase 3: Knowledge | 2 | 2 | PASS |
| Phase 4: Safety | 1 | 1 | PASS |
| Phase 5: Multi-Agent | 2 | 2 | PASS |
| **Total** | **11** | **11** | **ALL PASS** |

**Skipped:** 2 (interactive/server)
- `human_in_the_loop.py` - Requires user input
- `run.py` - Server entrypoint

---

## Phase 1: Basic (No DB)

### agent_with_tools.py

**Status:** PASS

**Description:** Basic agent with YFinanceTools for fetching stock data.

**Result:** Agent fetched NVIDIA stock data (price $182.41, market cap $4.44T, P/E 45.26) and provided comprehensive investment brief with key drivers, risks, and analyst sentiment.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Agent returns typed Pydantic objects (StockAnalysis).

**Result:** Agent returned structured StockAnalysis object with all typed fields including current_price ($182.37), key_drivers, key_risks, and recommendation (Strong Buy).

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Full type safety on input (StockQuery) and output (StockAnalysis) schemas.

**Result:** Agent accepted typed StockQuery input and returned typed StockAnalysis output for Apple (AAPL) at $260.24 with Buy recommendation.

---

## Phase 2: Persistence (SQLite)

### agent_with_storage.py

**Status:** PASS

**Description:** Persistent conversations across runs using SQLite.

**Result:**
- Turn 1: Analyzed NVIDIA (comprehensive brief)
- Turn 2: Compared to Tesla (remembered NVDA context)
- Turn 3: Provided recommendation based on full conversation (NVIDIA recommended for fundamentals)

---

### agent_with_memory.py

**Status:** PASS

**Description:** MemoryManager for storing and recalling user preferences.

**Result:**
- Agent learned user preferences (AI/semiconductor stocks, moderate risk)
- Recommendations tailored to preferences (MSFT, AVGO, TSM, ASML suggested)
- Memory stored and retrieved successfully

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Session state management for tracking structured data (watchlist).

**Result:**
- Added NVDA, AAPL, GOOGL to watchlist via state management
- Agent queried prices for all watched stocks
- Final state: `Watchlist: ['NVDA', 'AAPL', 'GOOGL']`

---

## Phase 3: Knowledge (ChromaDb)

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Knowledge base with hybrid search over Agno documentation.

**Result:**
- Loaded Agno documentation into ChromaDb
- Searched knowledge base for "What is Agno?"
- Provided comprehensive answer about Framework, AgentOS Runtime, and Control Plane

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Custom tools for saving and searching learnings in knowledge base.

**Result:**
- Retrieved existing learnings (P/E benchmarks, PEG ratio, interest rate impact)
- Successfully searched and returned 3 saved learnings from knowledge base

---

## Phase 4: Safety

### agent_with_guardrails.py

**Status:** PASS

**Description:** Input validation with PII detection, prompt injection blocking, and custom spam detection.

**Result:**
- Normal query (P/E ratio): Processed successfully with detailed response
- PII (SSN 123-45-6789): BLOCKED - "Potential PII detected"
- Prompt injection ("Ignore previous instructions"): BLOCKED - "Potential jailbreaking or prompt injection detected"
- Spam (excessive exclamations): BLOCKED - "Input appears to be spam"

---

## Phase 5: Multi-Agent

### multi_agent_team.py

**Status:** PASS

**Description:** Multi-agent team with Bull and Bear analysts coordinated by team leader.

**Result:**
- Bull Analyst provided optimistic case for NVIDIA
- Bear Analyst provided cautionary perspective
- Team synthesized both views into NVDA vs AMD comparison
- Final recommendation with key metrics table

---

### sequential_workflow.py

**Status:** PASS

**Description:** Sequential workflow pipeline with 3 steps (Data → Analysis → Report).

**Result:**
- Step 1 (Data Collection): Fetched NVIDIA fundamentals
- Step 2 (Analysis): Deep-dive on strengths/weaknesses
- Step 3 (Report Writing): Final BUY recommendation with metrics table
- Completed in 32.6s

**Note:** Debug warnings "Failed to broadcast through manager: no running event loop" appeared but did not affect execution.

---

## Skipped Tests

### human_in_the_loop.py

**Status:** SKIPPED (Interactive)

**Reason:** Requires user confirmation prompts - cannot be fully automated.

---

### run.py

**Status:** SKIPPED (Server)

**Reason:** Agent OS entrypoint - starts a server for web UI interaction.

---

## Notes

- All Gemini-based tests passing with `gemini-3-flash-preview` model
- Storage (SQLite), Knowledge (ChromaDb), Memory, State all working correctly
- Multi-agent teams and workflows functioning as expected
- Guardrails correctly blocking PII, injection, and spam
- Debug warning in workflows is non-blocking (known issue)
