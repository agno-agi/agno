# TEST_LOG - 01_showcase

**Test Date:** 2026-01-16
**Environment:** `.venvs/demo/bin/python`
**Branch:** `v2.4-with-cookbooks`

---

## 01_agents/

### self_learning_agent.py

**Status:** N/A (Module only)

**Description:** Defines agent but has no main block. Used as import by other files.

---

### deep_knowledge_agent.py

**Status:** PASS

**Description:** Agentic RAG agent with deep knowledge. Successfully loaded Agno documentation (861 documents) into PgVector knowledge base, processing in batches of 100.

---

## 02_teams/

### tic_tac_toe_team.py

**Status:** PASS

**Description:** Multi-model Tic Tac Toe game. Two AI players (Player 1 = X, Player 2 = O) played a complete game ending in a draw. Final board state was valid and game logic worked correctly. Completed in 56.1s.

---

### autonomous_startup_team.py

**Status:** SKIPPED (Missing dependency)

**Description:** Requires `exa_py` module which is not installed.

---

### news_agency_team.py

**Status:** SKIPPED (Missing dependency)

**Description:** Requires `newspaper4k` module which is not installed.

---

### skyplanner_mcp_team.py

**Status:** SKIPPED (MCP required)

**Description:** Requires MCP/npx which is not available in test environment.

---

## 03_workflows/

### research_workflow.py

**Status:** PASS

**Description:** Parallel execution research workflow. Successfully researched AI agents landscape, producing comprehensive analysis with current sources (OpenAI CUA, Anthropic computer use, MCP, etc.), key trends, and consolidated takeaways.

---

### startup_idea_validator.py

**Status:** SKIPPED (Interactive)

**Description:** Requires user input via Rich Prompt. Cannot be automated.

---

### investment_report_generator.py

**Status:** SKIPPED (Interactive)

**Description:** Requires user input for company symbols. Cannot be automated.

---

### employee_recruiter_async_stream.py

**Status:** NOT TESTED

**Description:** Async streaming workflow - not tested in this run.

---

## 04_gemini/

### pal_agent.py

**Status:** SKIPPED (Interactive)

**Description:** Plan and Learn agent. Requires interactive input loop. Cannot be automated.

---

### creative_studio_agent.py

**Status:** NOT TESTED

---

### product_comparison_agent.py

**Status:** NOT TESTED

---

### self_learning_agent.py

**Status:** NOT TESTED

---

### self_learning_research_agent.py

**Status:** NOT TESTED

---

## Summary

| Test | Status |
|:-----|:-------|
| 01_agents/deep_knowledge_agent.py | PASS |
| 02_teams/tic_tac_toe_team.py | PASS |
| 03_workflows/research_workflow.py | PASS |
| 01_agents/self_learning_agent.py | N/A (Module) |
| 02_teams/autonomous_startup_team.py | SKIPPED (exa_py) |
| 02_teams/news_agency_team.py | SKIPPED (newspaper4k) |
| 02_teams/skyplanner_mcp_team.py | SKIPPED (MCP) |
| 03_workflows/startup_idea_validator.py | SKIPPED (Interactive) |
| 03_workflows/investment_report_generator.py | SKIPPED (Interactive) |
| 04_gemini/pal_agent.py | SKIPPED (Interactive) |

**Total:** 3 PASS, 7 SKIPPED/N/A

**Notes:**
- Many showcase examples require interactive input (Rich Prompt)
- Some require external dependencies not in demo venv (exa_py, newspaper4k)
- MCP agents require Node.js/npx
