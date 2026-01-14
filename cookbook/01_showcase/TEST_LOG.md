# Showcase Testing Log

Testing all cookbooks in `cookbook/01_showcase/` to verify they work as expected.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Date: 2026-01-14

---

## 01_agents/

### self_learning_agent.py

**Status:** PASS (imports)

**Description:** Agent that learns and saves reusable insights to knowledge base.

**Requires:** PostgreSQL with PgVector, OPENAI_API_KEY

---

### self_learning_research_agent.py

**Status:** PASS (imports)

**Description:** Research agent that tracks consensus over time and compares with past snapshots.

**Requires:** PostgreSQL with PgVector, OPENAI_API_KEY

---

### deep_knowledge_agent.py

**Status:** PASS

**Description:** Deep reasoning with iterative knowledge base search using ReasoningTools.

**Requires:** PostgreSQL with PgVector, OPENAI_API_KEY

**Notes:** Auto-loads content from docs.agno.com when run.

---

### deep_research_agent_exa.py

**Status:** REQUIRES DEPENDENCY

**Description:** Research agent with citations using Exa search.

**Requires:** EXA_API_KEY, exa_py package

---

### startup_analyst_agent.py

**Status:** REQUIRES DEPENDENCY

**Description:** Due diligence research on startups using ScrapeGraph.

**Requires:** SGAI_API_KEY, scrapegraph_py package

---

### social_media_agent.py

**Status:** REQUIRES DEPENDENCY

**Description:** X/Twitter brand intelligence and sentiment analysis.

**Requires:** X_API_KEY, tweepy package

---

### translation_agent.py

**Status:** REQUIRES DEPENDENCY

**Description:** Multi-language translation with voice synthesis.

**Requires:** CARTESIA_API_KEY, cartesia package

---

### recipe_rag_image.py

**Status:** REQUIRES DEPENDENCY

**Description:** Recipe search with RAG and image generation.

**Requires:** COHERE_API_KEY, OPENAI_API_KEY, cohere package

---

### airbnb_mcp.py

**Status:** REQUIRES DEPENDENCY

**Description:** Airbnb search via MCP with Llama 4.

**Requires:** GROQ_API_KEY, groq package, npx (Node.js)

---

### sql/sql_agent.py

**Status:** PASS (imports)

**Description:** Text-to-SQL agent with F1 data, semantic model, and self-learning.

**Requires:** PostgreSQL with PgVector

---

## 02_teams/

### tic_tac_toe_team.py

**Status:** PASS

**Description:** GPT-4o vs Gemini playing tic-tac-toe.

**Requires:** OPENAI_API_KEY, GOOGLE_API_KEY

**Notes:** Successfully tested - game runs and completes with proper turn-taking.

---

### skyplanner_mcp_team.py

**Status:** REQUIRES DEPENDENCY

**Description:** Trip planning team with multiple MCP servers.

**Requires:** npx (Node.js), GOOGLE_API_KEY

---

### autonomous_startup_team.py

**Status:** PASS (imports)

**Description:** Autonomous multi-agent startup simulation team with 6 specialized agents.

**Requires:** OPENAI_API_KEY, EXA_API_KEY (optional), SLACK_TOKEN (optional)

**Notes:** Fixed broken knowledge path reference.

---

### news_agency_team.py

**Status:** PASS (imports)

**Description:** News research and writing team with coordination.

**Requires:** OPENAI_API_KEY

---

### ai_customer_support_team.py

**Status:** PASS (imports)

**Description:** Customer support automation with routing and escalation.

---

## 03_workflows/

### startup_idea_validator.py

**Status:** PASS (imports)

**Description:** 4-phase startup idea validation workflow with structured Pydantic output.

**Requires:** OPENAI_API_KEY

**Notes:** Removed emojis per style guide.

---

### investment_report_generator.py

**Status:** PASS (syntax)

**Description:** Financial analysis pipeline for investment reports.

---

### employee_recruiter_async_stream.py

**Status:** PASS (syntax)

**Description:** Streaming recruitment workflow with async execution.

---

### research_workflow.py

**Status:** PASS (imports)

**Description:** Parallel research workflow with multiple agents (HN, Web, Parallel).

**Requires:** PostgreSQL with PgVector, OPENAI_API_KEY

**Notes:** Added main execution block.

---

## 04_gemini/

### agents/pal_agent.py

**Status:** PASS (imports)

**Description:** Plan and Learn Agent - creates structured plans with success criteria.

**Requires:** PostgreSQL with PgVector, GOOGLE_API_KEY

**Notes:** Removed emojis from interactive mode per style guide.

---

### agents/self_learning_agent.py

**Status:** PASS (imports)

**Description:** Self-learning agent using Gemini.

**Requires:** PostgreSQL with PgVector, GOOGLE_API_KEY

---

### agents/self_learning_research_agent.py

**Status:** PASS (imports)

**Description:** Research tracking agent with claims and consensus using Gemini.

**Requires:** PostgreSQL with PgVector, GOOGLE_API_KEY

---

### agents/creative_studio_agent.py

**Status:** PASS (syntax)

**Description:** Image generation with NanoBanana and Gemini.

---

### agents/product_comparison_agent.py

**Status:** PASS (syntax)

**Description:** Product comparison using Gemini native search features.

---

## TESTING SUMMARY

**Summary:**
- Total cookbooks: 24 (excluding support files)
- Imports/Syntax Pass: 18
- Requires External Dependencies: 6 (exa, scrapegraph, tweepy, cartesia, cohere, groq)
- Full Runtime Test: 1 (tic_tac_toe_team.py)

**Issues Fixed:**
1. startup_idea_validator.py - Removed emojis per style guide
2. pal_agent.py - Removed emojis from interactive mode
3. research_workflow.py - Added main execution block
4. news_agency_team.py - Wrapped execution in main guard
5. autonomous_startup_team.py - Removed broken knowledge path, added main guard

**Notes:**
- PostgreSQL with PgVector required for most agents (`./cookbook/scripts/run_pgvector.sh`)
- Many agents require external API keys
- MCP agents require Node.js with npx
