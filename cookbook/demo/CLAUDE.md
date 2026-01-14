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
cd cookbook/01_demo
.venvs/demo/bin/python -c "
from agents.<agent_name> import <agent_name>
response = <agent_name>.run('your query here')
print(response.content)
"
```

**Test results file:**
```
cookbook/01_demo/TEST_LOG.md
```

---

## Folder Structure

```
cookbook/01_demo/
├── agents/
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
│   └── finance_team.py             # Finance + Research team
├── workflows/
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

### Code & Data Agents (No External Dependencies)

| Agent | Model | Description |
|-------|-------|-------------|
| `code_executor_agent` | GPT-5-mini | Generates and executes Python code |
| `data_analyst_agent` | GPT-5-mini | Statistics and chart creation |

**Test these first** - They only need the demo Python environment.

### Research Agents (Need API Keys)

| Agent | Model | Description |
|-------|-------|-------------|
| `research_agent` | Claude Sonnet | Web research with Parallel tools |
| `report_writer_agent` | Claude Sonnet | Professional reports with research |
| `finance_agent` | Gemini Flash | Financial analysis with YFinance |

### Knowledge Agents (Need PostgreSQL)

| Agent | Model | Description |
|-------|-------|-------------|
| `self_learning_agent` | GPT-5.2 | Learns and saves insights |
| `self_learning_research_agent` | GPT-5.2 | Tracks research consensus |
| `deep_knowledge_agent` | GPT-5.2 | Deep reasoning with knowledge |
| `agno_knowledge_agent` | Claude Sonnet | RAG with Agno docs |
| `sql_agent` | Claude Sonnet | Text-to-SQL with F1 data |

### Special Agents

| Agent | Model | Description |
|-------|-------|-------------|
| `agno_mcp_agent` | Claude Sonnet | Uses MCP for Agno docs |

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
   ```

### 2. Running Tests

**Quick test pattern:**
```bash
cd cookbook/01_demo
.venvs/demo/bin/python -c "
import sys
sys.path.insert(0, '.')
from agents.<agent> import <agent>
response = <agent>.run('test query')
print(response.content[:2000])
"
```

**Example - Test code_executor_agent:**
```bash
.venvs/demo/bin/python -c "
import sys
sys.path.insert(0, '.')
from agents.code_executor_agent import code_executor_agent
response = code_executor_agent.run('Calculate the first 10 Fibonacci numbers')
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
- `GOOGLE_API_KEY` or `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`

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

---

## Demo Scenarios

### Impressive Demos (Show These)

1. **Code Executor** - "Generate 10 random user profiles with name, email, and age as JSON"
2. **Data Analyst** - "Analyze this data and create a bar chart: Q1: 25000, Q2: 31000, Q3: 28000, Q4: 35000"
3. **Report Writer** - "Write an executive summary on the current state of AI agents"
4. **Self-Learning Research** - "What is the consensus on AI agents in enterprise production?"
5. **SQL Agent** - "Who won the most F1 championships in the 1990s?"

### Quick Validation Tests

```python
# Code Executor
"Calculate the first 20 Fibonacci numbers"

# Data Analyst
"Calculate mean, median, and std for: 23, 45, 67, 89, 12, 34, 56"

# Report Writer
"Write a brief executive summary on electric vehicles"

# Finance Agent
"What's NVIDIA's current stock price and P/E ratio?"

# Research Agent
"Latest breakthroughs in small language models"
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
