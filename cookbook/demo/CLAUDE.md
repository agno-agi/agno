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

**Run a single agent test:**
```bash
cd cookbook/demo
.venvs/demo/bin/python -c "
from agents.<agent_name> import <agent_name>
response = <agent_name>.run('your query here')
print(response.content)
"
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
│   ├── planning_agent.py           # Autonomous goal decomposition
│   ├── image_analyst_agent.py      # Multi-modal image analysis
│   ├── web_intelligence_agent.py   # Website analysis
│   ├── code_executor_agent.py      # Generate and run Python code
│   ├── data_analyst_agent.py       # Statistics and visualizations
│   ├── report_writer_agent.py      # Professional report generation
│   ├── finance_agent.py            # Financial analysis with YFinance
│   ├── research_agent.py           # Web research with Parallel
│   ├── self_learning_agent.py      # Learning agent with knowledge base
│   ├── self_learning_research_agent.py  # Research with consensus tracking
│   ├── deep_knowledge_agent.py     # Deep reasoning with knowledge
│   ├── agno_knowledge_agent.py     # RAG with Agno docs
│   ├── agno_mcp_agent.py           # MCP integration
│   ├── db.py                       # Database configuration
│   └── sql/
│       └── sql_agent.py            # Text-to-SQL with F1 data
├── teams/
│   ├── investment_team.py          # Finance + Research + Report Writer
│   ├── research_report_team.py     # Research + Knowledge + Report Writer
│   └── finance_team.py             # Finance + Research
├── workflows/
│   ├── deep_research_workflow.py   # 4-phase research pipeline
│   ├── data_analysis_workflow.py   # End-to-end data analysis
│   └── research_workflow.py        # Parallel research workflow
├── workspace/                      # Working directory for code execution
│   └── charts/                     # Generated visualizations
├── run.py                          # AgentOS entrypoint
├── config.yaml                     # Quick prompts configuration
├── db.py                           # Database configuration
├── CLAUDE.md                       # This file
├── TEST_LOG.md                     # Test results
└── README.md                       # User documentation
```

---

## Agent Categories

### Flagship Agents (The Stars)

| Agent | Model | Description |
|-------|-------|-------------|
| `planning_agent` | Claude Sonnet | Autonomous goal decomposition and execution |
| `image_analyst_agent` | Claude Sonnet | Multi-modal image/chart analysis |
| `web_intelligence_agent` | Claude Sonnet | Website analysis and intelligence |

**Test these for wow factor** - These are the most impressive demos.

### Code & Data Agents

| Agent | Model | Description |
|-------|-------|-------------|
| `code_executor_agent` | GPT-5-mini | Generates and executes Python code |
| `data_analyst_agent` | GPT-5-mini | Statistics and chart creation |

### Research Agents (Need API Keys)

| Agent | Model | Description |
|-------|-------|-------------|
| `research_agent` | Claude Sonnet | Web research with Parallel tools |
| `report_writer_agent` | Claude Sonnet | Professional reports with research |
| `finance_agent` | GPT-5-mini | Financial analysis with YFinance |

### Knowledge Agents (Need PostgreSQL)

| Agent | Model | Description |
|-------|-------|-------------|
| `self_learning_agent` | GPT-5.2 | Learns and saves insights |
| `self_learning_research_agent` | GPT-5.2 | Tracks research consensus |
| `deep_knowledge_agent` | GPT-5.2 | Deep reasoning with knowledge |
| `agno_knowledge_agent` | Claude Sonnet | RAG with Agno docs |
| `sql_agent` | Claude Sonnet | Text-to-SQL with F1 data |

---

## Testing Workflow

### 1. Before Testing

1. Ensure virtual environment exists: `./scripts/demo_setup.sh`
2. Start PostgreSQL: `./cookbook/scripts/run_pgvector.sh`
3. Export API keys:
   ```bash
   export GOOGLE_API_KEY=xxx
   export OPENAI_API_KEY=xxx
   export ANTHROPIC_API_KEY=xxx
   export PARALLEL_API_KEY=xxx
   ```

### 2. Running Tests

**Quick test pattern:**
```bash
cd cookbook/demo
.venvs/demo/bin/python -c "
import sys
sys.path.insert(0, '.')
from agents.<agent> import <agent>
response = <agent>.run('test query')
print(response.content[:2000])
"
```

**Test Planning Agent:**
```bash
.venvs/demo/bin/python -c "
import sys
sys.path.insert(0, '.')
from agents.planning_agent import planning_agent
response = planning_agent.run('Create a competitor analysis for OpenAI vs Anthropic')
print(response.content)
"
```

**Test Investment Team:**
```bash
.venvs/demo/bin/python -c "
import sys
sys.path.insert(0, '.')
from teams.investment_team import investment_team
response = investment_team.run('Complete investment analysis of NVIDIA')
print(response.content)
"
```

**Test Deep Research Workflow:**
```bash
.venvs/demo/bin/python -c "
import sys
import asyncio
sys.path.insert(0, '.')
from workflows.deep_research_workflow import deep_research_workflow
response = asyncio.run(deep_research_workflow.run('Future of AI agents'))
print(response.content)
"
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
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`

**Required for Parallel tools:**
- `PARALLEL_API_KEY`

**Required for knowledge agents:**
- PostgreSQL with pgvector running on `localhost:5532`
- Database: `ai` with user `ai` password `ai`

**Required for data_analyst_agent:**
- `matplotlib` (install with: `uv pip install matplotlib`)

---

## Known Issues

1. **Knowledge agents need initialization** - `agno_knowledge_agent` and `deep_knowledge_agent` need their knowledge bases loaded before use.

2. **SQL agent needs F1 data** - The SQL agent expects F1 tables to exist in the database.

3. **Charts saved to workspace** - `data_analyst_agent` saves charts to `workspace/charts/`.

4. **Image Analyst needs URLs** - Provide image URLs for analysis (not local files).

---

## Demo Scenarios

### Flagship Demos (Show These First)

1. **Planning Agent** - "Build a complete market analysis of the electric vehicle industry"
2. **Investment Team** - "Complete investment analysis of NVIDIA"
3. **Deep Research Workflow** - "Deep research: Future of AI agents in enterprise"
4. **Image Analyst** - "Analyze this chart: [chart_url]"
5. **Web Intelligence** - "Analyze openai.com and summarize their products"

### Quick Validation Tests

```python
# Planning Agent
"Create a competitor analysis for OpenAI vs Anthropic"

# Image Analyst
"Analyze this chart and tell me the trend: [url]"

# Web Intelligence
"Analyze anthropic.com and summarize their products"

# Investment Team
"Should I invest in Microsoft or Google?"

# Deep Research Workflow
"What's the future of AI agents?"

# Code Executor
"Calculate the first 20 Fibonacci numbers"

# Data Analyst
"Analyze: Q1: 25000, Q2: 31000, Q3: 28000, Q4: 35000"
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
