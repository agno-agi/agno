# The 5 Levels of Agentic Software

Build a coding agent from scratch, progressively adding capabilities at each level. Same agent, five architectural stages -- from a stateless tool caller to a production agentic system.

| Level | File | What It Adds | Key Features |
|:------|:-----|:-------------|:-------------|
| 1 | `level_1_tools.py` | Tools + Instructions | CodingTools, stateless execution |
| 2 | `level_2_storage_knowledge.py` | Knowledge + Storage | ChromaDb, SqliteDb, hybrid search, session history |
| 3 | `level_3_memory_learning.py` | Memory + Learning | LearningMachine, agentic memory, ReasoningTools |
| 4 | `level_4_team.py` | Multi-Agent Team | Coder/Reviewer/Tester team with coordination |
| 5 | `level_5_api.py` | Production Infrastructure | PostgresDb, PgVector, tracing |

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create and activate a virtual environment

```bash
uv venv .venvs/levels --python 3.12
source .venvs/levels/bin/activate
```

### 3. Install dependencies

```bash
uv pip install -r cookbook/levels_of_agentic_software/requirements.txt
```

### 4. Set your API key

```bash
export OPENAI_API_KEY=your-openai-api-key
```

### 5. Run any level

```bash
python cookbook/levels_of_agentic_software/level_1_tools.py
```

## Run Each Level

```bash
# Level 1: Agent + Tools (no setup needed)
python cookbook/levels_of_agentic_software/level_1_tools.py

# Level 2: Agent + Knowledge + Storage
python cookbook/levels_of_agentic_software/level_2_storage_knowledge.py

# Level 3: Agent + Memory + Learning
python cookbook/levels_of_agentic_software/level_3_memory_learning.py

# Level 4: Multi-Agent Team
python cookbook/levels_of_agentic_software/level_4_team.py

# Level 5: Production API (requires PostgreSQL)
# Start Postgres first:
./cookbook/scripts/run_pgvector.sh
# Then run:
python cookbook/levels_of_agentic_software/level_5_api.py
```

## Run via Agent OS

Agent OS provides a web interface for interacting with your agents. All 5 levels are available in the UI so you can compare the progression interactively. Level 5 is the most complete, with production databases, learning, and tracing.

```bash
# Start PostgreSQL (required for Level 5)
./cookbook/scripts/run_pgvector.sh

# Start the server
python cookbook/levels_of_agentic_software/run.py
```

Then visit [os.agno.com](https://os.agno.com) and add `http://localhost:7777` as an endpoint.

| Agent in UI | What You Get |
|:------------|:-------------|
| L1 Coding Agent | Stateless tool calling -- no setup needed |
| L2 Coding Agent | Knowledge base + session storage (ChromaDb + SQLite) |
| L3 Coding Agent | Memory + learning -- improves over time |
| L4 Coding Team | Multi-agent team: Coder, Reviewer, Tester |
| L5 Coding Agent | Production system with PostgreSQL, PgVector, tracing |

**Start with L5 for the full experience.** Try L1-L4 to see how each capability builds on the last.

## Swap Models

These examples use OpenAI but Agno is model-agnostic:

```python
# OpenAI (default in these examples)
from agno.models.openai import OpenAIResponses
model = OpenAIResponses(id="gpt-5.2")

# Google
from agno.models.google import Gemini
model = Gemini(id="gemini-3-flash-preview")

# Anthropic
from agno.models.anthropic import Claude
model = Claude(id="claude-sonnet-4-5")
```

## When to Use Each Level

| Problem | Level |
|---------|-------|
| Task is self-contained, no memory needed | **Level 1** |
| Agent needs domain knowledge or conversation history | **Level 2** |
| Agent should improve over time | **Level 3** |
| Task needs multiple specialist perspectives | **Level 4** |
| Agent needs to serve multiple users in production | **Level 5** |

**Start at Level 1.** Most teams overbuild. Add complexity only when simplicity fails.
