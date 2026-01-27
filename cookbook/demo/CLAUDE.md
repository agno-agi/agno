# CLAUDE.md - Demo Cookbook

Instructions for Claude Code when testing and maintaining the Demo cookbook.

---

## Quick Reference

**Test Environment:**
```bash
# Virtual environment with all dependencies
.venvs/demo/bin/python

# Required services
./cookbook/scripts/run_pgvector.sh
```

**Run any agent:**
```bash
python cookbook/demo/agents/pal_agent.py
python cookbook/demo/agents/research_agent.py "Your query here"
```

**Test results file:**
```
cookbook/demo/TEST_LOG.md
```

---

## Folder Structure

```
cookbook/demo/
├── agents/
│   ├── pal_agent.py               # Plan and Learn - stateful planning
│   ├── research_agent.py          # Professional research
│   ├── finance_agent.py           # Financial analysis
│   ├── deep_knowledge_agent.py    # RAG with iterative reasoning
│   ├── web_intelligence_agent.py  # Website analysis
│   ├── report_writer_agent.py     # Report generation
│   ├── knowledge_agent.py         # General RAG agent
│   ├── mcp_agent.py               # General MCP agent
│   ├── devil_advocate_agent.py    # Critical review (used in teams)
│   └── db.py                      # Database configuration
├── teams/
│   ├── investment_team.py         # Finance + Research + Report Writer
│   └── due_diligence_team.py      # Full due diligence with debate
├── workflows/
│   ├── deep_research_workflow.py  # 4-phase research pipeline
│   └── startup_analyst_workflow.py # VC-style due diligence
├── workspace/                     # Working directory for outputs
├── run.py                         # AgentOS entrypoint
├── config.yaml                    # Quick prompts configuration
├── db.py                          # Database configuration
├── CLAUDE.md                      # This file
├── TEST_LOG.md                    # Test results
└── README.md                      # User documentation
```

---

## Key Rules

1. **All agents use GPT-5.2**: `OpenAIResponses(id="gpt-5.2")`
2. **All agents use database**: `db=demo_db`
3. **All files have demo tests**: `if __name__ == "__main__":`
4. **Knowledge base URL**: `https://docs.agno.com/llms-full.txt`
5. **MCP server URL**: `https://docs.agno.com/mcp`

---

## Agent Categories

### Flagship Agents

| Agent | Description |
|-------|-------------|
| `pal_agent` | Plan and Learn - stateful planning with session state |
| `research_agent` | Professional research with rigorous methodology |
| `finance_agent` | Financial analysis with YFinance |

### Knowledge & Intelligence Agents

| Agent | Description |
|-------|-------------|
| `deep_knowledge_agent` | RAG with iterative reasoning |
| `web_intelligence_agent` | Website analysis and competitive intel |
| `report_writer_agent` | Professional report generation |
| `knowledge_agent` | General RAG agent |
| `mcp_agent` | General MCP integration |

### Team-Only Agents

| Agent | Description |
|-------|-------------|
| `devil_advocate_agent` | Critical review (used in Due Diligence Team) |

---

## Testing Workflow

### 1. Before Testing

1. Ensure virtual environment exists: `./scripts/demo_setup.sh`
2. Start PostgreSQL: `./cookbook/scripts/run_pgvector.sh`
3. Export API keys:
   ```bash
   export OPENAI_API_KEY=xxx
   export PARALLEL_API_KEY=xxx
   ```

### 2. Running Tests

Every agent/team/workflow can be run directly:

```bash
# Run with demo tests
python cookbook/demo/agents/pal_agent.py

# Run with specific query
python cookbook/demo/agents/pal_agent.py "Help me compare databases"

# Run teams
python cookbook/demo/teams/investment_team.py

# Run workflows
python cookbook/demo/workflows/deep_research_workflow.py
```

### 3. Updating TEST_LOG.md

After each test, update `TEST_LOG.md` with:
- Status: PASS/FAIL
- Description of what was tested
- Key results or outputs
- Any issues encountered

---

## Key Dependencies

**Required for all agents:**
- `OPENAI_API_KEY`

**Required for Parallel tools:**
- `PARALLEL_API_KEY`

**Required for all agents:**
- PostgreSQL with pgvector running on `localhost:5532`
- Database: `ai` with user `ai` password `ai`

---

## Demo Scenarios

### Flagship Demos

1. **PaL Agent** - "Help me decide between Supabase, Firebase, and PlanetScale"
2. **Investment Team** - "Complete investment analysis of NVIDIA"
3. **Due Diligence Team** - "Due diligence on Anthropic - should we invest?"
4. **Deep Research Workflow** - "Deep research: Future of AI agents in enterprise"
5. **Startup Analyst Workflow** - "Analyze this startup: Anthropic"

### Quick Validation Tests

```bash
# PaL Agent
python cookbook/demo/agents/pal_agent.py "What's 2+2?"

# Research Agent
python cookbook/demo/agents/research_agent.py "Latest AI news"

# Finance Agent
python cookbook/demo/agents/finance_agent.py "NVDA price"

# Investment Team
python cookbook/demo/teams/investment_team.py "Quick analysis of AAPL"
```

---

## Debugging

Enable debug output:
```python
import os
os.environ["AGNO_DEBUG"] = "true"
```

Check agent session:
```python
print(agent.session_id)
print(agent.run_response.messages)
```
