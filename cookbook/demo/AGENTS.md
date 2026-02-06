# Agno Demo - Instructions for AI Coding Agents

## Overview

This is the main Agno demo showcasing 6 agents, 2 teams, and 2 workflows served via AgentOS.

## Structure

```
cookbook/demo/
├── agents/
│   ├── dash/          # Data agent (self-learning SQL, F1 dataset)
│   ├── scout/         # Knowledge agent (enterprise docs, mock S3)
│   ├── pal/           # Personal assistant (DuckDB + research)
│   ├── seek/          # Deep researcher (multi-source research)
│   ├── dex/           # Relationship intelligence (people profiles)
│   └── ace/           # Response agent (learns your voice)
├── teams/
│   ├── research/      # Seek + Scout + Dex (coordinate mode)
│   └── support/       # Ace + Scout + Dash (route mode)
├── workflows/
│   ├── daily_brief/   # Calendar + Email + News → Brief
│   └── meeting_prep/  # Parse → Research → Prep Brief
├── evals/             # Evaluation framework
├── config.yaml        # Quick prompts for AgentOS UI
├── db.py              # Shared database configuration
├── registry.py        # Registry for AgentOS
└── run.py             # AgentOS entrypoint
```

## Running

```bash
# Start PostgreSQL with pgvector
./cookbook/scripts/run_pgvector.sh

# Load data for Dash
.venvs/demo/bin/python -m cookbook.demo.agents.dash.scripts.load_data
.venvs/demo/bin/python -m cookbook.demo.agents.dash.scripts.load_knowledge

# Load knowledge for Scout
.venvs/demo/bin/python -m cookbook.demo.agents.scout.scripts.load_knowledge

# Run individual agents
.venvs/demo/bin/python cookbook/demo/agents/pal/agent.py
.venvs/demo/bin/python cookbook/demo/agents/seek/agent.py
.venvs/demo/bin/python cookbook/demo/agents/dex/agent.py
.venvs/demo/bin/python cookbook/demo/agents/ace/agent.py

# Run via AgentOS
cd cookbook/demo && ../../.venvs/demo/bin/python run.py
```

## Key Patterns

- All agents use `OpenAIResponses(id="gpt-5.2")`
- All learning agents use `LearningMachine` with all three subsystems in `AGENTIC` mode
- Shared `db.py` at the demo root provides database connections
- `create_knowledge()` helper creates PgVector-backed knowledge bases
- Agents use `sys.path.insert` to access the shared `db.py`

## Environment Variables

- `OPENAI_API_KEY` - Required for all agents
- `EXA_API_KEY` - Required for Exa MCP tools (Pal, Seek, Dex, Ace)
- `DATABASE_URL` - Optional, defaults to `postgresql+psycopg://ai:ai@localhost:5532/ai`

## Don't

- Don't create agents in loops
- Don't use f-strings for print lines where there are no variables
- Don't use emojis
- Don't skip the learning configuration on self-learning agents
