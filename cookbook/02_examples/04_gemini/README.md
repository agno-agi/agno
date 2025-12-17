# Gemini Agents

This cookbook shows how to build production-grade agents with Gemini and Agno. It showcases how to combine Gemini's built-in features with Agno's agent runtime, memory, and knowledge systems.

We'll build:
| Agent | File | Key Features | Description |
| :--- | :--- | :--- | :--- |
| **Simple Research Agent** | `simple_research_agent.py` | **Grounding**, **Search** | Performs web research using built-in Gemini grounding and returns cited answers. |
| **Creative Studio** | `creative_studio_agent.py` | **NanoBanana** | Generates high-quality images natively using NanoBanana. |
| **Product Comparison** | `product_comparison_agent.py` | **URL Context** | Reads and compares content directly from URLs using `url_context=True`. |
| **Self Learning Research Agent** | `self_learning_research_agent.py` | **Parallel Search**, **Continuous Learning** | Tracks internet consensus over time, explains what changed, and stores historical snapshots for future comparison. |

## Why Gemini shines for agentic use cases

- **Speed**: Fast inference makes interactive agent workflows feel responsive.
- **Reasoning**: Strong native reasoning produces cleaner synthesis and fewer hallucinations.
- **Multi-modal primitives**: Image generation, URL context, and grounding are first-class capabilities.

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

### 4. Set Environment Variables

```bash
# Required for Gemini models
export GOOGLE_API_KEY=your-google-api-key

# Required for Self-learning Research Agent
export PARALLEL_API_KEY=your-parallel-api-key
```

### 5. Run Postgres with PgVector

We'll use postgres for storing agent sessions, memory and knowledge. Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) and run the following command to start a postgres container with PgVector.

```shell
./cookbook/scripts/run_pgvector.sh
```

OR run the following docker command directly:

```shell
docker run -d -e POSTGRES_DB=ai -e POSTGRES_USER=ai -e POSTGRES_PASSWORD=ai -e PGDATA=/var/lib/postgresql -v pgvolume:/var/lib/postgresql -p 5532:5432 --name pgvector agnohq/pgvector:18
```

### 6. Run your AgentOS

Agno provides a rich UI and web interface for agents called the AgentOS, it pairs exceptionally well with Gemini and gives our Agents a runtime, UI and control plane. You can read more about it [here](https://docs.agno.com/agent-os/overview).

```bash
python cookbook/02_examples/04_gemini/run.py
```

Visit [os.agno.com](https://os.agno.com) and add `http://localhost:7777` as an OS endpoint. You can then interact with the agents via the web interface.

### Optional: Run Agents Individually

```bash
# Image Generation
python cookbook/02_examples/04_gemini/agents/creative_studio_agent.py

# Research with Grounding
python cookbook/02_examples/04_gemini/agents/simple_research_agent.py

# Product Comparison
python cookbook/02_examples/04_gemini/agents/product_comparison_agent.py

# Self Learning Research Agent
python cookbook/02_examples/04_gemini/agents/self_learning_research_agent.py
```

## Native Gemini Features

Agno supports all native Gemini features. Learn more about them [here](https://docs.agno.com/integrations/models/native/google/overview).

| Feature       | Parameter           | Description                  |
| ------------- | ------------------- | ---------------------------- |
| Google Search | `search=True`       | Search the web (Gemini 2.0+) |
| Grounding     | `grounding=True`    | Search with citations        |
| URL Context   | `url_context=True`  | Analyze web page content     |
| NanoBanana    | `NanoBananaTools()` | Image generation toolkit     |

## Screenshots

<p align="center">
  <img src="assets/agentos_2.png" alt="Creative Studio Demo" width="500"/>
  <br>
  <em>Creative Studio: AI Image Generation (NanoBanana + Gemini)</em>
</p>

<p align="center">
  <img src="assets/agentos_3.png" alt="Research Agent Demo" width="500"/>
  <br>
  <em>Research Agent: Web Search &amp; Grounding with Google Gemini</em>
</p>

<p align="center">
  <img src="assets/agentos_4.png" alt="Product Comparison Agent Demo" width="500"/>
  <br>
  <em>Product Comparison Agent: Analyze and compare products using URLs and search</em>
</p>




