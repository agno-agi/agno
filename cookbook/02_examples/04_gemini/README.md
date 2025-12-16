# Gemini Agents

Let's **build production-grade agents with Gemini 3 and Agno**. We'll showcase features like:
- **NanoBanana** (native image generation)
- **Google Search & Grounding** (real-time web search)
- **URL Context** (direct web page analysis)

## Agents

The `/agents` directory contains the following agents designed to showcase Gemini 3's native multi-modal, search, and reasoning capabilities:

| Agent | File | Key Feature | Description |
| :--- | :--- | :--- | :--- |
| **Creative Studio** | `creative_studio_agent.py` | **NanoBanana** | Generates high-quality images natively using the `gemini-3-pro-image-preview` model and NanoBanana tools. |
| **Research Agent** | `research_agent.py` | **Grounding** | Performs deep web searches with `search=True`, providing factual answers with source citations. |
| **Product Comparison** | `product_comparison_agent.py` | **URL Context** | Reads content directly from URLs (`url_context=True`) to compare products or articles side-by-side. |

## Why Gemini 3 shines for agentic use cases

- **Speed**: Blazing fast inference helps to improve the chat experience when interacting with the agents.
- **Reasoning**: With strong native reasoning capabilities, Gemini 3 ensures answers are accurate and well-reasoned.
- **Search & Context**: When adding web search and URL context to the agents that use Gemini 3, the native web search provides better results than external search tools.

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
export GOOGLE_API_KEY=your-api-key
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

You can also run each agent individually:

```bash
# Image Generation
python cookbook/02_examples/04_gemini/agents/creative_studio_agent.py

# Research with Grounding
python cookbook/02_examples/04_gemini/agents/simple_research_agent.py

# Product Comparison (URL Context + Search)
python cookbook/02_examples/04_gemini/agents/product_comparison_agent.py

```

## Examples Overview

| Example                       | Agent                      | Google Features         | Memory Features                   |
| ----------------------------- | -------------------------- | ----------------------- | --------------------------------- |
| `creative_studio_agent.py`    | `creative_studio_agent`    | NanoBanana              | history                           |
| `research_agent.py`           | `research_agent`           | Grounding               | user_memories + session_summaries |
| `product_comparison_agent.py` | `product_comparison_agent` | URL Context + Grounding | user_memories + history           |

### Database

All agents use SqliteDb for persistence (configured in `db.py`):

```python
from db import demo_db
# Stores to: tmp/google_examples.db
```

## Google-Specific Features

Agno supports a variety of Google-specific features. Learn more about them [here](https://docs.agno.com/integrations/models/native/google/overview).

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




