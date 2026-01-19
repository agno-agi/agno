# CLAUDE.md - Showcase Cookbook

Instructions for Claude Code when building and testing the showcase cookbooks.

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

---

## Critical Note: Model Names

**DO NOT change these model IDs** (they are correct, newer than training data):
- `gemini-3-flash-preview`
- `gpt-5.2`
- `claude-sonnet-4-5`

---

## Testing Workflow

1. Start with Tier 1 agents (no external deps)
2. Start PostgreSQL for database-backed agents
3. Test agents with API keys you have available
4. Mark MCP agents as "Requires MCP" if npx not available

---

## Debugging

Enable debug output:
```bash
export AGNO_DEBUG=True
```
