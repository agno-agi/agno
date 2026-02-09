# TEST_LOG.md - Quick Start Cookbook

Test results for `cookbook/00_quickstart/` cookbooks.

**Test Date:** 2026-02-09
**Environment:** `.venvs/demo/bin/python`
**Model:** Gemini (gemini-3-flash-preview)
**Branch:** v2.5-clean

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

**Result:** Agent successfully used multiple YFinanceTools (get_current_stock_price, get_stock_fundamentals, get_key_financial_ratios, get_analyst_recommendations, get_company_info, get_company_news, get_technical_indicators) to generate a comprehensive investment brief for NVIDIA including price ($191.83), market cap ($4.67T), P/E ratio (47.48), key drivers, risks, and analyst sentiment (Strong Buy).

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Agent that returns structured Pydantic model (StockAnalysis) with typed fields.

**Result:** Agent correctly returned a StockAnalysis model with all required fields populated: ticker (NVDA), company_name (NVIDIA Corporation), current_price (191.84), market_cap (4.67T), pe_ratio (47.48), week_52_high/low, summary, key_drivers (3 items), key_risks (3 items), and recommendation (Strong Buy).

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
3. "Based on our discussion, which looks like the better investment?" - Synthesized full conversation into recommendation with NVIDIA vs Tesla comparison (GARP vs speculative growth)

Session persistence via `session_id="finance-agent-session"` worked correctly.

---

### agent_with_memory.py

**Status:** PASS

**Description:** Agent with MemoryManager that extracts and stores user preferences across sessions.

**Result:** Agent successfully:
1. Captured user preferences: "AI and semiconductor stocks" with "moderate risk tolerance"
2. Used preferences to make personalized recommendations (MSFT, AVGO, TSM, ASML with Beta/volatility considerations)
3. Stored 2 memories to SQLite with topics: `['interests', 'stocks', 'AI', 'semiconductors']` and `['risk tolerance', 'investments']`
4. Memory retrieval via `agent.get_user_memories(user_id=...)` returned both stored preferences

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Agent with session state for managing a stock watchlist using custom tools.

**Result:** Agent successfully:
1. Used `add_to_watchlist` tool to add NVDA, AAPL, GOOGL to watchlist
2. Tracked watchlist state: `{'watchlist': ['NVDA', 'AAPL', 'GOOGL']}`
3. Fetched current prices and historical data for watched stocks when asked "How are my watched stocks doing?"
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
4. Generated comprehensive response about Agno framework including core components (SDK, AgentOS, AgentOS UI), key features, and code example

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Self-learning agent with custom `save_learning` tool to persist insights to knowledge base.

**Result:** Agent successfully:
1. Answered question about P/E ratios for tech stocks
2. Proposed a learning: "Tech stock P/E and PEG benchmarks" with actionable insight
3. Saved learning when user confirmed with "yes"
4. Retrieved saved learnings from knowledge base showing the stored insight with timestamp

---

## Phase 4: Safety

### agent_with_guardrails.py

**Status:** PASS

**Description:** Agent with input validation guardrails: PIIDetectionGuardrail, PromptInjectionGuardrail, and custom SpamDetectionGuardrail.

**Result:** All guardrails worked correctly:
1. **Normal request** ("What's a good P/E ratio?") - Processed successfully with detailed response including real examples (MSFT, AAPL, NVDA P/E ratios)
2. **PII** ("My SSN is 123-45-6789") - Blocked with "Potential PII detected in input"
3. **Prompt injection** ("Ignore previous instructions") - Blocked with "Potential jailbreaking or prompt injection detected"
4. **Spam** ("URGENT!!! BUY NOW!!!!") - Blocked with "Input appears to be spam (excessive exclamation marks)"

---

### human_in_the_loop.py

**Status:** SKIPPED (Interactive)

**Description:** Agent with `@tool(requires_confirmation=True)` for human-in-the-loop approval workflow.

**Result:** This test requires interactive user input (confirmation prompts via `rich.prompt.Prompt`) and cannot be fully automated.

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
5. Follow-up "How does AMD compare?" maintained context, delegated to both analysts, and produced comprehensive AMD vs NVIDIA comparison with metrics table

Team coordination via `delegate_task_to_member` worked correctly.

---

### sequential_workflow.py

**Status:** PASS

**Description:** Three-step research pipeline: Data Gathering -> Analysis -> Report Writing.

**Result:** Workflow executed all 3 steps sequentially:
1. **Step 1 (Data Gatherer)**: Fetched comprehensive market data for NVIDIA using YFinanceTools (price, fundamentals, ratios, analyst sentiment, historical data)
2. **Step 2 (Analyst)**: Interpreted key metrics, compared to benchmarks, identified strengths/weaknesses
3. **Step 3 (Report Writer)**: Produced investment brief with core price info, valuation, efficiency metrics, and analyst sentiment

---

## Notes

1. **API Rate Limits**: No rate limit issues encountered during this run.
2. **tmp/ Directory**: Tests create files in `tmp/` (agents.db, chromadb/) - this is expected behavior.
3. **Network Dependency**: yfinance requires internet access for real-time stock data.
4. **Interactive Tests**: human_in_the_loop.py requires manual testing with user input.
5. **Environment**: `GOOGLE_API_KEY` must be set via direnv or manually exported.
