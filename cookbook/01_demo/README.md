# Agno v2.5 Demo

6 self-learning agents, 2 teams, and 2 workflows served via AgentOS. Each agent learns from interactions using LearningMachine with all three subsystems (user profile, user memory, learned knowledge) in agentic mode.

## Architecture

All agents share a common foundation:

- **Model**: `OpenAIResponses(id="gpt-5.2")`
- **Storage**: PostgreSQL + PgVector for knowledge, learnings, and chat history
- **Knowledge**: Dual knowledge system -- static curated knowledge + dynamic learnings discovered at runtime
- **Search**: Hybrid search (semantic + keyword) with OpenAI embeddings (`text-embedding-3-small`)
- **Learning**: `LearningMachine` in `AGENTIC` mode -- agents decide when to save learnings
- **Research**: Exa MCP tools for web search, company research, people search, and crawling

Three agents (Dash, Scout, Seek) have reasoning variants that add `ReasoningTools` for multi-step reasoning on complex queries. This brings the total to 9 agents registered in AgentOS.

```
cookbook/01_demo/
├── agents/
│   ├── dash/          # Data agent (F1 dataset, SQL, dual knowledge)
│   ├── scout/         # Knowledge navigator (mock S3, grep-like search)
│   ├── pal/           # Second brain (DuckDB + web research)
│   ├── seek/          # Deep researcher (multi-source, structured reports)
│   ├── dex/           # Relationship intelligence (DuckDB people profiles)
│   └── ace/           # Response agent (tone adaptation, style learning)
├── teams/
│   ├── research/      # Seek + Scout + Dex (coordinate mode)
│   └── support/       # Ace + Scout + Dash (route mode)
├── workflows/
│   ├── daily_brief/   # Calendar + Email + News (parallel) -> Synthesize
│   └── meeting_prep/  # Parse -> Research (parallel) -> Synthesize
├── evals/             # 16 test cases across all components
├── config.yaml        # Quick prompts for AgentOS UI
├── db.py              # Shared database configuration
├── registry.py        # Shared tools, models, and database for AgentOS
└── run.py             # AgentOS entrypoint (localhost:7777)
```

## Agents

### Dash - Self-Learning Data Agent

Analyzes an F1 racing dataset via SQL. Provides insights and context, not just raw query results. Remembers column quirks, date formats, and successful queries across sessions.

- **Tools**: SQLTools, introspect_schema, save_validated_query, Exa MCP
- **Knowledge**: Table schemas, validated queries, business rules + dynamic learnings
- **Showcases**: Dual knowledge (curated + learned), LearningMachine, context injection

### Scout - Enterprise Knowledge Navigator

Finds information across company S3 storage using grep-like search and full document reads. Knows what sources exist and routes queries to the right bucket.

- **Tools**: S3 connector (mock), list_sources, get_metadata, save_intent_discovery, Exa MCP
- **Knowledge**: Source registry, intent routing, known patterns + dynamic learnings
- **Showcases**: Custom connectors, intent routing, transparent "not found" responses

### Pal - Personal AI Second Brain

Captures and retrieves personal knowledge: notes, bookmarks, people, meetings, projects. Uses DuckDB for structured content and the learning system for schema and research findings.

- **Tools**: DuckDbTools, Exa MCP (web_search, company_research, people_search, crawling, code_context)
- **Storage**: DuckDB (`pal.db`) for user content, PgVector for learnings
- **Showcases**: Dual storage (DuckDB + PgVector), data separation (user content vs. learnings)

### Seek - Deep Research Agent

Conducts exhaustive multi-source research and produces structured, well-sourced reports. Follows a 4-phase methodology: scope, gather, analyze, synthesize.

- **Tools**: Exa MCP, DuckDuckGoTools
- **Knowledge**: Best sources, methodologies + dynamic learnings on source reliability
- **Showcases**: Multi-tool research, structured report output, source confidence tracking

### Dex - Relationship Intelligence Agent

Builds living profiles of people you interact with. Tracks interactions, maps connections, and prepares meeting briefs with full context.

- **Tools**: DuckDbTools, Exa MCP (people_search, company_research, crawling)
- **Storage**: DuckDB (`dex.db`) with people, interactions, and connections tables
- **Showcases**: Relationship mapping, meeting prep, interaction logging

### Ace - Response Agent

Drafts replies to emails, messages, and questions. Learns your tone, communication style, and preferences for different contexts (client vs. team vs. exec).

- **Tools**: Exa MCP (web_search, company_research, crawling)
- **Knowledge**: Communication guidelines + dynamic learnings on style preferences
- **Showcases**: Context-aware tone adaptation, style learning from feedback

## Teams

| Team | Members | Mode | Purpose |
|------|---------|------|---------|
| **Research Team** | Seek + Scout + Dex | Coordinate | Breaks research into dimensions (external, internal, people) and delegates to specialists. Synthesizes findings into a comprehensive report. |
| **Support Team** | Ace + Scout + Dash | Route | Routes questions to the right specialist: data/metrics to Dash, internal docs to Scout, drafting to Ace. |

## Workflows

| Workflow | Steps | Purpose |
|----------|-------|---------|
| **Daily Brief** | 3 parallel gatherers (calendar, email, news) then 1 synthesizer | Morning briefing with priorities, schedule highlights, inbox summary, and industry news. Uses mock calendar/email data and live DuckDuckGo for news. |
| **Meeting Prep** | Parse meeting, then 3 parallel researchers (attendees, internal docs, external context), then 1 synthesizer | Deep preparation with attendee context, key data points, talking points, and anticipated questions. Uses mock meeting data and live DuckDuckGo. |

## Setup

```bash
# 1. Set up the demo virtual environment
../../scripts/demo_setup.sh

# 2. Start PostgreSQL with pgvector
../scripts/run_pgvector.sh

# 3. Load data for Dash (F1 dataset)
python -m agents.dash.scripts.load_data
python -m agents.dash.scripts.load_knowledge

# 4. Load knowledge for Scout (enterprise docs)
python -m agents.scout.scripts.load_knowledge
```

## Environment Variables

```bash
export OPENAI_API_KEY="..."      # Required for all agents
export EXA_API_KEY="..."         # Required for Exa MCP tools
export DATABASE_URL="..."        # Optional (defaults to postgresql+psycopg://ai:ai@localhost:5532/ai)
```

## Running

### Via AgentOS

```bash
python -m run
```

Then connect via [os.agno.com](https://os.agno.com) pointing to `http://localhost:7777`.

### Individual Agents

```bash
python -m agents.dash.agent
python -m agents.scout.agent
python -m agents.pal.agent
python -m agents.seek.agent
python -m agents.dex.agent
python -m agents.ace.agent
```

### Evals

16 test cases covering all agents, both teams, and both workflows. Uses string-matching validation with `all` or `any` match modes.

```bash
# Run all evals
python -m evals.run_evals

# Filter by agent
python -m evals.run_evals --agent dash

# Filter by category
python -m evals.run_evals --category dash_basic

# Verbose mode (show full responses on failure)
python -m evals.run_evals --verbose
```
