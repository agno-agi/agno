# TEST_LOG.md - Quick Start Cookbook

Test results for `cookbook/00_quickstart/` cookbooks.

**Test Date:** 2026-01-19
**Environment:** `.venvs/demo/bin/python`
**Model:** Gemini (gemini-3-flash-preview)

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
| Phase 4: Safety | human_in_the_loop.py | SKIPPED (Interactive) |
| Phase 5: Multi-Agent | multi_agent_team.py | PASS |
| Phase 5: Multi-Agent | sequential_workflow.py | PASS |

**Overall: 11 PASS, 1 SKIPPED**

---

## Phase 1: Basic (No DB)

### agent_with_tools.py

**Status:** PASS

**Description:** Finance agent with YFinanceTools that retrieves market data and produces investment briefs.

**Result:** Agent successfully used multiple YFinanceTools (get_current_stock_price, get_stock_fundamentals, get_key_financial_ratios, get_analyst_recommendations, get_company_info) to generate a comprehensive investment brief for NVIDIA including price, market cap, P/E ratio, key drivers, risks, and analyst sentiment.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Agent that returns structured Pydantic model (StockAnalysis) with typed fields.

**Result:** Agent correctly returned a StockAnalysis model with all required fields populated: ticker, company_name, current_price, market_cap, pe_ratio, week_52_high/low, summary, key_drivers (list), key_risks (list), and recommendation.

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Agent with both input schema (AnalysisRequest) and output schema (StockAnalysis) for end-to-end type safety.

**Result:** Successfully processed two analyses:
1. NVDA with `analysis_type="deep"` - included key_drivers and key_risks
2. AAPL with `analysis_type="quick"` - correctly omitted key_drivers/key_risks (null)

Both input methods (dict and Pydantic model) worked correctly.

---

## Phase 2: Persistence (SQLite)

### agent_with_storage.py

**Status:** PASS

**Description:** Agent with persistent conversation history stored to SQLite (`tmp/agents.db`).

**Result:** Agent maintained conversation context across 3 turns:
1. "Give me a quick investment brief on NVIDIA" - Generated brief
2. "Compare that to Tesla" - Remembered NVDA, fetched TSLA data, produced comparison table
3. "Based on our discussion, which looks like the better investment?" - Synthesized full conversation into recommendation

Session persistence via `session_id="finance-agent-session"` worked correctly.

---

### agent_with_memory.py

**Status:** PASS

**Description:** Agent with MemoryManager that extracts and stores user preferences across sessions.

**Result:** Agent successfully:
1. Captured user preference: "interested in AI and semiconductor stocks" with "moderate risk tolerance"
2. Used preferences to make personalized recommendations (AVGO, TSM, ASML, NVDA with beta/volatility considerations)
3. Stored memory to SQLite with topics: `['interests', 'finance', 'risk tolerance']`
4. Memory retrieval via `agent.get_user_memories(user_id=...)` returned the stored preference

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Agent with session state for managing a stock watchlist using custom tools.

**Result:** Agent successfully:
1. Used `add_to_watchlist` tool to add NVDA, AAPL, GOOGL to watchlist
2. Tracked watchlist state: `{'watchlist': ['NVDA', 'AAPL', 'GOOGL']}`
3. Fetched current prices for watched stocks when asked "How are my watched stocks doing?"
4. State persisted across runs and was accessible via `agent.get_session_state()`

---

## Phase 3: Knowledge (ChromaDb)

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Agent with searchable knowledge base using ChromaDb with hybrid search (vector + keyword).

**Result:** Agent successfully:
1. Loaded knowledge from URL (`https://docs.agno.com/introduction.md`)
2. Stored in ChromaDb with hybrid search (RRF fusion, k=60)
3. Used `search_knowledge_base(query="What is Agno?")` tool to retrieve relevant content
4. Generated comprehensive response about Agno framework, AgentOS, and features based on knowledge base

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Self-learning agent with custom `save_learning` tool to persist insights to knowledge base.

**Result:** Agent successfully:
1. Answered question about P/E ratios for tech stocks
2. Proposed a learning: "Tech Valuation Tiering" with actionable insight
3. Saved learning when user confirmed with "yes"
4. Retrieved saved learnings from knowledge base showing multiple stored insights

---

## Phase 4: Safety

### agent_with_guardrails.py

**Status:** PASS

**Description:** Agent with input validation guardrails: PIIDetectionGuardrail, PromptInjectionGuardrail, and custom SpamDetectionGuardrail.

**Result:** All guardrails worked correctly:
1. **Normal request** ("What's a good P/E ratio?") - Processed successfully with detailed response
2. **PII** ("My SSN is 123-45-6789") - Blocked with "Potential PII detected in input"
3. **Prompt injection** ("Ignore previous instructions") - Blocked with "Potential jailbreaking or prompt injection detected"
4. **Spam** ("URGENT!!! BUY NOW!!!!") - Blocked with "Input appears to be spam (excessive exclamation marks)"

---

### human_in_the_loop.py

**Status:** SKIPPED (Interactive)

**Description:** Agent with `@tool(requires_confirmation=True)` for human-in-the-loop approval workflow.

**Result:** This test requires interactive user input (confirmation prompts via `rich.prompt.Prompt`) and cannot be fully automated. The code structure is valid and demonstrates:
- `@tool(requires_confirmation=True)` decorator
- Handling `run_response.active_requirements`
- `requirement.confirm()` / `requirement.reject()` pattern
- `agent.continue_run()` to resume after user decision

**Note:** Manual testing required for full validation.

---

## Phase 5: Multi-Agent

### multi_agent_team.py

**Status:** PASS

**Description:** Investment research team with Bull Analyst, Bear Analyst, and Lead Analyst (team leader).

**Result:** Team successfully:
1. Delegated NVIDIA analysis to both Bull and Bear analysts
2. **Bull Analyst**: Made case FOR investment (AI dominance, growth, margins)
3. **Bear Analyst**: Made case AGAINST investment (valuation, geopolitical risks, concentration)
4. **Team Leader**: Synthesized both views into balanced recommendation with confidence level
5. Follow-up "How does AMD compare?" maintained context, delegated to both analysts, and produced comparison

Team coordination via `delegate_task_to_member` worked correctly.

---

### sequential_workflow.py

**Status:** PASS

**Description:** Three-step research pipeline: Data Gathering -> Analysis -> Report Writing.

**Result:** Workflow executed all 3 steps sequentially:
1. **Step 1 (Data Gatherer)**: Fetched comprehensive market data for NVIDIA using YFinanceTools
2. **Step 2 (Analyst)**: Interpreted key metrics, compared to benchmarks, identified strengths/weaknesses
3. **Step 3 (Report Writer)**: Produced concise investment brief with BUY recommendation, rationale, risks, and key metrics table

Completed in ~30 seconds. Debug messages about "Failed to broadcast through manager" are non-fatal event broadcasting warnings and don't affect workflow functionality.

---

## Notes

1. **API Rate Limits**: Gemini API may require pauses between tests if hitting rate limits.
2. **tmp/ Directory**: Tests create files in `tmp/` (agents.db, chromadb/) - this is expected behavior.
3. **Network Dependency**: yfinance requires internet access for real-time stock data.
4. **Interactive Tests**: human_in_the_loop.py requires manual testing with user input.
