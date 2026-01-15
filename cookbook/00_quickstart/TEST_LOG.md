# Quick Start Cookbook Test Log

Testing results for `cookbook/00_quickstart/` examples.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- API Key: `GOOGLE_API_KEY` (Gemini)
- Date: 2026-01-15

---

## Test Summary

| File | Status | Notes |
|------|--------|-------|
| agent_with_tools.py | PASS | Fetched NVDA data, comprehensive brief |
| agent_with_structured_output.py | PASS | Returned typed StockAnalysis object |
| agent_with_typed_input_output.py | PASS | Input/output schema validation working |
| agent_with_storage.py | PASS | Multi-turn conversation persistence |
| agent_with_memory.py | PASS | User preferences stored and recalled |
| agent_with_state_management.py | PASS | Watchlist state maintained |
| agent_search_over_knowledge.py | PASS | ChromaDb hybrid search working |
| custom_tool_for_self_learning.py | PASS | Custom save_learning tool integrated |
| agent_with_guardrails.py | PASS | PII/injection/spam blocked correctly |
| human_in_the_loop.py | MANUAL | Requires user input |
| multi_agent_team.py | PASS | Bull/Bear analysis synthesized |
| sequential_workflow.py | PASS | 3-step pipeline executed |
| run.py | SKIPPED | Server entrypoint |

**Total: 11/11 automated tests PASS**

---

## Test Details

### Phase 1: Basic (No DB)

**agent_with_tools.py** - PASS
- Fetched NVIDIA stock data via YFinanceTools
- Returned comprehensive investment brief with key drivers and risks

**agent_with_structured_output.py** - PASS
- Returned typed StockAnalysis Pydantic object
- All fields populated correctly (price, market_cap, key_drivers, etc.)

**agent_with_typed_input_output.py** - PASS
- Input schema (AnalysisRequest) validated
- Output schema (StockAnalysis) enforced
- Both dict and Pydantic model inputs work

### Phase 2: Persistence (SQLite)

**agent_with_storage.py** - PASS
- Turn 1: Analyzed NVIDIA
- Turn 2: Compared to Tesla (remembered context)
- Turn 3: Synthesized recommendation based on full conversation

**agent_with_memory.py** - PASS
- Stored user preferences (AI/semiconductor stocks, moderate risk)
- Recommendations tailored to stored preferences
- Memory retrieved via `get_user_memories()`

**agent_with_state_management.py** - PASS
- Added NVDA, AAPL, GOOGL to watchlist via custom tools
- Agent queried prices for all watched stocks
- State persisted: `{'watchlist': ['NVDA', 'AAPL', 'GOOGL']}`

### Phase 3: Knowledge (ChromaDb)

**agent_search_over_knowledge.py** - PASS
- Loaded Agno docs into ChromaDb
- Hybrid search returned relevant results
- Agent synthesized comprehensive answer about Agno framework

**custom_tool_for_self_learning.py** - PASS
- Custom `save_learning` tool integrated
- Learnings saved to knowledge base
- Retrieved saved learnings via search

### Phase 4: Safety

**agent_with_guardrails.py** - PASS
- Normal query: Processed successfully
- PII (SSN): BLOCKED - "Potential PII detected"
- Prompt injection: BLOCKED - "Potential jailbreaking detected"
- Spam (excessive exclamations): BLOCKED by custom guardrail

**human_in_the_loop.py** - MANUAL
- Requires user input for confirmation prompts
- Code structure verified correct

### Phase 5: Multi-Agent

**multi_agent_team.py** - PASS
- Bull Analyst: Provided optimistic case
- Bear Analyst: Provided cautionary perspective
- Team Leader: Synthesized both views with comparison table

**sequential_workflow.py** - PASS
- Step 1 (Data Gathering): Fetched stock fundamentals
- Step 2 (Analysis): Identified strengths/weaknesses
- Step 3 (Report Writing): Produced concise investment brief

---

## Code Quality Notes

- All examples use correct model ID: `gemini-3-flash-preview`
- No emojis in code (per CLAUDE.md guidelines)
- Each file demonstrates ONE concept clearly
- Well-documented with helpful comments
- README progression is logical

---

## Known Observations

1. **Debug warning in workflows**: "Failed to broadcast through manager: no running event loop" appears but doesn't affect execution - this is related to async event broadcasting in sync context.

2. **Guardrails behavior**: The `print_response` method handles `InputCheckError` internally, showing ERROR logs but not raising to calling code. The try/except pattern in the example demonstrates the API but the guardrails block at the framework level.
