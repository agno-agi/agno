# Agno v2.5 Demo Cookbook — Full Context

## Overview

The `cookbook/01_demo/` directory contains a comprehensive Agno v2.5 showcase: 6 agents, 2 teams, 2 workflows, and an eval suite. It demonstrates the full Agno stack — agents with knowledge + learning, teams in coordinate and route modes, workflows with parallel steps, and AgentOS serving everything via FastAPI.

All agents use `OpenAIResponses(id="gpt-5.2")` as the model and PostgreSQL (PgVector) for knowledge/learning storage.

## Architecture

```
cookbook/01_demo/
├── db.py                          # Shared database config (all agents import from here)
├── run.py                         # AgentOS entrypoint (serves on localhost:7777)
├── registry.py                    # AgentOS registry (shared tools + models)
├── config.yaml                    # Quick prompts for AgentOS UI
├── AGENTS.md                      # Instructions for AI coding agents
├── README.md                      # User-facing documentation
├── requirements.in                # Python dependencies
├── generate_requirements.sh       # uv pip compile script
├── .gitignore                     # data/, workspace/, *.db
│
├── agents/
│   ├── __init__.py                # Empty
│   ├── ace/                       # Response drafting agent
│   ├── dash/                      # F1 data/SQL agent (copied from ~/code/dash)
│   ├── dex/                       # Relationship intelligence agent
│   ├── pal/                       # Personal second brain agent
│   ├── scout/                     # Enterprise S3 knowledge agent (copied from ~/code/scout)
│   └── seek/                      # Deep research agent
│
├── teams/
│   ├── __init__.py                # Empty
│   ├── research/                  # Seek + Scout + Dex (coordinate mode)
│   └── support/                   # Ace + Scout + Dash (route mode)
│
├── workflows/
│   ├── __init__.py                # Empty
│   ├── daily_brief/               # Calendar + Email + News → Synthesize
│   └── meeting_prep/              # Parse → Parallel research → Synthesize
│
└── evals/
    ├── __init__.py                # Empty
    ├── test_cases.py              # 16 test cases across all components
    └── run_evals.py               # CLI eval runner with Rich output
```

## Shared Infrastructure

### db.py
Central database configuration. Every agent, team, and workflow imports from here.

```python
db_url = getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")

def get_postgres_db(contents_table: str | None = None) -> PostgresDb:
    # If contents_table provided, creates a PostgresDb with knowledge_table set
    # Otherwise, plain PostgresDb for session storage

def create_knowledge(name: str, table_name: str) -> Knowledge:
    # Creates Knowledge with PgVector (hybrid search, text-embedding-3-small)
    # and a contents_db for tracking loaded content
```

**Critical detail**: `PostgresDb.__init__` does NOT accept `table_name`. Use `knowledge_table` for content tracking. The `get_postgres_db()` function handles this.

