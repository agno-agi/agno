# Agno Demo

6 self-learning agents, 2 teams, and 2 workflows served via AgentOS. Each agent learns from interactions and improves with every use.

## Architecture

All agents share a common foundation:

- **Model**: `OpenAIResponses(id="gpt-5.2")`
- **Storage**: PostgreSQL + PgVector for knowledge, learnings, and chat history
- **Knowledge**: Dual knowledge system -- static curated knowledge + dynamic learnings discovered at runtime
- **Search**: Hybrid search (semantic + keyword) with OpenAI embeddings (`text-embedding-3-small`)
- **Learning**: `LearningMachine` in `AGENTIC` mode -- agents decide when to save learnings

## Agents

### Dash - Self-Learning Data Agent

Analyzes an F1 racing dataset via SQL. Provides insights and context, not just raw query results. Remembers column quirks, date formats, and successful queries across sessions.

### Scout - Self-Learning Context Agent

Finds information (context) across company S3 storage using grep-like search and full document reads. Knows what sources exist and routes queries to the right bucket. Learns intent from repeated use.

### Pal - Personal Agent that Learns

Captures and retrieves personal knowledge: notes, bookmarks, people, meetings, projects. Uses DuckDB for structured content and the learning system for schema and research findings.

### Seek - Deep Research Agent

Conducts exhaustive multi-source research and produces structured, well-sourced reports. Follows a 4-phase methodology: scope, gather, analyze, synthesize.

### Dex - Relationship Intelligence Agent

Builds living profiles of people you interact with. Tracks interactions, maps connections, and prepares meeting briefs with full context.

### Ace - Response Agent

Drafts replies to emails, messages, and questions. Learns your tone, communication style, and preferences for different contexts (client vs. team vs. exec).

## Teams

| Team | Members | Mode | Purpose |
|------|---------|------|---------|
| **Research Team** | Seek + Scout + Dex | Coordinate | Breaks research into dimensions (external, internal, people) and delegates to specialists. Synthesizes findings into a comprehensive report. |
| **Support Team** | Ace + Scout + Dash | Route | Routes questions to the right specialist: data/metrics to Dash, internal docs to Scout, drafting to Ace. |

## Workflows

| Workflow | Steps | Purpose |
|----------|-------|---------|
| **Daily Brief** | 3 parallel gatherers (calendar, email, news) then 1 synthesizer | Morning briefing with priorities, schedule highlights, inbox summary, and industry news. Uses mock calendar/email data and live Parallel web search for news. |
| **Meeting Prep** | Parse meeting, then 3 parallel researchers (attendees, internal docs, external context), then 1 synthesizer | Deep preparation with attendee context, key data points, talking points, and anticipated questions. Uses mock meeting data and live Parallel web search. |

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
export EXA_API_KEY="..."         # Optional because Exa MCP is currently free
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
- Click on "Add AgentOS"
- Add `http://localhost:7777` as an endpoint
- Click "Connect"
- You should see the demo agents and workflows
- Interact with the agents and workflows via the web interface

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
