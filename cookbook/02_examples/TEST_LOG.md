# Examples Cookbook Testing Log

Testing examples in `cookbook/02_examples/` to verify they work as expected.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Database: PostgreSQL with PgVector (`./cookbook/scripts/run_pgvector.sh`)
- Date: 2026-01-14

---

## 01_agents/

### Impressive Agents (Priority Testing)

#### startup_analyst_agent.py

**Status:** NOT TESTED

**Description:** Comprehensive startup due diligence using ScrapeGraph.

**Dependencies:** SGAI_API_KEY

---

#### airbnb_mcp.py

**Status:** NOT TESTED

**Description:** MCP integration with Llama 4 for Airbnb search.

**Dependencies:** GROQ_API_KEY, Node.js (npx)

---

#### deep_research_agent_exa.py

**Status:** NOT TESTED

**Description:** Advanced research with Exa Research Pro and citations.

**Dependencies:** EXA_API_KEY

---

#### recipe_rag_image.py

**Status:** NOT TESTED

**Description:** Multi-modal RAG with image generation.

**Dependencies:** PgVector, COHERE_API_KEY, OPENAI_API_KEY

---

#### translation_agent.py

**Status:** NOT TESTED

**Description:** Emotion-aware translation with Cartesia voice synthesis.

**Dependencies:** CARTESIA_API_KEY, GOOGLE_API_KEY

---

#### social_media_agent.py

**Status:** NOT TESTED

**Description:** X/Twitter brand intelligence and sentiment analysis.

**Dependencies:** X_API_KEY

---

#### deep_knowledge.py

**Status:** NOT TESTED

**Description:** Iterative knowledge base search with PgVector.

**Dependencies:** PgVector

---

### Basic Agents

#### basic_agent.py

**Status:** NOT TESTED

**Description:** Minimal agent example.

**Note:** Consider removing - overlaps with 00_getting_started.

---

#### agent_with_tools.py

**Status:** NOT TESTED

**Description:** Agent with tools.

**Note:** Consider removing - overlaps with 00_getting_started.

---

#### fibonacci_agent.py

**Status:** NOT TESTED

**Description:** Fibonacci calculation agent.

**Note:** Consider removing - too trivial.

---

## 02_teams/

### tic_tac_toe_team.py

**Status:** NOT TESTED

**Description:** GPT-4o vs Gemini playing tic-tac-toe.

**Dependencies:** OPENAI_API_KEY, GOOGLE_API_KEY

---

### skyplanner_mcp_team.py

**Status:** NOT TESTED

**Description:** Travel planning with multiple MCP servers (Airbnb, Google Maps).

**Dependencies:** GOOGLE_MAPS_API_KEY, Node.js (npx)

---

### autonomous_startup_team.py

**Status:** NOT TESTED

**Description:** Autonomous multi-agent startup team.

**Dependencies:** OPENAI_API_KEY

---

## 03_workflows/

### startup_idea_validator.py

**Status:** NOT TESTED

**Description:** 4-phase startup validation workflow.

**Dependencies:** OPENAI_API_KEY

---

### investment_report_generator.py

**Status:** NOT TESTED

**Description:** Financial analysis pipeline.

**Dependencies:** OPENAI_API_KEY

---

### employee_recruiter.py

**Status:** NOT TESTED

**Description:** Recruitment workflow.

**Dependencies:** OPENAI_API_KEY

---

## 04_gemini/

See [04_gemini/README.md](04_gemini/README.md) for detailed testing instructions.

---

## 06_spotify_agent/

### spotify_agent.py

**Status:** NOT TESTED

**Description:** Spotify music assistant with playlist management.

**Dependencies:** SPOTIFY_TOKEN

---

## TESTING SUMMARY

**Summary:**
- Total examples: 50+
- Tested: 0
- Passed: 0
- Skipped: 0

**Priority Queue:**
1. Impressive agents (7 highlighted in CLAUDE.md)
2. Impressive teams (3 highlighted)
3. Impressive workflows (2 highlighted)

**Notes:**
- Many examples require external API keys
- MCP examples require Node.js
- Knowledge/RAG examples require PostgreSQL
