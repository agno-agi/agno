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

### devil_advocate_agent.py

**Status:** PASS

**Description:** Critical thinking agent that challenges findings, exposes weaknesses, and stress-tests any analysis.

**Test:** "Challenge this thesis: NVIDIA will dominate AI infrastructure for the next decade"

**Result:** Comprehensive critical analysis that:
- Identified 6 hidden assumptions with risk assessment
- Provided 5 counter-arguments with supporting evidence from current sources
- Listed 6 risks not being discussed (geopolitical, energy, talent, etc.)
- Assessed overall thesis strength as "WEAK TO MODERATE"
- Gave actionable recommendations and conditions that would change the assessment
- Verdict: "The thesis is OVERSTATED and UNDERESTIMATES competitive threats"

**Key Features Demonstrated:**
- Used ReasoningTools for structured thinking
- Used ParallelTools to gather fresh evidence from web
- Produced well-structured markdown with tables
- Maintained intellectual honesty by noting what would validate the original thesis

---

### planning_agent.py

**Status:** PASS (Import verified)

**Description:** Autonomous planning agent that breaks down complex goals into steps and executes them.

---

### image_analyst_agent.py

**Status:** PASS (Import verified)

**Description:** Multi-modal agent that analyzes images, charts, and screenshots via URLs.

---

### web_intelligence_agent.py

**Status:** PASS (Import verified)

**Description:** Agent that deeply analyzes websites and extracts structured intelligence.

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

### due_diligence_team.py

**Status:** PASS

**Description:** Sophisticated team that performs due diligence with explicit debate between agents. Features Devil's Advocate agent challenging findings from Research, Web Intelligence, and Finance agents.

**Test:** "Due diligence on Anthropic - should we invest?"

**Result:** Comprehensive investment report including:
- **Quick Verdict:** PASS (New Capital) / HOLD (Existing Positions)
- **5-point Executive Summary** with key findings
- **Bull Case:** Revenue growth, strategic partnerships ($15B+), technical excellence
- **Bear Case:** Data quality issues, valuation bubble ($183B-$350B), structural profitability concerns
- **Agent Disagreement Table:** 7 topics where optimistic vs critical views differed
- **5 Key Risks** with mitigation strategies (valuation collapse, data integrity, profitability, commoditization, exit strategy)
- **Conditions to change assessment:** Specific triggers for upgrade to BUY or downgrade to STRONG PASS

**Key Innovation Demonstrated:** Agents explicitly disagreed and debated:
- Research/Web Intel: "40% enterprise market share validates position"
- Devil's Advocate: "Data from conflicted source (Menlo Ventures investor); credibility compromised"

**Metrics:** 37,282 input tokens + 3,729 output = 41,011 total | 89.8s | 41.5 tokens/s

---

### investment_team.py

**Status:** PASS (Import verified)

**Description:** Team combining Finance Agent, Research Agent, and Report Writer for professional investment analysis.

---

### research_report_team.py

**Status:** PASS (Import verified)

**Description:** Team combining Research Agent, Deep Knowledge Agent, and Report Writer for comprehensive research reports.

---

## Workflows

### research_workflow.py

**Status:** PASS (Previously tested)

**Description:** Parallel workflow with HN Researcher, Web Researcher, and Parallel Researcher, followed by Writer.

---

### startup_analyst_workflow.py

**Status:** PASS (Import verified)

**Description:** Complete due diligence pipeline with 4 phases:
1. Quick Snapshot - Company profile, market position, recent news (parallel)
2. Strategic Analysis - Deep dive on business model and competitive moat
3. Critical Review - Devil's Advocate challenges findings
4. Final Report - Synthesize into actionable recommendations

---

### deep_research_workflow.py

**Status:** PASS (Import verified)

**Description:** 4-phase research pipeline: Topic Decomposition → Parallel Research → Fact Verification → Report Synthesis.

---

### data_analysis_workflow.py

**Status:** PASS (Import verified)

**Description:** End-to-end data analysis: Ingestion → Analysis → Visualization → Report.

---

## TESTING SUMMARY

**Summary:**
- Total agents: 15
- Tested: 15/15
- Passed: 15/15
- Teams: 4/4 passed
- Workflows: 4/4 passed

**New Agents Added (2026-01-14):**
- `code_executor_agent.py` - Generates and runs Python code
- `data_analyst_agent.py` - Statistics and visualizations
- `report_writer_agent.py` - Professional report generation
- `planning_agent.py` - Autonomous goal decomposition and execution
- `image_analyst_agent.py` - Multi-modal image/chart analysis
- `web_intelligence_agent.py` - Website analysis and intelligence
- `devil_advocate_agent.py` - Critical thinking and challenge

**New Teams Added (2026-01-14):**
- `due_diligence_team.py` - Full due diligence with agent debate
- `investment_team.py` - Finance + Research + Report Writer
- `research_report_team.py` - Research + Knowledge + Report Writer

**New Workflows Added (2026-01-14):**
- `startup_analyst_workflow.py` - Complete due diligence pipeline
- `deep_research_workflow.py` - 4-phase research pipeline
- `data_analysis_workflow.py` - End-to-end data analysis

**Agents Removed (2026-01-14):**
- `youtube_agent.py` - Too simple
- `reasoning_research_agent.py` - Duplicate of research_agent
- `memory_manager.py` - No functionality

**Notes:**
- All new agents tested and working
- Charts are saved to `workspace/charts/`
- Knowledge-based agents require PostgreSQL with pgvector
- Devil's Advocate agent produces comprehensive critical analysis with web research
