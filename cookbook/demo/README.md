# Agno Demo

6 self-learning agents, 2 teams, and 2 workflows showcasing Agno's capabilities.

## Agents

| Agent | What it does | Key features |
|-------|-------------|--------------|
| **Dash** | Self-learning data agent (F1 dataset) | SQL tools, 6-layer context, knowledge base, learning |
| **Scout** | Enterprise knowledge navigator | Grep-like search, full doc reads, source registry, learning |
| **Pal** | Personal AI second brain | DuckDB storage, web research, captures and retrieves knowledge |
| **Seek** | Deep research agent | Multi-source research, structured reports, learns reliable sources |
| **Dex** | Relationship intelligence | People profiles, meeting prep, interaction tracking |
| **Ace** | Response agent that learns your voice | Email/message drafting, tone adaptation, style learning |

## Teams

| Team | Members | Mode | Use case |
|------|---------|------|----------|
| **Research Team** | Seek + Scout + Dex | Coordinate | Deep research combining external, internal, and people intelligence |
| **Support Team** | Ace + Scout + Dash | Route | Routes incoming questions to the right specialist |

## Workflows

| Workflow | Steps | Use case |
|----------|-------|----------|
| **Daily Brief** | Calendar + Email + News (parallel) -> Synthesize | Morning briefing with priorities, schedule, and news |
| **Meeting Prep** | Parse meeting -> Research attendees + Internal docs + External context (parallel) -> Prep brief | Deep preparation before any meeting |

## Setup

```bash
# 1. Start PostgreSQL with pgvector
./cookbook/scripts/run_pgvector.sh

# 2. Load data for Dash (F1 dataset)
.venvs/demo/bin/python -m cookbook.demo.agents.dash.scripts.load_data
.venvs/demo/bin/python -m cookbook.demo.agents.dash.scripts.load_knowledge

# 3. Load knowledge for Scout (enterprise docs)
.venvs/demo/bin/python -m cookbook.demo.agents.scout.scripts.load_knowledge
```

## Environment Variables

```bash
export OPENAI_API_KEY="..."      # Required
export EXA_API_KEY="..."         # Required for Exa MCP tools
export DATABASE_URL="..."        # Optional (defaults to localhost:5532)
```

## Running

### Individual Agents

```bash
.venvs/demo/bin/python cookbook/demo/agents/pal/agent.py
.venvs/demo/bin/python cookbook/demo/agents/seek/agent.py
.venvs/demo/bin/python cookbook/demo/agents/dex/agent.py
.venvs/demo/bin/python cookbook/demo/agents/ace/agent.py
```

### Via AgentOS

```bash
cd cookbook/demo && ../../.venvs/demo/bin/python run.py
```

Then connect via [os.agno.com](https://os.agno.com) pointing to `http://localhost:7777`.

### Evals

```bash
# Run all evals
cd cookbook/demo && ../../.venvs/demo/bin/python -m evals.run_evals

# Run evals for a specific agent
cd cookbook/demo && ../../.venvs/demo/bin/python -m evals.run_evals --agent dash

# Verbose mode (show full responses on failure)
cd cookbook/demo && ../../.venvs/demo/bin/python -m evals.run_evals --verbose
```
