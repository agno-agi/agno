# Gemini Agents

Production-grade AI agents powered by Gemini and Agno. This cookbook demonstrates how to combine Gemini's native capabilities with Agno's agent runtime, memory, knowledge, and state management systems.

## Agents

| Agent | Description | Key Features |
| :--- | :--- | :--- |
| **Simple Research Agent** | Web research with cited answers | Grounding, Search |
| **Creative Studio** | High-quality image generation | Imagen |
| **Product Comparison** | Analyze and compare content from URLs | URL Context |
| **Self-Learning Agent** | Answers questions and learns from successful runs | Parallel Search, YFinance, Knowledge Base |
| **Self-Learning Research Agent** | Tracks internet consensus over time with historical snapshots | Parallel Search, Continuous Learning |
| **PaL (Plan and Learn)** | Disciplined planning and execution with learning | Session State, Knowledge Base, Parallel Search |

## ✨ Featured: PaL — Plan and Learn Agent

> *Plan. Execute. Learn. Repeat.*

PaL is a disciplined execution agent that:

- **Plans** — Breaks goals into steps with clear success criteria
- **Executes** — Works through steps sequentially, verifying completion
- **Adapts** — Modifies plans mid-flight when requirements change
- **Learns** — Captures reusable patterns from successful executions

**New pattern**: PaL uses Agno's incredible **Session State** feature — persistent state that survives across conversation turns and sessions. Track progress, manage workflows, and build stateful agents.

```python
# Session state persists across runs
session_state={
    "objective": None,
    "plan": [],
    "current_step": 1,
    "status": "no_plan",
}
```

[→ See the full implementation](agents/pal_agent.py)

## Native Gemini Features

Agno supports all native Gemini capabilities out of the box:

| Feature | Parameter | Description |
| :--- | :--- | :--- |
| Google Search | `search=True` | Search the web (Gemini 2.0+) |
| Grounding | `grounding=True` | Search with citations |
| URL Context | `url_context=True` | Analyze web page content |
| Imagen | `ImagenTools()` | Image generation toolkit |

## Why Gemini + Agno

- **Speed** — Fast inference makes agent workflows feel responsive
- **Reasoning** — Strong native reasoning with fewer hallucinations
- **Built-in primitives** — Image generation, URL context, and grounding are first-class
- **Production-ready** — Agno provides persistence, memory, knowledge, and state management

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create and activate a virtual environment

```bash
uv venv .gemini-agents --python 3.12
source .gemini-agents/bin/activate
```

### 3. Install dependencies

```bash
uv pip install -r cookbook/02_examples/04_gemini/requirements.txt
```

### 4. Set environment variables

```bash
# Required for Gemini models
export GOOGLE_API_KEY=your-google-api-key

# Required for agents using parallel search
export PARALLEL_API_KEY=your-parallel-api-key
```

### 5. Run Postgres with PgVector

Postgres stores agent sessions, memory, knowledge, and state. Install [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) and run:

```bash
./cookbook/scripts/run_pgvector.sh
```

Or run directly:

```bash
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

### 6. Run the Agent OS

Agno provides a web interface for interacting with agents. Start the server:

```bash
python cookbook/02_examples/04_gemini/run.py
```

Then visit [os.agno.com](https://os.agno.com/?utm_source=github&utm_medium=cookbook&utm_campaign=gemini&utm_content=cookbook-gemini-flash&utm_term=gemini-flash) and add `http://localhost:7777` as an endpoint.

---

## Run Agents Individually

```bash
# Research with grounding and citations
python cookbook/02_examples/04_gemini/agents/simple_research_agent.py

# Image generation
python cookbook/02_examples/04_gemini/agents/creative_studio_agent.py

# Compare products from URLs
python cookbook/02_examples/04_gemini/agents/product_comparison_agent.py

# Self-learning agent
python cookbook/02_examples/04_gemini/agents/self_learning_agent.py

# Self-learning research agent
python cookbook/02_examples/04_gemini/agents/self_learning_research_agent.py

# PaL - Plan and Learn Agent
python cookbook/02_examples/04_gemini/agents/pal_agent.py
```

## File Structure

```
cookbook/02_examples/04_gemini/
├── agents/
│   ├── creative_studio_agent.py    # Image generation
│   ├── pal_agent.py                # Plan and Learn (session state)
│   ├── product_comparison_agent.py # URL comparison
│   ├── self_learning_agent.py      # Learning from tasks
│   ├── self_learning_research_agent.py  # Research with history
│   └── simple_research_agent.py    # Grounded search
├── assets/                         # Screenshots
├── db.py                           # Database configuration
├── run.py                          # Agent OS entrypoint
└── README.md
```
## Screenshots

<p align="center">
  <img src="assets/agentos_2.png" alt="Creative Studio Demo" width="500"/>
  <br>
  <em>Creative Studio: AI Image Generation with Imagen</em>
</p>

<p align="center">
  <img src="assets/agentos_3.png" alt="Research Agent Demo" width="500"/>
  <br>
  <em>Research Agent: Web Search &amp; Grounding</em>
</p>

<p align="center">
  <img src="assets/agentos_4.png" alt="Product Comparison Agent Demo" width="500"/>
  <br>
  <em>Product Comparison: Analyze products using URLs</em>
</p>

## Learn More

- [Agno Documentation](https://docs.agno.com/?utm_source=github&utm_medium=cookbook&utm_campaign=gemini&utm_content=cookbook-gemini-flash&utm_term=gemini-flash)
- [Gemini Native Features](https://docs.agno.com/integrations/models/native/google/overview/?utm_source=github&utm_medium=cookbook&utm_campaign=gemini&utm_content=cookbook-gemini-flash&utm_term=gemini-flash)
- [Session State Guide](https://docs.agno.com/basics/state/agent/?utm_source=github&utm_medium=cookbook&utm_campaign=gemini&utm_content=cookbook-gemini-flash&utm_term=gemini-flash)
- [Agent OS Overview](https://docs.agno.com/agent-os/overview/?utm_source=github&utm_medium=cookbook&utm_campaign=gemini&utm_content=cookbook-gemini-flash&utm_term=gemini-flash)
