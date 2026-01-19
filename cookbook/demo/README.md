# Agno AgentOS Demo

This demo showcases what's possible with **Agno AgentOS** - a high-performance runtime for multi-agent systems.

## What's Inside

### Agents

| Agent | Description |
|-------|-------------|
| **PaL Agent** | Plan and Learn - stateful planning with session state and learning capture |
| **Research Agent** | Professional research with rigorous methodology and source verification |
| **Finance Agent** | Financial data retrieval and analysis with YFinance |
| **Deep Knowledge Agent** | RAG with iterative reasoning and knowledge base search |
| **Web Intelligence Agent** | Website analysis and competitive intelligence |
| **Report Writer Agent** | Professional report generation and synthesis |
| **Knowledge Agent** | General RAG agent with knowledge base (uses docs.agno.com as example) |
| **MCP Agent** | General MCP integration (uses docs.agno.com/mcp as example) |

### Teams (2 total)

| Team | Members | Use Case |
|------|---------|----------|
| **Investment Team** | Finance + Research + Report Writer | Wall Street quality investment research |
| **Due Diligence Team** | Research + Web Intel + Finance + Devil's Advocate + Report Writer | Rigorous due diligence with debate |

### Workflows (2 total)

| Workflow | Phases | Use Case |
|----------|--------|----------|
| **Deep Research Workflow** | Decomposition -> Parallel Research -> Verification -> Synthesis | Professional research reports |
| **Startup Analyst Workflow** | Snapshot -> Deep Analysis -> Critical Review -> Report | VC-style due diligence |

---

## Getting Started

### 1. Clone the repository

```shell
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create a virtual environment

```shell
uv venv .demoenv --python 3.12
source .demoenv/bin/activate
```

### 3. Install dependencies

```shell
uv pip install -r cookbook/demo/requirements.txt
```

### 4. Run Postgres with PgVector

We use PostgreSQL for storing agent sessions, memories, metrics, evals, and knowledge. Install [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) and run:

```shell
./cookbook/scripts/run_pgvector.sh
```

Or use Docker directly:

```shell
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql \
  -v pgvolume:/var/lib/postgresql \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:18
```

### 5. Export API Keys

```shell
export OPENAI_API_KEY=***
export PARALLEL_API_KEY=***
```

### 6. Run the demo AgentOS

```shell
python cookbook/demo/run.py
```

### 7. Connect to the AgentOS UI

- Open [os.agno.com](https://os.agno.com/)
- Connect to `http://localhost:7777`

---

## Running Individual Agents

Every agent can be run directly with demo tests:

```shell
# Run PaL Agent with demo tests
python cookbook/demo/agents/pal_agent.py

# Run with a specific query
python cookbook/demo/agents/pal_agent.py "Help me compare cloud providers"

# Run other agents
python cookbook/demo/agents/research_agent.py
python cookbook/demo/agents/finance_agent.py
python cookbook/demo/agents/web_intelligence_agent.py
python cookbook/demo/agents/report_writer_agent.py
python cookbook/demo/agents/deep_knowledge_agent.py
python cookbook/demo/agents/knowledge_agent.py
python cookbook/demo/agents/mcp_agent.py
```

---

## Showcase Demos

### PaL Agent (Plan and Learn)

Ask it to build something complex and watch it plan, execute, and learn:

```
"Help me decide between Supabase, Firebase, and PlanetScale for my startup"
```

The agent will:
1. Create a structured plan with success criteria
2. Research each option
3. Compare and analyze
4. Save learnings for future tasks

### Investment Team

Get Wall Street quality research:

```
"Complete investment analysis of NVIDIA"
```

The team coordinates:
- Finance Agent gets quantitative data
- Research Agent gets qualitative insights
- Report Writer synthesizes into a professional report

### Due Diligence Team

Rigorous analysis with debate:

```
"Due diligence on Anthropic - should we invest?"
```

The team includes:
- Research, Web Intel, and Finance gather evidence
- Devil's Advocate challenges findings
- Report Writer synthesizes with disagreements noted

### Deep Research Workflow

Professional-grade research:

```
"Deep research: What's the future of AI agents in enterprise?"
```

4-phase process:
1. Topic decomposition
2. Parallel research from multiple sources
3. Fact verification
4. Report synthesis

### Startup Analyst Workflow

VC-style due diligence:

```
"Analyze this startup: Anthropic"
```

4-phase process:
1. Quick snapshot (profile, market, news)
2. Deep strategic analysis
3. Critical review (challenge findings)
4. Final report with verdict

---

## Loading Knowledge Bases

### Knowledge Agent

Load the knowledge base (runs automatically on first use):

```shell
python cookbook/demo/agents/knowledge_agent.py
```

### Deep Knowledge Agent

Load knowledge for deep reasoning:

```shell
python cookbook/demo/agents/deep_knowledge_agent.py
```

---

## Technical Details

- **Model**: All agents use GPT-5.2
- **Database**: PostgreSQL with PgVector on localhost:5532
- **Persistence**: All agents have database integration for session persistence

---

## Additional Resources

- [Read the Agno Docs](https://docs.agno.com)
- [Chat with us on Discord](https://agno.link/discord)
- [Ask on Discourse](https://agno.link/community)
- [Report an Issue](https://github.com/agno-agi/agno/issues)
