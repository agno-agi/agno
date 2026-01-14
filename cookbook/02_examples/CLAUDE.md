# CLAUDE.md - Examples Cookbook

Instructions for Claude Code when testing the examples cookbooks.

---

## Quick Reference

**Test Environment:**
```bash
# Virtual environment with all dependencies
.venvs/demo/bin/python

# Start PostgreSQL with PgVector (required for many examples)
./cookbook/scripts/run_pgvector.sh
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/02_examples/01_agents/<file>.py
```

**Test results file:**
```
cookbook/02_examples/TEST_LOG.md
```

---

## Folder Structure

This cookbook is organized into subfolders by topic:

| Folder | Description | Count |
|:-------|:------------|------:|
| `01_agents/` | Individual agent examples | 38 |
| `02_teams/` | Multi-agent team examples | 13 |
| `03_workflows/` | Multi-step workflow examples | 5 |
| `04_gemini/` | Gemini-specific examples (well-documented) | 6+ |
| `05_streamlit_apps/` | Streamlit UI examples | varies |
| `06_spotify_agent/` | Spotify integration example | 2 |

---

## Testing Workflow

### 1. Before Testing

**Start PostgreSQL:**
```bash
./cookbook/scripts/run_pgvector.sh
```

**API Keys Required:**
- `OPENAI_API_KEY` - Most examples
- `GOOGLE_API_KEY` - Gemini examples
- `EXA_API_KEY` - Research agents
- `FIRECRAWL_API_KEY` - Web scraping agents
- `SGAI_API_KEY` - ScrapeGraph agents
- `X_API_KEY` - Twitter/X agents
- `CARTESIA_API_KEY` - Voice synthesis
- `GROQ_API_KEY` - Groq/Llama models
- `SPOTIFY_TOKEN` - Spotify agent

### 2. Running Tests

```bash
# Individual agent
.venvs/demo/bin/python cookbook/02_examples/01_agents/startup_analyst_agent.py

# Team example
.venvs/demo/bin/python cookbook/02_examples/02_teams/tic_tac_toe_team.py

# Workflow
.venvs/demo/bin/python cookbook/02_examples/03_workflows/startup_idea_validator.py
```

### 3. Updating TEST_LOG.md

After each test, update `cookbook/02_examples/TEST_LOG.md` with results.

---

## Highlighted Examples

### Impressive Agents (01_agents/)

| File | What's Impressive | Dependencies |
|:-----|:------------------|:-------------|
| `startup_analyst_agent.py` | Comprehensive due diligence with ScrapeGraph | SGAI_API_KEY |
| `airbnb_mcp.py` | MCP + Llama 4 for Airbnb search | GROQ_API_KEY, npx |
| `deep_research_agent_exa.py` | Research with citations and structured output | EXA_API_KEY |
| `recipe_rag_image.py` | Multi-modal RAG with image generation | PgVector, Cohere |
| `translation_agent.py` | Voice synthesis with Cartesia | CARTESIA_API_KEY |
| `social_media_agent.py` | X/Twitter brand intelligence | X_API_KEY |
| `deep_knowledge.py` | Iterative knowledge base search | PgVector |

### Impressive Teams (02_teams/)

| File | What's Impressive | Dependencies |
|:-----|:------------------|:-------------|
| `tic_tac_toe_team.py` | GPT-4o vs Gemini playing games | OpenAI, Google |
| `skyplanner_mcp_team.py` | Multiple MCP servers + structured output | Google Maps, npx |
| `autonomous_startup_team.py` | Autonomous multi-agent startup team | OpenAI |

### Impressive Workflows (03_workflows/)

| File | What's Impressive | Dependencies |
|:-----|:------------------|:-------------|
| `startup_idea_validator.py` | 4-phase validation with structured output | OpenAI |
| `investment_report_generator.py` | Financial analysis pipeline | OpenAI |

---

## Known Issues

1. **MCP agents require npx** - Need Node.js installed for MCP server examples
2. **Rate limits** - Some agents make many API calls, may hit rate limits
3. **External services** - Some agents depend on external APIs that may change

---

## Mediocre Examples (Consider Removing)

These examples are too simple or redundant:

| File | Issue |
|:-----|:------|
| `fibonacci_agent.py` | Too trivial - not impressive |
| `basic_agent.py` | Overlaps with 00_getting_started |
| `agent_with_tools.py` | Overlaps with 00_getting_started |
| `movie_recommendation.py` | Same pattern as book_recommendation |
| `book_recommendation.py` | Same pattern as movie_recommendation |
| `shopping_partner.py` | Same pattern as recommendation agents |

---

## Reference

For a well-structured subfolder, see `04_gemini/` which has:
- Complete README.md with featured agent
- Table of agents with descriptions
- Getting started guide
- Screenshots
