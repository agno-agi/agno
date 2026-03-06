# Agno Demo

5 agents, 1 team, 1 workflow served via AgentOS. Each agent learns from interactions and improves with every use.

## Overview

### Agents

| Agent | Description |
|-------|-------------|
| **Dash** | An adaptive data agent that queries and interprets your data — improving its understanding of your schema, metrics, and priorities with every interaction. |
| **Pal** | A personal agent that learns your preferences, context, and history. |
| **Gcode** | A lightweight coding agent that writes, reviews, and iterates on code. No bloat, no IDE lock-in — just a fast agent that gets sharper the more you use it. |
| **Scout** | A self-managing context agent that researches, drafts, and refines information stored in s3 buckets. |
| **Seek** | A self-learning research agent that investigates complex topics over time, building persistent knowledge that compounds across sessions. |

### Team

| Team | Description |
|------|-------------|
| **Research Team** | Seek and Scout working together as a team. |

### Workflow

| Workflow | Description |
|----------|-------------|
| **Daily Brief** | A workflow that sources and surfaces new developments (using seek), tracks metrics (using dash), and produces a daily digest (using scout). |

## Architecture

All agents share a common foundation:

- **Model**: `OpenAIResponses(id="gpt-5.2")`
- **Storage**: PostgreSQL + PgVector for knowledge, learnings, and chat history
- **Knowledge**: Dual knowledge system — static curated knowledge + dynamic learnings discovered at runtime
- **Search**: Hybrid search (semantic + keyword) with OpenAI embeddings (`text-embedding-3-small`)
- **Learning**: `LearningMachine` in `AGENTIC` mode — agents decide when to save learnings

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create and activate the demo virtual environment

```bash
./scripts/demo_setup.sh
source .venvs/demo/bin/activate
```

### 3. Run PgVector

```bash
./cookbook/scripts/run_pgvector.sh
```

### 4. Export environment variables

```bash
export OPENAI_API_KEY="..."      # Required for all agents
export EXA_API_KEY="..."         # Optional (Exa MCP is currently free)
```

### 5. Load data and knowledge

```bash
cd cookbook/01_demo

python -m agents.dash.scripts.load_data
python -m agents.dash.scripts.load_knowledge
python -m agents.scout.scripts.load_knowledge
```

### 6. Run the demo

```bash
python -m run
```

### 7. Connect via AgentOS

- Open [os.agno.com](https://os.agno.com) in your browser
- Click "Add AgentOS"
- Add `http://localhost:7777` as an endpoint
- Click "Connect"

## Evals

Test cases covering all agents, team, and workflow. Uses string-matching validation with `all` or `any` match modes.

```bash
# Run all evals
python -m evals.run_evals

# Filter by agent
python -m evals.run_evals --agent dash
python -m evals.run_evals --agent seek

# Verbose mode (show full responses on failure)
python -m evals.run_evals --verbose
```

## Agno Features Demonstrated

| Feature | Where |
|---------|-------|
| LearningMachine (AGENTIC mode) | All 5 agents |
| CodingTools | Gcode |
| ReasoningTools | Gcode |
| SQL Tools | Dash, Pal |
| MCP Tools | Seek (Exa), Scout (Exa), Dash (Exa), Pal (Exa) |
| Knowledge (hybrid search) | All agents |
| Persistent Memory | Pal, Seek |
| Teams (coordinate mode) | Research Team |
| Workflows (parallel steps) | Daily Brief |
| Scheduled Tasks | Daily Brief |
| AgentOS | run.py |
