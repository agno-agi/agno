# Agno Demo Suite - Client Showcase

This cookbook contains comprehensive demonstrations of Agno's capabilities for client presentations, including both basic functionality and enterprise-grade advanced features.

## 📁 Demo Files

- **`real_world_showcase.py`** - 10 production-ready use cases (5 agents + 4 teams + 1 workflow)
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

# Run real-world showcase (serves 10 use cases: 5 agents + 4 teams + 1 workflow)
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

**10 Real-World Applications:**
1. **Customer Support AI Team** - Intelligent ticket classification & resolution
2. **Content Creation Pipeline** - Automated research, writing & editing workflow
3. **Personal Finance Manager** - Investment analysis & financial advice
4. **Legal Document Analyzer** - Contract review with RAG knowledge base
5. **HR Recruitment Assistant** - Resume screening & candidate evaluation
6. **E-commerce Product Recommender** - Personalized shopping assistant
7. **Healthcare Symptom Checker** - Educational health information team
8. **Business Intelligence Team** - Data analysis & strategic insights
9. **Education Tutor** - Adaptive personalized learning with RAG
10. **Travel Planning Assistant** - Comprehensive trip planning

**Key Features Demonstrated:**
- 📋 Multi-Agent Teams (4 teams with specialized roles)
- 🔄 Complex Workflows (Research → Write → Edit pipeline)
- 💾 Memory & Knowledge (RAG with legal, medical, education knowledge bases)
- ✅ Structured Outputs (Pydantic schemas for all responses)
- 🔒 Validation & Safety (Pre-hooks for input validation, emergency detection)
- 🎯 Real-World Scenarios (Customer support, finance, healthcare, etc.)

**Run AgentOS:**
```bash
# Start the Real-World Showcase server
python cookbook/demo/real_world_showcase.py

# Then connect to https://os.agno.com to interact with all use cases
# API available at http://localhost:7780
# Full documentation: cookbook/demo/REAL_WORLD_SHOWCASE.md
```

---

## 📚 Additional Documentation

- **[REAL_WORLD_SHOWCASE.md](./REAL_WORLD_SHOWCASE.md)** - Comprehensive documentation for all 10 real-world use cases

---

### 7. Message us on [discord](https://agno.link/discord) if you have any questions
