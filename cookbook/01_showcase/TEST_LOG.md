# Showcase Testing Log

Testing all cookbooks in `cookbook/01_showcase/` to verify they work as expected.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Date: 2026-01-14

---

## 01_agents/

### finance_agent.py

**Status:** NOT TESTED

**Description:** Comprehensive financial analysis agent with YFinance tools.

---

### self_learning_agent.py

**Status:** NOT TESTED

**Description:** Agent that learns and saves reusable insights to knowledge base.

---

### self_learning_research_agent.py

**Status:** NOT TESTED

**Description:** Research agent that tracks consensus over time and compares with past snapshots.

---

### deep_knowledge_agent.py

**Status:** NOT TESTED

**Description:** Deep reasoning with iterative knowledge base search.

---

### deep_knowledge.py

**Status:** NOT TESTED

**Description:** Iterative knowledge base search with agentic RAG.

---

### deep_research_agent_exa.py

**Status:** NOT TESTED

**Description:** Research agent with citations using Exa search.

**Requires:** EXA_API_KEY

---

### startup_analyst_agent.py

**Status:** NOT TESTED

**Description:** Due diligence research on startups using ScrapeGraph.

**Requires:** SGAI_API_KEY

---

### social_media_agent.py

**Status:** NOT TESTED

**Description:** X/Twitter brand intelligence and sentiment analysis.

**Requires:** X_API_KEY

---

### translation_agent.py

**Status:** NOT TESTED

**Description:** Multi-language translation with voice synthesis.

**Requires:** CARTESIA_API_KEY

---

### recipe_rag_image.py

**Status:** NOT TESTED

**Description:** Recipe search with RAG and image generation.

**Requires:** COHERE_API_KEY, OPENAI_API_KEY

---

### airbnb_mcp.py

**Status:** NOT TESTED

**Description:** Airbnb search via MCP with Llama 4.

**Requires:** GROQ_API_KEY, npx (Node.js)

---

### reasoning_finance_agent.py

**Status:** NOT TESTED

**Description:** Financial analysis with extended chain-of-thought reasoning.

---

### sql/sql_agent.py

**Status:** NOT TESTED

**Description:** Text-to-SQL agent with F1 data, semantic model, and self-learning.

**Requires:** PostgreSQL with PgVector

---

## 02_teams/

### tic_tac_toe_team.py

**Status:** NOT TESTED

**Description:** GPT-4o vs Gemini playing tic-tac-toe.

**Requires:** OPENAI_API_KEY, GOOGLE_API_KEY

---

### skyplanner_mcp_team.py

**Status:** NOT TESTED

**Description:** Trip planning team with multiple MCP servers.

**Requires:** npx (Node.js), GOOGLE_API_KEY

---

### autonomous_startup_team.py

**Status:** NOT TESTED

**Description:** Autonomous multi-agent startup simulation team.

---

### news_agency_team.py

**Status:** NOT TESTED

**Description:** News research and writing team with coordination.

---

### ai_customer_support_team.py

**Status:** NOT TESTED

**Description:** Customer support automation with routing and escalation.

---

### finance_team.py

**Status:** NOT TESTED

**Description:** Finance + research team working together.

---

## 03_workflows/

### startup_idea_validator.py

**Status:** NOT TESTED

**Description:** 4-phase startup idea validation workflow.

---

### investment_report_generator.py

**Status:** NOT TESTED

**Description:** Financial analysis pipeline for investment reports.

---

### employee_recruiter_async_stream.py

**Status:** NOT TESTED

**Description:** Streaming recruitment workflow with async execution.

---

### research_workflow.py

**Status:** NOT TESTED

**Description:** Parallel research workflow with multiple agents.

---

## 04_gemini/

See `04_gemini/` folder for Gemini-specific examples.

---

## TESTING SUMMARY

**Summary:**
- Total cookbooks: 26 (excluding 04_gemini subfolder)
- Tested: 0/26
- Passed: 0
- Skipped: 0

**Notes:**
- Showcase folder newly created
- Testing pending
