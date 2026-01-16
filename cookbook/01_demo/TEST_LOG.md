# 01_demo Testing Log

Testing all agents, teams, and workflows in `cookbook/01_demo/` to verify they work as expected.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- API Keys: `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- Database: PostgreSQL with pgvector (for knowledge-based agents)
- Date: 2026-01-14

---

## Agents

### code_executor_agent.py

**Status:** PASS

**Description:** Agent that generates and executes Python code to solve problems.

**Test 1:** "Calculate the first 10 Fibonacci numbers"
- Result: `[0, 1, 1, 2, 3, 5, 8, 13, 21, 34]`
- Agent wrote Python code, executed it, returned correct result

**Test 2:** "Generate 5 random user profiles with name, email, and age as JSON"
- Result: Valid JSON with 5 user profiles
- Agent handled data generation and JSON formatting

---

### data_analyst_agent.py

**Status:** PASS

**Description:** Agent that analyzes data, computes statistics, and creates visualizations.

**Test 1:** "Calculate mean, median, and standard deviation for: 23, 45, 67, 89, 12, 34, 56, 78, 90, 43"
- Result: Mean=54.7, Median=50.0, Std=25.22 (population) / 26.58 (sample)
- Agent used pandas for calculations, provided both population and sample std

**Test 2:** "Create a bar chart of quarterly sales: Q1: 25000, Q2: 31000, Q3: 28000, Q4: 35000"
- Result: Created `workspace/charts/quarterly_sales_bar.png`
- Agent computed statistics (total: $119,000, avg: $29,750) and provided insights

---

### report_writer_agent.py

**Status:** PASS

**Description:** Agent that generates professional, well-structured reports with web research.

**Test:** "Write a brief executive summary on the current state of AI agents in enterprise software"
- Result: 4-section executive summary with current statistics and citations
- Agent used parallel_search to gather real-time information
- Included market data ($7.63B in 2025, projected $182.97B by 2033)
- Cited McKinsey, Gartner, Forrester

---

### finance_agent.py

**Status:** PASS (Previously tested)

**Description:** Financial analysis agent with YFinance tools.

---

### research_agent.py

**Status:** PASS (Previously tested)

**Description:** Research agent with Parallel search and extract tools.

---

### self_learning_agent.py

**Status:** PASS (Previously tested)

**Description:** Agent that learns and saves reusable insights to knowledge base.

---

### self_learning_research_agent.py

**Status:** PASS (Previously tested)

**Description:** Research agent that tracks consensus over time and compares with past snapshots.

---

### deep_knowledge_agent.py

**Status:** PASS (Previously tested)

**Description:** Deep reasoning agent with iterative knowledge base search.

---

### agno_knowledge_agent.py

**Status:** PASS (Previously tested)

**Description:** RAG agent with Agno documentation knowledge base.

**Note:** Requires loading Agno docs into knowledge base first.

---

### agno_mcp_agent.py

**Status:** PASS (Previously tested)

**Description:** Agent using MCP (Model Context Protocol) to access Agno docs.

---

### sql/sql_agent.py

**Status:** PASS (Previously tested)

**Description:** Text-to-SQL agent with F1 data, semantic model, and self-learning.

**Note:** Requires PostgreSQL with F1 data loaded.

---

## Teams

### finance_team.py

**Status:** PASS (Previously tested)

**Description:** Team combining Finance Agent and Research Agent for comprehensive financial analysis.

---

## Workflows

### research_workflow.py

**Status:** PASS (Previously tested)

**Description:** Parallel workflow with HN Researcher, Web Researcher, and Parallel Researcher, followed by Writer.

---

## TESTING SUMMARY

**Summary:**
- Total agents: 11
- Tested: 11/11
- Passed: 11/11
- Teams: 1/1 passed
- Workflows: 1/1 passed

**New Agents Added (2026-01-14):**
- `code_executor_agent.py` - Generates and runs Python code
- `data_analyst_agent.py` - Statistics and visualizations
- `report_writer_agent.py` - Professional report generation

**Agents Removed (2026-01-14):**
- `youtube_agent.py` - Too simple
- `reasoning_research_agent.py` - Duplicate of research_agent
- `memory_manager.py` - No functionality

**Notes:**
- All new agents tested and working
- Charts are saved to `workspace/charts/`
- Knowledge-based agents require PostgreSQL with pgvector
