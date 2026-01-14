# CLAUDE.md - Showcase Cookbook

Instructions for Claude Code when testing the showcase cookbooks.

---

## Quick Reference

**Test Environment:**
```bash
# Virtual environment with all dependencies
.venvs/demo/bin/python

# Start PostgreSQL with PgVector (required for some agents)
./cookbook/scripts/run_pgvector.sh
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/<file>.py
```

**Test results file:**
```
cookbook/01_showcase/TEST_LOG.md
```

---

## Folder Structure

| Folder | Count | Description |
|:-------|------:|:------------|
| `01_agents/` | 10 | Impressive standalone agents |
| `02_teams/` | 5 | Multi-agent team examples |
| `03_workflows/` | 4 | Multi-step workflow examples |
| `04_gemini/` | 5 | Gemini partner showcase |

**Total: 24+ Python files**

---

## Critical Note: Model Names

**DO NOT change these model IDs** (they are correct, newer than training data):
- `gemini-3-flash-preview`
- `gpt-5.2`
- `claude-sonnet-4-5`

---

## Testing Priority

Test in this order (most impressive first):

### Tier 1: Must Work (Core showcase)
1. `01_agents/self_learning_agent.py` - Learning Machine demo
2. `02_teams/tic_tac_toe_team.py` - Multi-model game
3. `03_workflows/startup_idea_validator.py` - Workflow demo
4. `04_gemini/agents/pal_agent.py` - Plan and Learn (most unique)

### Tier 2: Impressive Features
5. `01_agents/sql/sql_agent.py` - Text-to-SQL with F1 data
6. `01_agents/deep_knowledge_agent.py` - Agentic RAG
7. `02_teams/autonomous_startup_team.py` - Autonomous mode
8. `03_workflows/research_workflow.py` - Parallel execution

### Tier 3: External Dependencies
9. `01_agents/deep_research_agent_exa.py` - Requires EXA_API_KEY
10. `01_agents/startup_analyst_agent.py` - Requires SGAI_API_KEY
11. `01_agents/social_media_agent.py` - Requires X_API_KEY
12. `01_agents/airbnb_mcp.py` - Requires MCP/npx

---

## API Keys Required

| Key | Required For |
|:----|:-------------|
| `GOOGLE_API_KEY` | Most agents (default model) |
| `OPENAI_API_KEY` | OpenAI-based agents, image generation |
| `EXA_API_KEY` | deep_research_agent_exa.py |
| `SGAI_API_KEY` | startup_analyst_agent.py |
| `X_API_KEY` | social_media_agent.py |
| `CARTESIA_API_KEY` | translation_agent.py |
| `COHERE_API_KEY` | recipe_rag_image.py (embedder) |

---

## Services Required

| Service | Required For | Start Command |
|:--------|:-------------|:--------------|
| PostgreSQL + PgVector | Most agents with knowledge | `./cookbook/scripts/run_pgvector.sh` |
| Node.js (npx) | MCP agents | Install Node.js |

---

## Known Issues

1. **MCP agents need Node.js** - airbnb_mcp.py, skyplanner_mcp_team.py require npx
2. **Rate limits** - Some agents make many API calls
3. **External APIs** - Some agents depend on third-party services

---

## Files Removed (cleanup)

The following were removed as duplicates or too basic:
- `finance_agent.py` - Duplicate of quickstart
- `deep_knowledge.py` - Duplicate of deep_knowledge_agent.py
- `reasoning_finance_agent.py` - Too basic (24 lines)
- `finance_team.py` - Broken imports
- `simple_research_agent.py` - Too basic

---

## Testing Workflow

1. Start with Tier 1 agents (no external deps)
2. Start PostgreSQL for database-backed agents
3. Test agents with API keys you have available
4. Mark MCP agents as "Requires MCP" if npx not available

---

## Debugging

Enable debug output:
```python
import os
os.environ["AGNO_DEBUG"] = "true"
```
