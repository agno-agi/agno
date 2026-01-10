# Agents 2.0: The Learning Machine

A comprehensive guide to building agents that learn, adapt, and improve.

## Overview

LearningMachine is a unified learning system that enables agents to learn from every interaction. It coordinates multiple **learning stores**, each handling a different type of knowledge:

| Store | What It Captures | Scope | Use Case |
|-------|------------------|-------|----------|
| **User Profile** | Structured fields (name, preferences) | Per user | Personalization |
| **Memories** | Unstructured observations about users | Per user | Context, preferences |
| **Session Context** | Goal, plan, progress, summary | Per session | Task continuity |
| **Entity Memory** | Facts, events, relationships | Configurable | CRM, knowledge graph |
| **Learned Knowledge** | Insights, patterns, best practices | Configurable | Collective intelligence |

## Quick Start

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# Setup
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
model = OpenAIResponses(id="gpt-5.2")

# The simplest learning agent
agent = Agent(
    model=model,
    db=db,
    learning=True,  # That's it!
)

# Use it
agent.print_response(
    "I'm Alex, I prefer concise answers.",
    user_id="alex@example.com",
    session_id="session_1",
)
```

## Running the Cookbooks

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create a virtual environment and install dependencies

Using the setup script (requires `uv`):

```bash
./cookbook/15_learning/venv_setup.sh
```

Or manually:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r cookbook/15_learning/requirements.txt
```

### 3. Export environment variables

```bash
# Required for accessing OpenAI models
export OPENAI_API_KEY=your-openai-api-key
```

### 4. Run Postgres with PgVector

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

### 5. Run Cookbooks

```bash
# Start with the basics
python cookbook/15_learning/basics/01_hello_learning.py

# Or run any specific example
python cookbook/15_learning/user_profile/02_agentic_mode.py
python cookbook/15_learning/patterns/research_agent.py
```

---

## Key Concepts

### The Goal
An agent on interaction 1000 is fundamentally better than it was on interaction 1.

### The Advantage
Instead of building memory, knowledge, and feedback systems separately, configure one system that handles all learning with consistent patterns.

### Three DX Levels

```python
# Level 1: Dead Simple
agent = Agent(model=model, db=db, learning=True)

# Level 2: Pick What You Want
agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=True,
        session_context=True,
        entity_memory=False,
        learned_knowledge=False,
    ),
)

# Level 3: Full Control
agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
)
```

### Learning Modes

Each Learning Store can be configured to run in different modes:

```python
from agno.learn import LearningMode

# ALWAYS (default for user_profile, session_context)
# - Automatic extraction after conversations
# - No agent tools needed
# - Extra LLM call per interaction

# AGENTIC (default for learned_knowledge)
# - Agent decides when to save via tools
# - More control, less noise
# - No extra LLM calls

# PROPOSE
# - Agent proposes, user confirms
# - Human-in-the-loop quality control
# - Good for high-stakes knowledge
```

### Built-in Learning Stores

#### 1. User Profile Store

Captures structured profile fields about users. Persists forever. Updated as new info is learned.

**Supported modes:** ALWAYS, AGENTIC

**Data stored:** `name`, `preferred_name`, and any custom fields you define.

See also: **Memories Store** for unstructured observations that don't fit fields.

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        user_profile=UserProfileConfig(
            mode=LearningMode.ALWAYS, # Auto-extract from conversations
        ),
  ),
)

# Session 1
agent.run("I'm Alice, I work at Netflix", user_id="alice")

# Session 2
agent.run("What do you know about me?", user_id="alice")
# → "You're Alice, you work at Netflix"
```

#### 2. Memories Store

Captures unstructured observations about users that don't fit into structured profile fields. Persists forever. Accumulates over time.

**Supported modes:** ALWAYS, AGENTIC

**When to use:** For context like "prefers detailed explanations", "works on ML projects", "mentioned budget constraints" - observations that are useful but not structured.

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, MemoriesConfig, LearningMode

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        memories=MemoriesConfig(
            mode=LearningMode.ALWAYS,  # Auto-extract observations
        ),
    ),
)

# Session 1
agent.run("I prefer code examples over explanations", user_id="alice")

# Session 2 - memory persists
agent.run("Explain async/await", user_id="alice")
# Agent knows Alice prefers code examples and adapts response
```