### Import Pattern
All agent files use this pattern to access shared `db.py`:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # Points to cookbook/01_demo/
from db import db_url, get_postgres_db
```

Within agent packages, everything uses relative imports (`from .tools import ...`, `from ..paths import ...`).

### run.py
AgentOS entrypoint. Imports all 9 agents, 2 teams, 2 workflows. Serves on localhost:7777 via `agent_os.serve(app="run:app", reload=True)`.

### registry.py
Provides shared tools (DuckDuckGoTools, CalculatorTools) and models (gpt-5.2, gpt-5-mini) to the AgentOS UI.

## The 6 Agents

### 1. Dash (data/SQL agent)
- **ID**: `dash` (reasoning variant: `reasoning-dash`)
- **Source**: Copied from `~/code/dash`, adapted imports
- **Purpose**: Self-learning F1 data analyst. Queries PostgreSQL tables, provides insights not just query results.
- **Tools**: SQLTools (connects to same db_url), introspect_schema (runtime table inspection), save_validated_query (saves working SQL to knowledge), Exa MCP
- **Knowledge**: Static curated knowledge (table schemas, business rules, golden SQL queries) + dynamic learnings
- **Context builders**: `context/semantic_model.py` loads table JSON metadata, `context/business_rules.py` loads business metrics/rules. Both inject into the system prompt via f-string.
- **Data**: F1 racing data loaded via `scripts/load_data.py` (downloads CSVs from S3, loads into PostgreSQL). Knowledge loaded via `scripts/load_knowledge.py`.
- **Key files**: `agent.py`, `paths.py`, `tools/introspect.py`, `tools/save_query.py`, `context/semantic_model.py`, `context/business_rules.py`, `knowledge/tables/*.json`, `knowledge/queries/common_queries.sql`, `knowledge/business/metrics.json`

### 2. Scout (enterprise knowledge agent)
- **ID**: `scout` (reasoning variant: `reasoning-scout`)
- **Source**: Copied from `~/code/scout`, stripped Google Drive/Notion/Slack connectors
- **Purpose**: Enterprise knowledge navigator. Finds information across S3 storage. Works like "Claude Code for enterprise docs."
- **Tools**: S3Tools (Toolkit class wrapping S3Connector), list_sources, get_metadata, save_intent_discovery, Exa MCP
- **Knowledge**: Static (source registry, intent routing rules, common patterns) + dynamic learnings
- **Context builders**: `context/source_registry.py` builds SOURCE_REGISTRY_STR from `knowledge/sources/s3.json`. `context/intent_routing.py` builds INTENT_ROUTING_CONTEXT from `knowledge/routing/intents.json`. Both injected into instructions via f-string.
- **Connectors**: `connectors/base.py` (ABC), `connectors/s3.py` (mock S3 with MOCK_BUCKETS, MOCK_FILES, MOCK_CONTENTS containing realistic enterprise docs — employee handbook, deployment runbooks, architecture docs, RFCs, OKRs, etc.)
- **Key detail**: The S3 connector is entirely mock data — no real AWS connection. All enterprise knowledge is hardcoded in `connectors/s3.py`.

### 3. Pal (personal second brain)
- **ID**: `pal`
- **Purpose**: Personal knowledge management. Captures notes, remembers context, retrieves past information.
- **Tools**: DuckDbTools (local data storage), Exa MCP
- **Knowledge**: None (uses DuckDB for structured data)
- **Learning**: Full LearningMachine (user profile, user memory, learned knowledge — all AGENTIC mode)
- **Design**: Two storage systems — DuckDB for user data (notes, tasks, snippets) and Learning for system knowledge (patterns, preferences).

### 4. Seek (deep researcher)
- **ID**: `seek` (reasoning variant: `reasoning-seek`)
- **Purpose**: Exhaustive multi-source research. Given a topic, produces structured reports.
- **Tools**: DuckDuckGoTools, Exa MCP
- **Knowledge**: Static + dynamic learnings via `create_knowledge()`
- **Methodology**: 4-phase research (Scope → Gather → Analyze → Synthesize)
- **Learning**: Learns what sources are reliable, what research patterns work, what the user cares about.

### 5. Dex (relationship intelligence)
- **ID**: `dex`
- **Purpose**: CRM/relationship management. Tracks people, interactions, and relationship context.
- **Tools**: DuckDbTools (profiles storage), Exa MCP (people search)
- **Knowledge**: Static knowledge via `create_knowledge()`
- **Capabilities**: Add/update people profiles, log interactions, meeting prep with relationship context, relationship mapping.

### 6. Ace (response drafting)
- **ID**: `ace`
- **Purpose**: Drafts emails, messages, and responses. Context-aware tone calibration.
- **Tools**: Exa MCP only
- **Knowledge**: Static knowledge via `create_knowledge()`
- **Learning**: Heavy learning focus — learns communication style preferences, tone patterns, recurring contexts.

### Agent Patterns
Every agent follows these patterns:
- **Dual knowledge**: Static `Knowledge` (curated) + dynamic `LearningMachine` learnings (discovered)
- **LearningMachine**: All use `UserProfileConfig`, `UserMemoryConfig`, `LearnedKnowledgeConfig` with `LearningMode.AGENTIC`
- **Exa MCP**: All agents have `MCPTools(url=f"https://mcp.exa.ai/mcp?exaApiKey={getenv('EXA_API_KEY', '')}&tools=web_search_exa")`
- **deep_copy for reasoning variants**: `reasoning_X = X.deep_copy(update={"id": "reasoning-X", "name": "Reasoning X", "tools": base_tools + [ReasoningTools(add_instructions=True)]})`
- **Critical**: The `deep_copy` update dict MUST include `"id"` — otherwise the reasoning variant inherits the base agent's ID, causing duplicate ID errors in AgentOS.

## The 2 Teams

### Research Team (coordinate mode)
- **ID**: `research-team`
- **Members**: Seek + Scout + Dex
- **Mode**: Coordinate (default) — leader synthesizes member responses
- **Use case**: Complex research queries needing web research + internal docs + people context

### Support Team (route mode)
- **ID**: `support-team`
- **Members**: Ace + Scout + Dash
- **Mode**: Route (`respond_directly=True`) — leader routes to the right member who responds directly
- **Routing rules**: Data/metrics/SQL → Dash, internal knowledge/docs → Scout, drafting responses → Ace

## The 2 Workflows

### Daily Brief
- **ID**: `daily-brief`
- **Steps**: `Parallel(Calendar, Email, News)` → `Synthesize`
- **Mock data**: Calendar and email tools use `@tool` decorated functions returning hardcoded realistic data (no Google OAuth). News uses DuckDuckGoTools (live).
- **Output**: Structured brief with Priority Actions, Schedule, Inbox Highlights, Industry Pulse

### Meeting Prep
- **ID**: `meeting-prep`
- **Steps**: `Parse Meeting` → `Parallel(Attendees, Internal Context, External Context)` → `Synthesize`
- **Mock data**: Meeting details and internal docs use `@tool` decorated functions. Attendee research and external context use DuckDuckGoTools (live).
- **Output**: Meeting overview, attendee context, key data points, talking points, potential questions

### Workflow Patterns
- Use `Step(name=..., agent=...)` for single-agent steps
- Use `Parallel(Step(...), Step(...), name=...)` for concurrent execution
- Workflow agents are lightweight (no knowledge/learning) — they're single-purpose
- All workflows use `@tool` decorator imported from `agno.tools` (NOT `agno.tools.function`)

## Evals

### test_cases.py
16 test cases defined as `TestCase(agent, question, expected_strings, category, match_mode)`:
- Dash: 3 tests (F1 data queries)
- Scout: 3 tests (enterprise knowledge)
- Pal: 2 tests (identity + note capture)
- Seek: 1 test (identity)
- Dex: 1 test (identity)
- Ace: 2 tests (identity + drafting)
- Research Team: 1 test
- Support Team: 1 test
- Daily Brief: 1 test
- Meeting Prep: 1 test

### run_evals.py
CLI runner with Rich output. Supports `--agent`, `--category`, `--verbose` flags. Uses string matching (case-insensitive) with "all" (all expected strings must appear) and "any" (at least one must appear) modes.

The `get_component()` function lazily imports each agent/team/workflow by ID, calls `.run(question)`, and checks `.content` for expected strings. Works for agents (RunResponse), teams (TeamRunOutput), and workflows (WorkflowRunOutput) — all have `.content`.

## Prerequisites

1. **PgVector**: `./cookbook/scripts/run_pgvector.sh` (Docker, port 5532)
2. **Demo venv**: `.venvs/demo/` — set up via `./scripts/demo_setup.sh`, install extras with `uv pip install duckdb --python .venvs/demo/bin/python`
3. **Environment variables**: `OPENAI_API_KEY`, `EXA_API_KEY`
4. **For Dash**: Load F1 data with `scripts/load_data.py`, load knowledge with `scripts/load_knowledge.py`
5. **For Scout**: Load knowledge with `scripts/load_knowledge.py`

## Known Issues / Notes

- Calendar/email tools in workflows use mock data (no Google OAuth credentials)
- `PostgresDb.__init__` does NOT have `table_name` — use `knowledge_table`
- `@tool` must be imported from `agno.tools`, NOT `agno.tools.function`
- Ruff requires explicit re-exports: `from .agent import ace as ace`
- `.venvs/demo/` has no pip module — use `uv pip install`
- Agents with LearningMachine check DB tables at import time — PgVector must be running
