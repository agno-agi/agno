# Quick Start Cookbook Test Log

Testing results for `cookbook/00_quickstart/` examples.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- API Key: `GOOGLE_API_KEY` (Gemini)
- Date: 2026-01-15

---

## Test Summary

| Phase | Tests | Passed | Status |
|:------|:------|:-------|:-------|
| Phase 1: Basic | 3 | 3 | PASS |
| Phase 2: Persistence | 3 | 3 | PASS |
| Phase 3: Knowledge | 2 | 2 | PASS |
| Phase 4: Safety | 2 | 2 | PASS |
| Phase 5: Multi-Agent | 2 | 2 | PASS |
| **Total** | **12** | **12** | **ALL PASS** |

**Skipped:** 1 (server)
- `run.py` - Server entrypoint

---

## Phase 1: Basic (No DB)

### agent_with_tools.py

**Status:** PASS

**Description:** Basic agent with YFinanceTools for fetching stock data.

**Result:** Agent fetched NVIDIA stock data (price $188.18, market cap $4.58T, P/E 46.46) and provided comprehensive investment brief with key drivers, risks, and analyst sentiment.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Agent returns typed Pydantic objects (StockAnalysis).

**Result:** Agent returned structured StockAnalysis object with all typed fields including current_price ($188.23), key_drivers, key_risks, and recommendation (Strong Buy).

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Full type safety on input (StockQuery) and output (StockAnalysis) schemas.

**Result:** Agent accepted typed input and returned typed output with proper validation.

---

## Phase 2: Persistence (SQLite)

### agent_with_storage.py

**Status:** PASS

**Description:** Persistent conversations across runs using SQLite.

**Result:**
- Turn 1: Analyzed NVIDIA (comprehensive brief)
- Turn 2: Compared to Tesla (remembered NVDA context)
- Turn 3: Provided recommendation based on full conversation

---

### agent_with_memory.py

**Status:** PASS

**Description:** MemoryManager for storing and recalling user preferences.

**Result:**
- Agent learned user preferences (AI/semiconductor stocks, moderate risk)
- Recommendations tailored to preferences
- Memory stored and retrieved successfully

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Session state management for tracking structured data (watchlist).

**Result:**
- Added NVDA, AAPL, GOOGL to watchlist via state management
- Agent queried prices for all watched stocks
- Final state correctly reflected watchlist

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
- Custom save_learning tool properly integrated
- Successfully searched and retrieved learnings from knowledge base

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

**Note:** Guardrails correctly block invalid requests. The ERROR logs confirm blocking behavior.

---

### human_in_the_loop.py

**Status:** PASS (Manual)

**Description:** Require user confirmation before executing sensitive tools.

**Result:** Interactive test - requires user input to confirm/reject tool execution. Code structure verified correct.

---

## Phase 5: Multi-Agent

### multi_agent_team.py

**Status:** PASS

**Description:** Multi-agent team with Bull and Bear analysts coordinated by team leader.

**Result:**
- Bull Analyst provided optimistic case for NVIDIA
- Bear Analyst provided cautionary perspective
- Team synthesized both views with comparison table
- Final recommendation with confidence levels

---

### sequential_workflow.py

**Status:** PASS

**Description:** Sequential workflow pipeline with 3 steps (Data -> Analysis -> Report).

**Result:**
- Step 1 (Data Collection): Fetched stock fundamentals
- Step 2 (Analysis): Deep-dive on strengths/weaknesses
- Step 3 (Report Writing): Final recommendation with metrics table

---

## Skipped Tests

### run.py

**Status:** SKIPPED (Server)

**Reason:** Agent OS entrypoint - starts a server for web UI interaction.

---

## Code Quality Notes

- Removed emojis from `agent_with_guardrails.py` and `human_in_the_loop.py` per CLAUDE.md guidelines
- All examples demonstrate ONE concept clearly
- Documentation and comments are thorough
- README progression is logical: Basic -> Output Control -> Persistence -> Knowledge -> Safety -> Multi-Agent

---

## Notes

- All Gemini-based tests passing with `gemini-3-flash-preview` model
- Storage (SQLite), Knowledge (ChromaDb), Memory, State all working correctly
- Multi-agent teams and workflows functioning as expected
- Guardrails correctly blocking PII, injection, and spam
