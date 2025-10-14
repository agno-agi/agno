# Agno Demo Suite - Client Showcase

This cookbook contains comprehensive demonstrations of Agno's capabilities for client presentations, including both basic functionality and enterprise-grade advanced features.

## 📁 Demo Files

- **`real_world_showcase.py`** - 3 comprehensive consumer/lifestyle agents (Lifestyle Concierge + Study Buddy + Creative Studio)
- **`run.py`** - AgentOS production setup with agents, teams, and workflows

> Note: Fork and clone the repository if needed

### 1. Create a virtual environment

```shell
uv venv .demoenv --python 3.12
source .demoenv/bin/activate
```

### 2. Install libraries

```shell
uv pip install -r cookbook/demo/requirements.txt
```

### 3. Run PgVector

Let's use Postgres for storing data and `PgVector` for vector search.

> Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) first.

- Run using a helper script

```shell
./cookbook/scripts/run_pgvector.sh
```

- OR run using the docker run command

```shell
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pgvolume:/var/lib/postgresql/data \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:16
```

### 4. Load data

Load F1 data into the database.

```shell
python cookbook/demo/sql/load_f1_data.py
```

Load F1 knowledge base

```shell
python cookbook/demo/sql/load_knowledge.py
```

### 5. Export API Keys

We recommend using claude-3-7-sonnet for this task, but you can use any Model you like.

```shell
export ANTHROPIC_API_KEY=***
```

Other API keys are optional, but if you'd like to test:

```shell
export OPENAI_API_KEY=***
export GOOGLE_API_KEY=***
export GROQ_API_KEY=***
```

### 6. Run demos

**Option A: Real-World Showcase Demo (production-ready use cases)**

```shell
# Activate your virtual environment
source venv/bin/activate

# Export API keys
export OPENAI_API_KEY='your-openai-key'
export ANTHROPIC_API_KEY='your-anthropic-key'

# Run real-world showcase (3 comprehensive agents: Lifestyle Concierge + Study Buddy + Creative Studio)
python cookbook/demo/real_world_showcase.py
```

Then open [os.agno.com](https://os.agno.com/) and connect to http://localhost:7780 to interact with real-world use cases.

**Option B: Full AgentOS production setup**

```shell
# Run full AgentOS with more agents, teams, and workflows
python cookbook/demo/run.py
```

Then open [os.agno.com](https://os.agno.com/) to connect and interact with the demo agents.

---

## 🎯 Demo Files Overview

### 🟡 `real_world_showcase.py` - Production-Ready Use Cases

**3 Comprehensive Consumer/Lifestyle Agents:**
1. **Lifestyle Concierge** - Multi-domain personal assistant (finance/shopping/travel)
   - Stock analysis with YFinance, product recommendations, travel planning
   - Demonstrates: Tools, Structured Outputs, Guardrails, Memory, Storage, Agent State, Metrics
2. **Study Buddy** - Educational AI with RAG capabilities
   - Knowledge base search, educational resources, learning assessments
   - Demonstrates: Vector Search, Input Validation Hooks, Tool Monitoring, Memory, Metrics
3. **Creative Studio** - Multimodal AI assistant
   - Image generation with DALL-E, image analysis with GPT-4o vision
   - Demonstrates: Multimodal Capabilities, Tool Hooks, Guardrails, Metrics

**Key Features Demonstrated (ALL 10 Core Agno Features):**
- 🔧 Tools - External API integration (YFinance, DuckDuckGo, DALL-E)
- 📚 Knowledge/RAG - Vector database with hybrid search (LanceDB)
- 🎨 Multimodal - Image generation and analysis (DALL-E, GPT-4o vision)
- 🪝 Pre/Post Hooks - Input validation, tool monitoring, metrics display
- 🛡️ Guardrails - PII detection, prompt injection protection
- 💾 Agent Sessions - Persistent conversation history and context
- 🗂️ Agent State - Shopping cart, travel preferences across sessions
- 🧠 Memory - User preferences and session summaries
- 📊 Structured Outputs - Pydantic schemas for all responses
- 📈 Metrics - Automatic performance tracking (tokens, cost, latency)

**Run AgentOS:**
```bash
# Start the Real-World Showcase server
python cookbook/demo/real_world_showcase.py

# Then connect to https://os.agno.com to interact with all agents
# API available at http://localhost:7780
# Quick prompts available in showcase_config.yaml
```

---

## 📚 Additional Documentation

- **[REAL_WORLD_SHOWCASE.md](./REAL_WORLD_SHOWCASE.md)** - Comprehensive documentation for all 10 real-world use cases

---

### 7. Message us on [discord](https://agno.link/discord) if you have any questions
