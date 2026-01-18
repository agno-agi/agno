# Agno AgentOS Demo

This demo showcases the power of **Agno AgentOS** - a high-performance runtime for multi-agent systems. Experience autonomous planning agents, multi-modal analysis, intelligent teams, and sophisticated workflows.

## What's Inside

### Agents (14 total)

| Category | Agent | Description |
|----------|-------|-------------|
| **Flagship** | Planning Agent | Autonomous goal decomposition and execution |
| **Flagship** | Image Analyst Agent | Multi-modal image and chart analysis |
| **Flagship** | Web Intelligence Agent | Website analysis and competitive intelligence |
| **Research** | Research Agent | Web research with Parallel tools |
| **Research** | Deep Knowledge Agent | RAG with iterative reasoning |
| **Research** | Self-Learning Research Agent | Tracks consensus over time |
| **Knowledge** | Agno Knowledge Agent | RAG with Agno documentation |
| **Knowledge** | Agno MCP Agent | MCP integration for Agno docs |
| **Data** | Code Executor Agent | Generate and run Python code |
| **Data** | Data Analyst Agent | Statistics and visualizations |
| **Finance** | Finance Agent | Financial data with YFinance |
| **Finance** | Report Writer Agent | Professional report generation |
| **Learning** | Self-Learning Agent | Learns and saves insights |
| **SQL** | SQL Agent | Text-to-SQL with F1 data |

### Teams (3 total)

| Team | Members | Use Case |
|------|---------|----------|
| **Investment Team** | Finance + Research + Report Writer | Wall Street quality investment research |
| **Research Report Team** | Research + Deep Knowledge + Report Writer | Comprehensive research reports |
| **Finance Team** | Finance + Research | Financial analysis with context |

### Workflows (3 total)

| Workflow | Phases | Use Case |
|----------|--------|----------|
| **Deep Research Workflow** | Decomposition -> Parallel Research -> Verification -> Synthesis | Professional research reports |
| **Data Analysis Workflow** | Ingestion -> Analysis -> Visualization -> Report | End-to-end data analysis |
| **Research Workflow** | Parallel research from multiple sources | Quick research synthesis |

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
export ANTHROPIC_API_KEY=***
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

## Showcase Demos

### Planning Agent (Autonomous)

Ask it to build something complex and watch it plan and execute:

```
"Build a complete market analysis of the electric vehicle industry"
```

The agent will:
1. Decompose the goal into steps
2. Research each aspect
3. Analyze the data
4. Produce a comprehensive report

### Investment Team

Get Wall Street quality research:

```
"Complete investment analysis of NVIDIA"
```

The team coordinates:
- Finance Agent gets quantitative data
- Research Agent gets qualitative insights
- Report Writer synthesizes into a professional report

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

### Image Analyst Agent

Multi-modal analysis:

```
"Analyze this chart: [image_url]"
```

Extracts data, identifies trends, provides insights.

---

## Loading Knowledge Bases

### Agno Knowledge Agent

Load the Agno documentation:

```shell
python cookbook/demo/agents/agno_knowledge_agent.py
```

### Deep Knowledge Agent

Load knowledge for deep reasoning:

```shell
python cookbook/demo/agents/deep_knowledge_agent.py
```

### SQL Agent

Load F1 data and knowledge:

```shell
python cookbook/demo/agents/sql/load_f1_data.py
python cookbook/demo/agents/sql/load_sql_knowledge.py
```

---

## Additional Resources

- [Read the Agno Docs](https://docs.agno.com)
- [Chat with us on Discord](https://agno.link/discord)
- [Ask on Discourse](https://agno.link/community)
- [Report an Issue](https://github.com/agno-agi/agno/issues)