#### 3. Session Context Store

Captures state and summary for the current session. Updated (not accumulated) on each extraction.

**Supported modes:** ALWAYS only

**Four types of data:**
- **Summary**: A brief summary of the current session
- **Goal**: The goal of the current session (requires `enable_planning=True`)
- **Plan**: Steps to achieve the goal (requires `enable_planning=True`)
- **Progress**: Completed steps (requires `enable_planning=True`)

**Key behavior**: Builds on previous context. Even if message history is truncated, the context persists.

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        session_context=SessionContextConfig(
            enable_planning=True, # Track goal, plan, progress (adds latency)
        ),
  ),
)

# Long conversation with many messages...
# Session context automatically tracks:
# - Summary: "Debugging a React performance issue"
# - Goal: "Fix the slow render on the dashboard"
# - Plan: ["Profile components", "Find bottleneck", "Optimize"]
# - Progress: ["Profile components ✓"]
```

> **⚠️ Note:** Planning mode adds latency. Only use for task-oriented agents where tracking goal/plan/progress is valuable.

#### 4. Learned Knowledge Store

Captures reusable insights, patterns, and rules that apply across users and sessions.

**Supported modes:** AGENTIC, PROPOSE, ALWAYS

**Requires a Knowledge base** (vector database) for semantic search.

**When to use**: Self-improving agents, research agents, any agent that should get smarter over time.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearnedKnowledgeConfig, LearningMode
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Vector DB for semantic search of learnings
knowledge_base = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="agent_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=LearningMachine(
        learned_knowledge=LearnedKnowledgeConfig(
            knowledge=knowledge_base,
            mode=LearningMode.AGENTIC,  # Agent decides when to save
        ),
    ),
)

# Agent discovers an insight and saves it
agent.run("When comparing cloud providers, always check egress costs first")

# Later, different user, agent searches and applies prior learnings
agent.run("Help me compare AWS vs GCP")
# Agent searches knowledge base, finds the egress insight, applies it
```

#### 5. Entity Memory Store

Captures knowledge about external entities: companies, projects, people, products, systems.

**Supported modes:** ALWAYS, AGENTIC

**Three types of entity data:**
- **Facts** (semantic memory): Timeless truths — "Uses PostgreSQL"
- **Events** (episodic memory): Time-bound occurrences — "Launched v2 on Jan 15"
- **Relationships** (graph edges): Connections — "Bob is CTO of Acme"

**When to use**: CRM-style agents, research agents, any agent tracking external entities.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, EntityMemoryConfig

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(
            namespace="global",  # Shared across all users
            enable_agent_tools=True,  # Agent can create/update entities
        ),
    ),
)

# Agent learns about entities from conversations
agent.run("Acme Corp just migrated to PostgreSQL and hired Bob as CTO")

# Later, agent can recall and use this knowledge
agent.run("What database does Acme use?")
# → "Acme Corp uses PostgreSQL"
```

### Custom Schemas for your use case

Extend the base schemas with typed fields for your domain. The LLM sees field descriptions and updates them appropriately.

```python
from dataclasses import dataclass, field
from typing import Optional
from agno.learn.schemas import UserProfile

@dataclass
class CustomerProfile(UserProfile):
    """Extended user profile for customer support."""

    company: Optional[str] = field(
        default=None,
        metadata={"description": "Company or organization"}
    )
    plan_tier: Optional[str] = field(
        default=None,
        metadata={"description": "Subscription tier: free | pro | enterprise"}
    )
    timezone: Optional[str] = field(
        default=None,
        metadata={"description": "User's timezone (e.g., America/New_York)"}
    )
    expertise_level: Optional[str] = field(
        default=None,
        metadata={"description": "Technical level: beginner | intermediate | expert"}
    )

# Use custom schema
learning = LearningMachine(
    db=db,
    model=model,
    user_profile=UserProfileConfig(
        schema=CustomerProfile,
    ),
)
```

## Learn More

- [Agno Documentation](https://docs.agno.com)

Built with 💜 by the Agno team
