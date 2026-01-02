# LearningMachine

Build agents that remember, adapt, and improve over time.

## What is LearningMachine?

`LearningMachine` is a unified learning system that gives agents persistent memory across three dimensions:

| Learning Type | What It Captures | Scope | Storage | Retrieval |
|:--------------|:-----------------|:------|:--------|:----------|
| **User Profile** | Preferences, facts, style | Per user | Database | `user_id` lookup |
| **Session Context** | Goals, plans, progress | Per session | Database | `session_id` lookup |
| **Learnings** | Insights, patterns, knowledge | Shared | Knowledge Base | Semantic search |

```
LearningMachine
├── UserProfileStore      → "Alice prefers concise answers with code"
├── SessionContextStore   → "We're building a REST API, completed steps 1-3"
└── LearningsStore        → "For ETF comparison, always check expense ratio AND tracking error"
```

**The Goal:** An agent on interaction 1000 is fundamentally better than it was on interaction 1.

## Cookbooks

| # | File | What You'll Learn | Key Features |
|:--|:-----|:------------------|:-------------|
| 01 | `agent_with_learning.py` | Simplest way to add learning | Auto-config, One-liner setup |
| 02 | `research_agent.py` | Real-world learning agent | Web search, PROPOSE mode, Interactive |
| 03 | `learning_machine.py` | The orchestrator in depth | 3 DX levels, Lazy init, Unified API |
| 04 | `user_profile_store.py` | Per-user memory | CRUD, Extraction, Agent tools |
| 05 | `session_context_store.py` | Per-session state | Summary, Planning mode, Replacement |
| 06 | `learnings_store.py` | Shared knowledge | Semantic search, Deduplication |
| 07 | `learning_modes.py` | BACKGROUND vs AGENTIC vs PROPOSE | Mode comparison, When to use which |
| 08 | `multi_user_sessions.py` | Isolation and concurrency | Multi-user, Multi-session, No leakage |
| 09 | `custom_stores.py` | Extend the system | Protocol implementation, Registration |
| 10 | `continuous_learning_agent.py` | Self-improving agent | Learns from every interaction |
| 11 | `plan_and_learn_agent.py` | Structured planning + learning | PaL pattern via LearningMachine |

## Learning Modes

LearningMachine supports three modes for controlling when and how learning happens:

| Mode | How It Works | Best For |
|:-----|:-------------|:---------|
| **BACKGROUND** | Automatic extraction after each response | User profiles, Session summaries |
| **AGENTIC** | Agent decides via tools | General learnings, Agent-driven |
| **PROPOSE** | Agent proposes, user confirms before saving | High-value insights, Quality control |

## Key Concepts

| Concept | What It Does | When to Use |
|:--------|:-------------|:------------|
| **LearningMachine** | Coordinates all learning stores | Always — it's the main entry point |
| **UserProfileStore** | Remembers facts about users | Personalization, Preferences |
| **SessionContextStore** | Tracks current session state | Multi-turn tasks, Planning |
| **LearningsStore** | Stores reusable insights | Knowledge that applies across users |
| **Knowledge Base** | Vector storage for semantic search | Required for LearningsStore |
| **`build_context()`** | Get memory for system prompt | Before generating responses |
| **`process()`** | Extract and save from conversation | After conversations end |
| **`get_tools()`** | Get learning tools for agent | When agent needs to save/search |

## Learning Progression

### "I just want it to work"
```
01_agent_with_learning.py → 02_research_agent.py
```

### "I want to understand how it works"
```
01 → 03_learning_machine.py → 04/05/06 (stores)
```

### "I want to extend it"
```
01 → 03 → 09_custom_stores.py
```

### "I want production patterns"
```
01 → 02 → 07_learning_modes.py → 08_multi_user_sessions.py → 10/11
```

## Quick Start

### The Simplest Agent with Learning

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.learn import LearningMachine
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# Setup
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
knowledge = Knowledge(
    vector_db=PgVector(db_url=db_url, table_name="agent_learnings"),
)

# Create agent with learning
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        db=db,
        knowledge=knowledge,  # This auto-enables learnings!
    ),
)

# That's it! The agent now:
# ✅ Remembers user preferences (UserProfileStore)
# ✅ Tracks session context (SessionContextStore)
# ✅ Saves and recalls insights (LearningsStore)
```

### Three Levels of Control

**Level 1: Dead Simple** — Just provide knowledge, everything auto-configures
```python
learning = LearningMachine(knowledge=my_kb)
```

**Level 2: Pick What You Want** — Boolean toggles
```python
learning = LearningMachine(
    db=db,
    knowledge=my_kb,
    user_profile=True,
    session_context=False,
    learnings=True,
)
```

**Level 3: Full Control** — Custom configs
```python
learning = LearningMachine(
    db=db,
    knowledge=my_kb,
    user_profile=UserProfileConfig(
        mode=LearningMode.AGENTIC,
        enable_tool=True,
    ),
    session_context=SessionContextConfig(
        enable_planning=True,
    ),
    learnings=LearningsConfig(
        mode=LearningMode.PROPOSE,
    ),
)
```

## Getting Started

### 1. Clone the repo
```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create and activate a virtual environment
```bash
uv venv .learning --python 3.12
source .learning/bin/activate
```

### 3. Install dependencies
```bash
uv pip install -r cookbook/learning/requirements.txt
```

### 4. Start PostgreSQL (for storage and knowledge)
```bash
docker run -d \
  --name pgvector \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e POSTGRES_DB=ai \
  -p 5532:5432 \
  pgvector/pgvector:pg17
```

### 5. Set your API key
```bash
export OPENAI_API_KEY=your-openai-api-key
```

### 6. Run any cookbook
```bash
python cookbook/learning/01_agent_with_learning.py
```

## Run Cookbooks Individually

```bash
# 01 - Simplest agent with learning
python cookbook/learning/01_agent_with_learning.py

# 02 - Research agent with tools and learning
python cookbook/learning/02_research_agent.py

# 03 - LearningMachine deep dive
python cookbook/learning/03_learning_machine.py

# 04 - UserProfileStore tests
python cookbook/learning/04_user_profile_store.py

# 05 - SessionContextStore tests
python cookbook/learning/05_session_context_store.py

# 06 - LearningsStore tests
python cookbook/learning/06_learnings_store.py

# 07 - Learning modes comparison
python cookbook/learning/07_learning_modes.py

# 08 - Multi-user isolation tests
python cookbook/learning/08_multi_user_sessions.py

# 09 - Custom stores examples
python cookbook/learning/09_custom_stores.py

# 10 - Continuous learning agent
python cookbook/learning/10_continuous_learning_agent.py

# 11 - Plan and Learn agent
python cookbook/learning/11_plan_and_learn_agent.py
```

## File Structure

```
cookbook/learning/
├── 01_agent_with_learning.py        # Simplest example
├── 02_research_agent.py             # Real-world agent
├── 03_learning_machine.py           # Orchestrator deep dive
├── 04_user_profile_store.py         # Per-user memory
├── 05_session_context_store.py      # Per-session state
├── 06_learnings_store.py            # Shared knowledge
├── 07_learning_modes.py             # Mode comparison
├── 08_multi_user_sessions.py        # Isolation testing
├── 09_custom_stores.py              # Extending the system
├── 10_continuous_learning_agent.py  # Self-improving agent
├── 11_plan_and_learn_agent.py       # PaL via LearningMachine
├── requirements.txt
└── README.md
```

## Learn More

- [Agno Documentation](https://docs.agno.com)

---

Built with 💜 by the Agno team
